"""Submission transport and maintainer scoring; never execute submitted code."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import zipfile

from .bundle import PRIMARY_PROTOCOL, file_digest, load_bundle, prompt_digest, validate_predictions
from .core import read_jsonl, sha, write_json, write_jsonl
from .runner import utc_now
from .score import score

SUBMISSION_MEMBERS = {"predictions.jsonl", "run.json", "submission.json"}


def validate_run(bundle, run, predictions):
    if not isinstance(run, dict):
        raise ValueError("Run metadata must be a JSON object")
    for key in ("dataset_id", "dataset_version"):
        if run.get(key) != bundle["manifest"][key]:
            raise ValueError(f"Run {key} does not match the evaluation bundle")
    if run.get("bundle_fingerprint") != bundle["fingerprint"]:
        raise ValueError("Run refers to different inputs/rubric/protocol")
    if run.get("status") != "complete" or run.get("valid_predictions") != len(bundle["ids"]):
        raise ValueError("Only complete runs can be submitted")
    if not isinstance(run.get("model"), str) or not run["model"].strip():
        raise ValueError("Model identity must be declared")
    if run.get("protocol_id") not in {PRIMARY_PROTOCOL, "external-agent-v1", "legacy-agent-3x29"}:
        raise ValueError("Unsupported run protocol")
    if run["protocol_id"] == PRIMARY_PROTOCOL and run.get("prompt_set_sha256") != prompt_digest(bundle):
        raise ValueError("Fixed prompt hash does not match the primary protocol")
    validate_predictions(predictions, bundle["ids"])


def create_submission(bundle_path, run_directory, destination):
    bundle = load_bundle(bundle_path)
    run_directory, destination = Path(run_directory), Path(destination)
    if destination.exists():
        raise ValueError("Submission destination already exists")
    rows = read_jsonl(run_directory / "predictions.jsonl")
    run = json.loads((run_directory / "run.json").read_text(encoding="utf-8"))
    validate_run(bundle, run, rows)
    predictions_bytes = (run_directory / "predictions.jsonl").read_bytes()
    if run.get("predictions_sha256") != __import__("hashlib").sha256(predictions_bytes).hexdigest():
        raise ValueError("Prediction file differs from finalized run metadata")
    run_bytes = (run_directory / "run.json").read_bytes()
    manifest = {"submission_format_version": 1, "dataset_id": bundle["manifest"]["dataset_id"],
                "bundle_fingerprint": bundle["fingerprint"], "created_at_utc": utc_now(),
                "predictions_sha256": sha(predictions_bytes.decode("utf-8")),
                "run_sha256": sha(run_bytes.decode("utf-8"))}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("predictions.jsonl", predictions_bytes)
        archive.writestr("run.json", run_bytes)
        archive.writestr("submission.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"submission": str(destination), "items": len(rows), "protocol_id": run["protocol_id"],
            "is_demo": run.get("is_demo", False), "sha256": file_digest(destination)}


def read_submission(path, bundle):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 3 or set(names) != SUBMISSION_MEMBERS:
            raise ValueError("Submission ZIP must contain exactly predictions.jsonl, run.json, submission.json")
        if any(info.file_size > 16_000_000 for info in archive.infolist()):
            raise ValueError("Submission entry is too large")
        payloads = {name: archive.read(name).decode("utf-8") for name in names}
    manifest, run = json.loads(payloads["submission.json"]), json.loads(payloads["run.json"])
    if not isinstance(manifest, dict) or manifest.get("submission_format_version") != 1:
        raise ValueError("Unsupported submission format")
    if manifest.get("bundle_fingerprint") != bundle["fingerprint"]:
        raise ValueError("Submission was generated for a different release")
    for name, key in [("predictions.jsonl", "predictions_sha256"), ("run.json", "run_sha256")]:
        if sha(payloads[name]) != manifest.get(key):
            raise ValueError(f"Submission hash mismatch: {name}")
    rows = [json.loads(line) for line in payloads["predictions.jsonl"].splitlines() if line.strip()]
    validate_run(bundle, run, rows)
    if run.get("predictions_sha256") != manifest["predictions_sha256"]:
        raise ValueError("Prediction hash differs between run and submission metadata")
    return rows, run, manifest


def grade_submission(bundle_path, submission_path, labels_path, out, *, allow_demo=False, bootstrap=2000):
    bundle = load_bundle(bundle_path)
    labels_path, out = Path(labels_path), Path(out)
    if file_digest(labels_path) != bundle["manifest"]["labels_sha256"]:
        raise ValueError("Maintainer labels differ from the release's committed label hash")
    rows, run, manifest = read_submission(submission_path, bundle)
    if run.get("is_demo") and not allow_demo:
        raise ValueError("Demo output is not a model result; --allow-demo is for pipeline verification only")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Grading output directory must be empty")
    with tempfile.TemporaryDirectory(prefix="luogubench-grade-") as scratch:
        predictions_path = Path(scratch) / "predictions.jsonl"
        write_jsonl(predictions_path, rows)
        metrics = score(labels_path, predictions_path, out, bootstrap=bootstrap)
    public = {
        "dataset_id": bundle["manifest"]["dataset_id"], "dataset_version": bundle["manifest"]["dataset_version"],
        "bundle_fingerprint": bundle["fingerprint"], "protocol_id": run["protocol_id"],
        "model": run["model"], "generation": run.get("generation", {}),
        "execution": run.get("execution", "self_reported"), "n": metrics["n"], "coverage": metrics["coverage"],
        "adapter_attempts": run.get("attempts"),
        "is_demo": run.get("is_demo", False),
        "primary_track_eligible": run["protocol_id"] == PRIMARY_PROTOCOL and not run.get("is_demo", False),
        "rationale_quality_scored": False, "graded_at_utc": utc_now(),
        "primary_metrics": metrics["primary_metrics"], "metric_targets": metrics["metric_targets"],
        "submission_sha256": file_digest(submission_path), "prediction_sha256": manifest["predictions_sha256"],
        "model_and_execution_attestation": "participant-reported, not independently attested by grader",
    }
    for key in ("accuracy", "within_one_level", "spearman_rho", "exact_matches", "within_one_count", "errors_over_one", "kendall_tau_b", "pearson_r", "mae",
                "rmse", "quadratic_weighted_kappa", "mean_signed_error", "macro_recall", "spearman_bootstrap"):
        if key in metrics:
            public[key] = metrics[key]
    write_json(out / "public_result.json", public)
    write_json(out / "submitted_run.json", run)
    return public

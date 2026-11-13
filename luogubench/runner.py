"""Provider-independent adapter process runner. No API clients or secrets here."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from . import __version__
from .bundle import (EXTERNAL_PROTOCOL, PRIMARY_PROTOCOL, item_prompt, load_bundle,
                     prompt_digest, validate_predictions)
from .core import read_jsonl, sha, write_json, write_jsonl


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_config(bundle, model, reasoning, temperature, max_output_tokens, protocol):
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Model name is required")
    return {
        "format_version": 1, "dataset_id": bundle["manifest"]["dataset_id"],
        "dataset_version": bundle["manifest"]["dataset_version"],
        "bundle_fingerprint": bundle["fingerprint"], "protocol_id": protocol,
        "model": model, "generation": {"reasoning_effort": reasoning,
                                        "temperature": temperature, "max_output_tokens": max_output_tokens},
        "runner_version": __version__, "expected_items": len(bundle["ids"]),
        "prompt_set_sha256": prompt_digest(bundle) if protocol == PRIMARY_PROTOCOL else None,
        "is_demo": False,
    }


def call_adapter(command, request, timeout):
    """Workers only call the adapter; the coordinator owns all output files."""
    item_id = request["id"]
    record = {"id": item_id, "prompt_sha256": sha(request["messages"][0]["content"]),
              "started_at_utc": utc_now()}
    start = time.monotonic()
    prediction, is_demo = None, False
    try:
        result = subprocess.run(command, input=json.dumps(request, ensure_ascii=False),
                                capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                shell=False)
        record.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr[-8000:])
        if result.returncode:
            raise ValueError(f"adapter exited with code {result.returncode}")
        response = json.loads(result.stdout)
        candidate = response.get("prediction") if isinstance(response, dict) and "prediction" in response else response
        validate_predictions([candidate], [item_id])
        prediction = candidate
        is_demo = isinstance(response, dict) and response.get("demo") is True
        if isinstance(response, dict) and "usage" in response:
            record["adapter_reported_usage"] = response["usage"]
        record["status"] = "valid"
    except (ValueError, subprocess.TimeoutExpired, OSError) as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
    record["elapsed_seconds"] = time.monotonic() - start
    return record, prediction, is_demo


def run_adapter(bundle_path, adapter, out, model, *, reasoning="unspecified", temperature=None,
                max_output_tokens=None, timeout=180, resume=False, limit=None, jobs=1, progress=False):
    if timeout <= 0 or (limit is not None and limit <= 0):
        raise ValueError("Timeout and optional limit must be positive")
    if type(jobs) is not int or jobs < 1:
        raise ValueError("jobs must be a positive integer")
    if max_output_tokens is not None and max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive when supplied")
    bundle = load_bundle(bundle_path)
    adapter = Path(adapter).resolve()
    if not adapter.is_file():
        raise ValueError("Adapter must be a Python file or an executable file")
    config = run_config(bundle, model, reasoning, temperature, max_output_tokens, PRIMARY_PROTOCOL)
    config["adapter_sha256"] = sha(adapter.read_text(encoding="utf-8")) if adapter.suffix == ".py" else __import__("hashlib").sha256(adapter.read_bytes()).hexdigest()
    out = Path(out)
    rows = []
    if out.exists() and any(out.iterdir()):
        if not resume:
            raise ValueError("Run directory is not empty; use --resume with the same configuration")
        previous = json.loads((out / "run.json").read_text(encoding="utf-8"))
        for key in ("dataset_id", "bundle_fingerprint", "protocol_id", "model", "generation", "adapter_sha256", "prompt_set_sha256"):
            if previous.get(key) != config[key]:
                raise ValueError(f"Resume configuration differs: {key}")
        config = previous
        rows = read_jsonl(out / "predictions.jsonl")
        validate_predictions(rows, bundle["ids"], require_complete=False)
        if config.get("predictions_sha256") and sha((out / "predictions.jsonl").read_text(encoding="utf-8")) != config["predictions_sha256"]:
            raise ValueError("Run predictions were modified after checkpointing")
    else:
        out.mkdir(parents=True, exist_ok=True)
        config.update(started_at_utc=utc_now(), execution="adapter_process_per_item", attempts=0)
        write_jsonl(out / "predictions.jsonl", [])
    predictions = {r["id"]: r for r in rows}
    responses = out / "responses"
    responses.mkdir(exist_ok=True)
    failures = {}
    pending_items = [item for item in bundle["items"] if item["id"] not in predictions]
    if limit is not None:
        pending_items = pending_items[:limit]
    pending_items = iter(pending_items)
    active = {}
    interrupted = False
    config.update(status="running", last_jobs=jobs, last_runner_version=__version__)
    write_json(out / "run.json", config)
    command = [sys.executable, str(adapter)] if adapter.suffix == ".py" else [str(adapter)]

    def launch_one(pool):
        item = next(pending_items, None)
        if item is None:
            return False
        item_id = item["id"]
        prompt = item_prompt(bundle, item)
        request = {"id": item_id, "protocol_id": PRIMARY_PROTOCOL,
                   "messages": [{"role": "user", "content": prompt}],
                   "response_schema": bundle["schema"], "model": model,
                   "generation": config["generation"]}
        number = len(list(responses.glob(f"{item_id}.attempt-*.json"))) + 1
        active[pool.submit(call_adapter, command, request, timeout)] = (item_id, number)
        config["attempts"] += 1
        write_json(out / "run.json", config)
        return True

    def collect(future):
        item_id, number = active[future]
        record, prediction, is_demo = future.result()
        if prediction is not None:
            predictions[item_id] = prediction
            config["is_demo"] = config.get("is_demo", False) or is_demo
        else:
            failures[item_id] = record["error"]
        write_json(responses / f"{item_id}.attempt-{number}.json", record)
        write_jsonl(out / "predictions.jsonl", [predictions[i] for i in bundle["ids"] if i in predictions])
        config.update(valid_predictions=len(predictions), status="running",
                      predictions_sha256=sha((out / "predictions.jsonl").read_text(encoding="utf-8")))
        write_json(out / "run.json", config)
        del active[future]
        if progress:
            print(f"[{len(predictions)}/{len(bundle['ids'])}] {item_id}: {record['status']}",
                  file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        try:
            for _ in range(jobs):
                if not launch_one(pool):
                    break
            while active:
                completed, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in completed:
                    collect(future)
                while len(active) < jobs and launch_one(pool):
                    pass
        except KeyboardInterrupt:
            # Stop dispatching, then checkpoint in-flight work before returning.
            interrupted = True
            if progress:
                print("Stopping dispatch; saving in-flight results before exit…", file=sys.stderr, flush=True)
            for future in as_completed(list(active)):
                collect(future)
    config.update(status="complete" if len(predictions) == len(bundle["ids"]) else "incomplete",
                  valid_predictions=len(predictions), last_finished_at_utc=utc_now(),
                  predictions_sha256=sha((out / "predictions.jsonl").read_text(encoding="utf-8")),
                  last_call_failures=failures, last_call_interrupted=interrupted)
    write_json(out / "run.json", config)
    return {"status": config["status"], "valid_predictions": len(predictions),
            "expected_items": len(bundle["ids"]), "is_demo": config.get("is_demo", False),
            "failed_ids": list(failures), "run_directory": str(out), "jobs": jobs, "interrupted": interrupted}


def import_predictions(bundle_path, predictions_path, out, model, *, reasoning="unspecified",
                       protocol=EXTERNAL_PROTOCOL):
    bundle = load_bundle(bundle_path)
    if protocol not in {EXTERNAL_PROTOCOL, "legacy-agent-3x29"}:
        raise ValueError("Imported runs use external-agent-v1 or legacy-agent-3x29; use run for the primary protocol")
    rows = read_jsonl(predictions_path)
    predictions = validate_predictions(rows, bundle["ids"])
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Import destination must be empty")
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "predictions.jsonl", [predictions[i] for i in bundle["ids"]])
    config = run_config(bundle, model, reasoning, None, None, protocol)
    config.update(status="complete", execution="external_import_self_reported", valid_predictions=len(rows),
                  imported_at_utc=utc_now(), predictions_sha256=sha((out / "predictions.jsonl").read_text(encoding="utf-8")))
    write_json(out / "run.json", config)
    return {"imported": len(rows), "protocol_id": protocol, "run_directory": str(out)}

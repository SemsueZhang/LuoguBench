from __future__ import annotations

from collections import Counter
from pathlib import Path
import csv
import json

from .core import LEVELS, read_jsonl, sha, validate_label, write_json
from .metrics import bootstrap_spearman, summarize


def score(labels_path, predictions_path, out, allow_partial=False, bootstrap=2000):
    labels, predictions = read_jsonl(labels_path), read_jsonl(predictions_path)
    if not labels:
        raise ValueError("Label set cannot be empty")
    for row in labels:
        validate_label(row)
    if any(not isinstance(p, dict) or not isinstance(p.get("id"), str) for p in predictions):
        raise ValueError("Each prediction must be an object with a string ID")
    for name, rows in [("labels", labels), ("predictions", predictions)]:
        ids = [r.get("id") for r in rows]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate IDs in {name}")
    truth = {r["id"]: r for r in labels}
    unknown = [r.get("id") for r in predictions if r.get("id") not in truth]
    if unknown:
        raise ValueError(f"Unknown prediction IDs: {unknown}")
    valid, invalid = {}, []
    for p in predictions:
        errors = []
        if type(p.get("level")) is not int or p["level"] not in LEVELS:
            errors.append("level must be an integer in 1..8")
        elif p.get("label") != LEVELS[p["level"]]:
            errors.append("label must match the exact level name")
        if not isinstance(p.get("reason"), str) or not p["reason"].strip():
            errors.append("nonempty reason required")
        if errors:
            invalid.append({"id": p["id"], "errors": errors})
        else:
            valid[p["id"]] = p
    missing = sorted(set(truth) - set(valid))
    if missing and not allow_partial:
        raise ValueError(f"Incomplete/invalid run: {len(missing)} missing valid predictions, invalid={invalid}. Use --allow-partial explicitly to score a subset.")
    rows = []
    for item_id, t in truth.items():
        if item_id in valid:
            p = valid[item_id]
            rows.append({"id": item_id, "problem_id": t["problem_id"], "bucket": t["bucket"],
                         "actual_level": t["level"], "actual_label": t["label"], "predicted_level": p["level"],
                         "predicted_label": p["label"], "signed_error": p["level"] - t["level"], "reason": p["reason"]})
    actual, predicted = [r["actual_level"] for r in rows], [r["predicted_level"] for r in rows]
    metrics = summarize(actual, predicted)
    metrics.update({"total_expected": len(labels), "coverage": len(valid) / len(labels), "invalid": invalid,
                    "missing": missing, "primary_metric": "accuracy",
                    "primary_metrics": ["accuracy", "within_one_level", "spearman_rho"],
                    "metric_targets": {"accuracy": "maximize", "within_one_level": 1.0, "spearman_rho": 1.0},
                    "reason_quality_scored": False,
                    "prediction_file_sha256": sha(Path(predictions_path).read_text()),
                    "label_file_sha256": sha(Path(labels_path).read_text())})
    if bootstrap:
        metrics["spearman_bootstrap"] = bootstrap_spearman(actual, predicted, bootstrap)
    # Descriptive prior-only comparisons; these use the evaluated labels, not training.
    majority = Counter(actual).most_common(1)[0][0]
    median = sorted(actual)[(len(actual) - 1) // 2]
    metrics["descriptive_constant_references"] = {
        "majority_level": majority, "majority_accuracy": actual.count(majority) / len(actual),
        "median_level": median, "median_mae": sum(abs(a - median) for a in actual) / len(actual),
        "constant_spearman": None,
    }
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "metrics.json", metrics)
    with (out / "per_problem.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (out / "confusion.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["actual/predicted"] + list(LEVELS.values()))
        for label, values in zip(LEVELS.values(), metrics["confusion_matrix"]):
            writer.writerow([label] + values)
    lines = ["LuoguBench: rating agreement", "", f"Coverage: {len(rows)}/{len(labels)}", ""]
    for key in ["accuracy", "within_one_level", "spearman_rho", "mae", "kendall_tau_b", "pearson_r", "quadratic_weighted_kappa", "mean_signed_error", "macro_recall"]:
        value = metrics[key]
        lines.append(f"{key}: {value:.6f}" if value is not None else f"{key}: undefined (zero variance)")
    lines.extend(["", "Per-level: actual level / n / accuracy / MAE / signed error"])
    for level, values in metrics["by_level"].items():
        lines.append(f"{level} {LEVELS[int(level)]}: {values['n']} / {values['accuracy']:.3f} / {values['mae']:.3f} / {values['mean_signed_error']:+.3f}")
    lines.extend(["", "Largest absolute errors (ties ordered by problem ID):"])
    for row in sorted(rows, key=lambda r: (-abs(r["signed_error"]), r["problem_id"]))[:10]:
        lines.append(f"{row['problem_id']}: {row['actual_level']} -> {row['predicted_level']}; {row['reason']}")
    lines.extend(["", "Reasons are retained for inspection, not automatically graded.",
                  "Public, purposively selected reference problems; correlation does not establish independent difficulty reasoning or generalization.",
                  "See run.json for the actual model, agent protocol and context isolation limits."])
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    return metrics

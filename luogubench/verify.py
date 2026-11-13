from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import math
import re
import shutil
import subprocess
import tempfile

from .core import code_blocks, read_jsonl, samples, sha, validate_input_item, write_json


def compare_output(actual, expected, settings):
    a, e = actual.split(), expected.split()
    if len(a) != len(e):
        return False
    if settings.get("sample_check") != "numeric_tokens":
        return a == e
    try:
        for got, want in zip(a, e):
            got, want = float(got), float(want)
            tolerance = max(settings.get("abs_tolerance", 0), settings.get("rel_tolerance", 0) * abs(want))
            if not math.isfinite(got) or not math.isfinite(want) or abs(got - want) > tolerance:
                return False
    except ValueError:
        return False
    return True


def verify(root, data, out, compiler=None, jobs=4):
    compiler = compiler or shutil.which("g++-16") or shutil.which("g++-15") or shutil.which("g++")
    if not compiler:
        raise ValueError("No C++ compiler found; pass --compiler")
    overrides_path = root / "curation/verification_overrides.json"
    overrides = json.loads(overrides_path.read_text()) if overrides_path.exists() else {}
    input_rows = read_jsonl(data / "inputs.jsonl")
    for item in input_rows:
        validate_input_item(item)
    items = {r["id"]: r for r in input_rows}
    provenance = read_jsonl(data / "provenance.jsonl")
    if len(items) != len(input_rows) or len({p["id"] for p in provenance}) != len(provenance) or set(items) != {p["id"] for p in provenance}:
        raise ValueError("Verification requires unique, aligned input/provenance IDs")
    tasks = []
    for p in provenance:
        statement = (root / p["source_dir"] / "statement.md").read_text()
        solutions = items[p["id"]]["solutions"]
        if len(p["selections"]) != len(solutions):
            raise ValueError(f"Verification method count mismatch: {p['id']}")
        for s, material in zip(p["selections"], solutions):
            source = data / s["std_path"]
            if s["method_id"] != material["method_id"] or sha(source.read_text()) != s["input_code_sha256"] or sha(material["std"]["code"]) != s["input_code_sha256"]:
                raise ValueError(f"Verification source/method hash mismatch: {p['id']}/{s['method_id']}")
            tasks.append((p, s, material, statement))
    def run(task):
        p, s, material, statement = task
        result = {"id": p["id"], "problem_id": p["problem_id"], "method_id": s["method_id"],
                  "std_sha256": s["input_code_sha256"], "patches": s.get("std_patches", [])}
        with tempfile.TemporaryDirectory(prefix="luogubench-std-") as scratch:
            scratch = Path(scratch)
            source = data / s["std_path"]
            binary = scratch / "program"
            command = [compiler, "-std=c++17", "-O2", "-DONLINE_JUDGE", str(source), "-o", str(binary)]
            if material["std"]["interface"] == "library":
                # Verify a compilation unit against the actual declarations in the supplied statement.
                special = overrides.get(p["problem_id"], {})
                header_name = special["header_file"]
                header = code_blocks(statement)[special["header_block_index"]][1]
                (scratch / header_name).write_text(header)
                command = [compiler, "-std=c++17", "-O2", "-DONLINE_JUDGE", "-I", str(scratch), "-c", str(source), "-o", str(scratch / "program.o")]
                result["library_header"] = {"name": header_name, "source": "supplied_statement_fenced_block", "sha256": sha(header)}
            try:
                compilation = subprocess.run(command, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                result["status"] = "compile_timeout"
                return result
            result["compile_command"] = [compiler, "-std=c++17", "-O2", "-DONLINE_JUDGE"]
            if compilation.returncode:
                result.update(status="compile_failed", diagnostic=compilation.stderr[-12000:])
                return result
            result["compiler_warnings"] = compilation.stderr[-4000:]
            if material["std"]["interface"] == "library":
                result.update(status="library_object_compiled", samples_skipped="requires original grader and interaction")
                return result
            special = overrides.get(p["problem_id"], {})
            if "交互" in statement or special.get("sample_check") == "skip":
                result.update(status="compiled_samples_skipped", samples_skipped=special.get("reason", "interactive task, no offline grader supplied"))
                return result
            checks = []
            for example in samples(statement):
                if not example["available"]:
                    checks.append({"status": "not_embedded", "reason": "statement references an attachment instead of supplying sample data"})
                    continue
                try:
                    run = subprocess.run([str(binary)], input=example["input"], capture_output=True, text=True, timeout=10, cwd=scratch)
                    match = run.returncode == 0 and compare_output(run.stdout, example["output"], special)
                    check = {"status": "pass" if match else "output_diff", "exit_code": run.returncode}
                    if not match:
                        check.update(expected=example["output"][:2000], actual=run.stdout[:2000], stderr=run.stderr[:2000])
                except subprocess.TimeoutExpired:
                    check = {"status": "timeout"}
                checks.append(check)
            result["samples"] = checks
            result["sample_comparison"] = special.get("sample_check", "whitespace_tokens_exact")
            available_checks = [c for c in checks if c["status"] != "not_embedded"]
            result["status"] = "samples_passed" if available_checks and all(c["status"] == "pass" for c in available_checks) else "sample_check_failed" if available_checks else "compiled_no_samples"
            return result
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(run, tasks))
    from collections import Counter
    compiler_version = subprocess.run([compiler, "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    report = {"compiler": compiler, "compiler_version": compiler_version,
              "input_file_sha256": sha((data / "inputs.jsonl").read_text()),
              "checks": len(results), "status_counts": dict(Counter(r["status"] for r in results)),
              "scope": "Compilation and supplied samples only, not original judge acceptance or a proof of correctness.", "programs": results}
    write_json(out, report)
    return {k: v for k, v in report.items() if k != "programs"}

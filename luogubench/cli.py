from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

from .build import build
from .core import LEVELS, read_jsonl, sha, validate_input_item, validate_label, write_json
from .prompt import OUTPUT_SCHEMA, RUBRIC
from .score import score
from .verify import verify
from .bundle import load_bundle
from .runner import import_predictions, run_adapter
from .submission import create_submission, grade_submission


def export(inputs_path, out, shards):
    if shards < 1:
        raise ValueError("shards must be positive")
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Export destination must be empty, to prevent stale/label files mixing with inputs")
    items = read_jsonl(inputs_path)
    for item in items:
        validate_input_item(item)
    ids = [r["id"] for r in items]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Export requires nonempty inputs with unique IDs")
    (out / "items").mkdir(parents=True, exist_ok=True)
    for item in items:
        (out / "items" / f"{item['id']}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
    images = []
    names = sorted(set(re.findall(r"!\[原文插图\]\(assets/([A-Za-z0-9_.-]+)\)", json.dumps(items, ensure_ascii=False))))
    for name in names:
        source = Path(inputs_path).parent / "assets" / name
        target = out / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        images.append({"filename": "assets/" + name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    for i in range(shards):
        (out / f"shard_{i+1}.txt").write_text("\n".join(f"items/{item['id']}.json" for item in items[i::shards]) + "\n")
    (out / "rubric.txt").write_text(RUBRIC + "\n")
    write_json(out / "output.schema.json", OUTPUT_SCHEMA)
    write_json(out / "manifest.json", {"n": len(items), "shards": shards,
                                       "input_file_sha256": sha(Path(inputs_path).read_text()),
                                       "rubric_sha256": sha(RUBRIC),
                                       "images": images,
                                       "files": [{"id": item["id"], "sha256": sha(json.dumps(item, ensure_ascii=False, sort_keys=True))} for item in items]})
    return {"export": str(out), "items": len(items), "shards": shards}


def validate(data):
    inputs, labels = read_jsonl(data / "inputs.jsonl"), read_jsonl(data / "labels.jsonl")
    if not inputs or not labels:
        raise ValueError("Dataset cannot be empty")
    for item in inputs:
        validate_input_item(item)
    for row in labels:
        validate_label(row)
    ids = [r["id"] for r in inputs]
    if len(ids) != len(set(ids)) or set(ids) != {r["id"] for r in labels} or len(inputs) != len(labels):
        raise ValueError("Input/label IDs are not unique and aligned")
    return {"valid": True, "items": len(inputs)}


def main():
    parser = argparse.ArgumentParser(description="Luogu difficulty benchmark MVP, stdlib only")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("release", help="create separate participant and private evaluator archives")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("check-bundle", help="validate a public bundle without labels")
    p.add_argument("bundle", type=Path)
    p = sub.add_parser("run", help="run a local adapter once per independent question")
    p.add_argument("--bundle", type=Path, default=Path("benchmark"))
    p.add_argument("--adapter", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--reasoning", default="unspecified")
    p.add_argument("--temperature", type=float)
    p.add_argument("--max-output-tokens", type=int)
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("import-run", help="import an externally collected agent prediction file")
    p.add_argument("predictions", type=Path)
    p.add_argument("--bundle", type=Path, default=Path("benchmark"))
    p.add_argument("--model", required=True)
    p.add_argument("--reasoning", default="unspecified")
    p.add_argument("--protocol", choices=["external-agent-v1", "legacy-agent-3x29"], default="external-agent-v1")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("submit", help="create a complete, label-free prediction submission ZIP")
    p.add_argument("--bundle", type=Path, default=Path("benchmark"))
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("grade", help="maintainer-only scoring of a submitted ZIP")
    p.add_argument("submission", type=Path)
    p.add_argument("--bundle", type=Path, default=Path("benchmark"))
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--allow-demo", action="store_true")
    p.add_argument("--bootstrap", type=int, default=2000)
    p = sub.add_parser("build", help="build from expert-curated source manifests")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--out", type=Path, default=Path("data"))
    p = sub.add_parser("validate")
    p.add_argument("--data", type=Path, default=Path("data"))
    p = sub.add_parser("export", help="export only blinded materials, with no labels/provenance")
    p.add_argument("--inputs", type=Path, default=Path("data/inputs.jsonl"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--shards", type=int, default=3)
    p = sub.add_parser("verify", help="compile stds and check supplied samples")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--out", type=Path, default=Path("data/std_verification.json"))
    p.add_argument("--compiler")
    p.add_argument("--jobs", type=int, default=4)
    p = sub.add_parser("score", help="strictly score a JSONL prediction file")
    p.add_argument("predictions", type=Path)
    p.add_argument("--labels", type=Path, default=Path("data/labels.jsonl"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--allow-partial", action="store_true")
    p.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()
    try:
        if args.command == "release":
            from .release import release
            result = release(args.root, args.out)
        elif args.command == "check-bundle":
            checked = load_bundle(args.bundle)
            result = {"valid": True, "items": len(checked["ids"]), "dataset_id": checked["manifest"]["dataset_id"],
                      "bundle_fingerprint": checked["fingerprint"]}
        elif args.command == "run":
            result = run_adapter(args.bundle, args.adapter, args.out, args.model, reasoning=args.reasoning,
                                 temperature=args.temperature, max_output_tokens=args.max_output_tokens,
                                 timeout=args.timeout, resume=args.resume, limit=args.limit)
        elif args.command == "import-run":
            result = import_predictions(args.bundle, args.predictions, args.out, args.model,
                                        reasoning=args.reasoning, protocol=args.protocol)
        elif args.command == "submit":
            result = create_submission(args.bundle, args.run, args.out)
        elif args.command == "grade":
            result = grade_submission(args.bundle, args.submission, args.labels, args.out,
                                      allow_demo=args.allow_demo, bootstrap=args.bootstrap)
        elif args.command == "build":
            result = build(args.root.resolve(), args.out.resolve())
        elif args.command == "validate":
            result = validate(args.data)
        elif args.command == "export":
            result = export(args.inputs, args.out, args.shards)
        elif args.command == "verify":
            result = verify(args.root.resolve(), args.data.resolve(), args.out.resolve(), args.compiler, args.jobs)
        else:
            result = score(args.labels, args.predictions, args.out, args.allow_partial, args.bootstrap)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "run" and result["status"] != "complete":
            parser.exit(1, "Run is incomplete; fix adapter failures and resume before submitting.\n")
    except (ValueError, KeyError, OSError, IndexError, zipfile.BadZipFile) as e:
        parser.exit(2, f"error: {e}\n")


if __name__ == "__main__":
    main()

"""Build separate public-participant and private-maintainer release archives."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import zipfile

from . import __version__
from .bundle import PRIMARY_PROTOCOL, PROTOCOL_NOTE, export_prompts, file_digest, load_bundle
from .core import sha, write_json

PUBLIC_MODULES = (
    "__init__.py", "__main__.py", "core.py", "metrics.py", "prompt.py", "bundle.py",
    "runner.py", "submission.py", "score.py", "cli.py", "release.py", "build.py", "verify.py", "rewrite.py",
)


def zip_directory(directory, destination):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store":
                archive.write(path, path.relative_to(directory).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("Release archive failed integrity validation")


def release(root, out):
    # Imported lazily to keep CLI export usable without circular imports.
    from .cli import export
    root, out = Path(root).resolve(), Path(out).resolve()
    if out == root or root.is_relative_to(out):
        raise ValueError("Release output must not be a parent of the source project")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Release output directory must be empty")
    spec = json.loads((root / "benchmark_spec.json").read_text(encoding="utf-8"))
    checks = [(root / "data/inputs.jsonl", "input_file_sha256"),
              (root / "data/labels.jsonl", "labels_sha256"),
              (root / "data/rubric.txt", "rubric_file_sha256")]
    for path, key in checks:
        if file_digest(path) != spec[key]:
            raise ValueError(f"Frozen release specification differs from {path.name}; create a new data version")
    if sha(PROTOCOL_NOTE + "\n") != spec["protocol_file_sha256"]:
        raise ValueError("Frozen protocol specification differs; create a new protocol version")
    participant = out / "participant"
    participant.mkdir(parents=True)
    material_root = participant / "benchmark"
    export(root / "data/inputs.jsonl", material_root, 3)
    manifest_path = material_root / "manifest.json"
    (material_root / "protocol.txt").write_text(PROTOCOL_NOTE + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["n"] != spec["problem_count"]:
        raise ValueError("Frozen item count differs")
    manifest.update(bundle_format_version=1, dataset_id=spec["dataset_id"],
                    dataset_version=spec["dataset_version"], labels_sha256=spec["labels_sha256"],
                    protocol_id=PRIMARY_PROTOCOL, rubric_file_sha256=file_digest(material_root / "rubric.txt"),
                    protocol_file_sha256=file_digest(material_root / "protocol.txt"),
                    schema_file_sha256=file_digest(material_root / "output.schema.json"))
    write_json(manifest_path, manifest)
    checked = load_bundle(material_root)
    # Explicit allowlist: never copy the research README, data/, results/, curation/ or source corpus.
    (participant / "luogubench").mkdir()
    for name in PUBLIC_MODULES:
        shutil.copy2(root / "luogubench" / name, participant / "luogubench" / name)
    (participant / "adapters").mkdir()
    for name in ("demo_constant.py", "example_adapter.py"):
        shutil.copy2(root / "adapters" / name, participant / "adapters" / name)
    shutil.copy2(root / "pyproject.toml", participant / "pyproject.toml")
    shutil.copy2(root / "LICENSE-CODE", participant / "LICENSE-CODE")
    for source, destination in [("docs/PARTICIPANT.md", "README.md"),
                                ("docs/DATASET_CARD.md", "DATASET_CARD.md"),
                                ("docs/DATA_NOTICE.md", "DATA_NOTICE.md")]:
        shutil.copy2(root / source, participant / destination)
    for name in ("AGENT_RUN.md", "PROMPT.md"):
        if (root / name).exists():
            shutil.copy2(root / name, participant / name)
    public_docs = participant / "docs"
    export_prompts(material_root, public_docs)
    (public_docs / "manifest.json").rename(public_docs / "prompt-manifest.json")
    if (root / "docs/CLI.md").exists():
        shutil.copy2(root / "docs/CLI.md", public_docs / "CLI.md")
    (participant / "answers-template.jsonl").write_text(
        "".join(json.dumps({"id": item_id, "level": None}) + "\n" for item_id in checked["ids"]), encoding="utf-8")
    write_json(participant / "historical_baseline.json", spec["legacy_baseline"])
    history = []
    if spec["legacy_baseline"]:
        history.append({**spec["legacy_baseline"], "id": "gpt-6-luna-original",
                        "display_name": "GPT-6 Luna medium", "source_type": "local_predictions",
                        "execution_summary": "旧数据 v0.1.0 · 3×29 共享上下文"})
    history.extend(spec.get("historical_contributions", []))
    write_json(participant / "historical_results.json", {"schema_version": 1, "results": history})
    (participant / ".gitignore").write_text("__pycache__/\n*.pyc\nruns/\n.env\n.env.*\n.dev.vars*\n.DS_Store\n*-submission.zip\n", encoding="utf-8")
    evaluator = out / "evaluator"
    shutil.copytree(participant, evaluator)
    (evaluator / "private").mkdir()
    shutil.copy2(root / "data/labels.jsonl", evaluator / "private/labels.jsonl")
    shutil.copy2(root / "benchmark_spec.json", evaluator / "private/benchmark_spec.json")
    shutil.copy2(root / "docs/MAINTAINER.md", evaluator / "MAINTAINER.md")
    public_zip = out / f"luogubench-participant-{__version__}.zip"
    private_zip = out / f"luogubench-evaluator-{__version__}.zip"
    zip_directory(participant, public_zip)
    zip_directory(evaluator, private_zip)
    with zipfile.ZipFile(public_zip) as archive:
        names = archive.namelist()
        if any(name.startswith(("private/", "data/", "results/", "curation/", "discuss1312513/"))
               or Path(name).name in {"labels.jsonl", "provenance.jsonl", "per_problem.csv", "catalog.csv"}
               for name in names):
            raise ValueError("Participant archive contains maintainer-only data")
    result = {"software_version": __version__, "dataset_id": spec["dataset_id"],
              "dataset_version": spec["dataset_version"], "items": manifest["n"],
              "bundle_fingerprint": checked["fingerprint"],
              "public_participant_archive": public_zip.name,
              "private_evaluator_archive": private_zip.name,
              "files": [{"name": p.name, "bytes": p.stat().st_size, "sha256": file_digest(p)}
                        for p in (public_zip, private_zip)],
              "release_location": "local artifacts only; no hosted upload performed",
              "public_problem_caveat": "label separation does not establish secrecy or absence of training contamination"}
    write_json(out / "release.json", result)
    return result

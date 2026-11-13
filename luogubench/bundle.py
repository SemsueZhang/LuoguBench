"""Validate public material bundles without ever loading a difficulty label."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .core import LEVELS, sha, validate_input_item
from .prompt import OUTPUT_SCHEMA

PRIMARY_PROTOCOL = "isolated-text-v1"
EXTERNAL_PROTOCOL = "external-agent-v1"
LEGACY_PROTOCOL = "legacy-agent-3x29"
PROTOCOL_NOTE = """本次执行协议为 isolated-text-v1：每道题使用独立的新会话，只包含固定评级标尺和该题材料。使用文本材料完成评定，不调用图片查看、联网、搜索或其他工具，也不使用其他题目的对话历史、带标签示例、额外技能或自行修改的评级标尺。插图引用保留为材料位置标记。所有题目使用相同模型与生成参数。输出本题的一个JSON对象。"""


def material_digest(item):
    return sha(json.dumps(item, ensure_ascii=False, sort_keys=True))


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bundle_fingerprint(manifest):
    return sha(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def validate_predictions(rows, expected_ids, *, require_complete=True):
    expected = set(expected_ids)
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "level", "label", "reason"}:
            raise ValueError("Prediction must contain exactly id, level, label, reason")
        item_id = row["id"]
        if not isinstance(item_id, str) or item_id not in expected or item_id in seen:
            raise ValueError(f"Unknown or duplicate prediction ID: {item_id}")
        if type(row["level"]) is not int or row["level"] not in LEVELS:
            raise ValueError(f"{item_id}: level must be integer 1..8")
        if row["label"] != LEVELS[row["level"]]:
            raise ValueError(f"{item_id}: label does not match level")
        if not isinstance(row["reason"], str) or not row["reason"].strip() or len(row["reason"]) > 8192:
            raise ValueError(f"{item_id}: nonempty reason of at most 8192 characters required")
        seen.add(item_id)
    if require_complete and seen != expected:
        raise ValueError(f"Incomplete submission: {len(seen)}/{len(expected)} valid IDs")
    return {row["id"]: row for row in rows}


def load_bundle(path):
    path = Path(path).resolve()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("bundle_format_version") != 1:
        raise ValueError("Expected a public release bundle with bundle_format_version=1")
    if manifest.get("protocol_id") != PRIMARY_PROTOCOL:
        raise ValueError("Unsupported primary protocol")
    rubric_path = path / "rubric.txt"
    schema_path = path / "output.schema.json"
    protocol_path = path / "protocol.txt"
    if file_digest(rubric_path) != manifest.get("rubric_file_sha256"):
        raise ValueError("Rubric hash mismatch")
    if file_digest(schema_path) != manifest.get("schema_file_sha256"):
        raise ValueError("Output schema hash mismatch")
    if file_digest(protocol_path) != manifest.get("protocol_file_sha256"):
        raise ValueError("Protocol text hash mismatch")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if schema != OUTPUT_SCHEMA:
        raise ValueError("Unsupported prediction schema")
    refs = manifest.get("files")
    if not isinstance(refs, list) or not refs or manifest.get("n") != len(refs):
        raise ValueError("Invalid bundle item count")
    ids = [row.get("id") for row in refs]
    if any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Unsafe/duplicate item identifiers in bundle")
    allowed = {"manifest.json", "rubric.txt", "protocol.txt", "output.schema.json"}
    allowed.update(f"shard_{i}.txt" for i in range(1, manifest.get("shards", 0) + 1))
    items = []
    referenced_images = set()
    for ref in refs:
        filename = f"items/{ref['id']}.json"
        allowed.add(filename)
        item = json.loads((path / filename).read_text(encoding="utf-8"))
        validate_input_item(item)
        if item["id"] != ref["id"] or material_digest(item) != ref["sha256"]:
            raise ValueError(f"Material hash/identity mismatch: {ref['id']}")
        referenced_images.update(re.findall(r"!\[原文插图\]\((assets/[A-Za-z0-9_.-]+)\)", json.dumps(item, ensure_ascii=False)))
        items.append(item)
    images = manifest.get("images", [])
    image_names = [r.get("filename") for r in images]
    if len(image_names) != len(set(image_names)) or set(image_names) != referenced_images:
        raise ValueError("Image inventory does not match materials")
    for ref in images:
        name = ref["filename"]
        if not isinstance(name, str) or not re.fullmatch(r"assets/[A-Za-z0-9_.-]+", name):
            raise ValueError("Unsafe image path")
        allowed.add(name)
        if file_digest(path / name) != ref["sha256"]:
            raise ValueError(f"Image hash mismatch: {name}")
    # Exact file inventory prevents accidentally packaging labels/provenance beside inputs.
    actual = set()
    for p in path.rglob("*"):
        if p.is_symlink():
            raise ValueError("Public bundle must not contain symlinks")
        if p.is_file():
            if p.name in {".DS_Store", "Thumbs.db"}:
                continue
            actual.add(p.relative_to(path).as_posix())
    if actual != allowed:
        raise ValueError(f"Unexpected/missing public bundle files: {sorted(actual ^ allowed)}")
    rubric = rubric_path.read_text(encoding="utf-8")
    return {"path": path, "manifest": manifest, "fingerprint": bundle_fingerprint(manifest),
            "items": items, "ids": ids, "rubric": rubric, "schema": schema,
            "protocol_note": protocol_path.read_text(encoding="utf-8")}


def item_prompt(bundle, item):
    return (bundle["rubric"].rstrip() + "\n\n" + bundle["protocol_note"].rstrip() +
            "\n\n<problem_material>\n" + json.dumps(item, ensure_ascii=False, indent=2) +
            "\n</problem_material>\n")


def prompt_digest(bundle):
    return sha(json.dumps([{ "id": item["id"], "sha256": sha(item_prompt(bundle, item))}
                           for item in bundle["items"]], ensure_ascii=False, sort_keys=True))

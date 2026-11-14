from __future__ import annotations

from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import re
import shutil

from .core import (BUCKET_LEVELS, LEVELS, LEAK_PATTERN, code_blocks, sanitize,
                   sha, strip_cpp_comments, write_json, write_jsonl)
from .prompt import OUTPUT_SCHEMA, RUBRIC, render_prompt
from .rewrite import apply_rewrite


def source_path(root, directory, name):
    return root / name[2:] if name.startswith("@/") else directory / name


def validate_manifest(manifest, directory):
    root = directory.parents[2]
    files = {p.name for p in directory.glob("*.md") if p.name != "statement.md"}
    files.update(manifest.get("supplemental_sources", []))
    assigned = [n for f in manifest["families"] for n in f["members"]]
    assigned += [r["source"] for r in manifest.get("rejected", [])]
    if Counter(assigned) != Counter(files):
        raise ValueError(f"{directory}: incomplete/duplicate source coverage: {Counter(files)-Counter(assigned)}, {Counter(assigned)-Counter(files)}")
    families = {f["id"]: f for f in manifest["families"]}
    if len(families) != len(manifest["families"]):
        raise ValueError(f"{directory}: duplicate family ID")
    selected = manifest["selected"]
    if len(selected) > 3 or len({s["family"] for s in selected}) != len(selected):
        raise ValueError(f"{directory}: selected methods must be distinct, at most 3")
    for s in selected:
        f = families[s["family"]]
        if s["editorial"] not in f["members"] or s["std_source"] not in f["members"]:
            raise ValueError(f"{directory}: explanation and std must belong to selected family")
        blocks = code_blocks(source_path(root, directory, s["std_source"]).read_text())
        if not 0 <= s["code_block_index"] < len(blocks):
            raise ValueError(f"{directory}: invalid code block index {s}")
        _, code = blocks[s["code_block_index"]]
        for patch in s.get("std_patches", []):
            if code.count(patch["old"]) != 1:
                raise ValueError(f"{directory}: std patch must match exactly once: {patch}")
            code = code.replace(patch["old"], patch["new"], 1)
        if not re.search(r"\bmain\s*\(", code) and s.get("std_interface") != "library":
            raise ValueError(f"{directory}: selected code lacks main: {s}")


def editorial_without_programs(text):
    """Keep explanation snippets; avoid repeating complete programs in editorial."""
    lines = text.splitlines(keepends=True)
    out, block, fence = [], [], None
    for line in lines:
        m = re.match(r"^[ \t]*(`{3,}|~{3,})([^\n]*)", line)
        if fence is None:
            if m:
                fence = (m[1][0], len(m[1]))
                block = [line]
            else:
                out.append(line)
        else:
            block.append(line)
            if m and m[1][0] == fence[0] and len(m[1]) >= fence[1] and not m[2].strip():
                body = "".join(block)
                out.append("[完整参考程序见配套 std]\n" if re.search(r"\bmain\s*\(|#include.*count\.h", body) else body)
                fence = None
    if fence:
        body = "".join(block)
        out.append("[完整参考程序见配套 std]\n" if re.search(r"\bmain\s*\(", body) else body)
    return "".join(out)


def build(root: Path, out: Path):
    raw = root / "discuss1312513"
    manifests = root / "curation/problems"
    asset_manifest_path = root / "assets/manifest.json"
    asset_manifest = json.loads(asset_manifest_path.read_text()) if asset_manifest_path.exists() else []
    asset_map = {r["url"]: r for r in asset_manifest if r["status"] == "downloaded"}
    used_assets = set()
    def resolve_image(url):
        row = asset_map.get(url)
        if row is None:
            return None
        filename = row.get("display_filename", row["filename"])
        digest = row.get("display_sha256", row["sha256"])
        source = root / "assets" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Image hash mismatch: {source}")
        target = out / "assets" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        used_assets.add(filename)
        return "assets/" + filename
    inputs, labels, provenance, excluded, audit, catalog = [], [], [], [], [], []
    rewrite_audit = []
    total_articles = 0
    source_index = []
    current_code_paths = set()
    for statement_path in sorted(raw.glob("*/*/statement.md")):
        directory = statement_path.parent
        bucket, pid = directory.parent.name, directory.name
        mpath = manifests / f"{pid}.json"
        if not mpath.exists():
            raise ValueError(f"Missing curation manifest: {mpath}")
        m = json.loads(mpath.read_text())
        if m["bucket"] != bucket or m["problem_id"] != pid:
            raise ValueError(f"Manifest identity mismatch: {mpath}")
        validate_manifest(m, directory)
        article_count = len(list(directory.glob("*.md"))) - 1
        total_articles += article_count
        for source in sorted(directory.glob("*.md")):
            source_index.append({"path": str(source.relative_to(root)), "sha256": sha(source.read_text())})
        for source in m.get("supplemental_sources", []):
            path = source_path(root, directory, source)
            source_index.append({"path": str(path.relative_to(root)), "sha256": sha(path.read_text()), "supplemental": True})
        if not m["selected"]:
            excluded.append({"problem_id": pid, "bucket": bucket, "reason": m.get("notes", "missing usable editorial/std")})
            continue
        anonymous_id = "B" + sha("luogubench-mvp-v1/" + pid)[:12]
        statement, edits = sanitize(statement_path.read_text(), statement=True, image_resolver=resolve_image)
        audit.append({"id": anonymous_id, "kind": "statement", "edits": edits})
        solutions, refs = [], []
        for i, s in enumerate(m["selected"], 1):
            original_editorial = source_path(root, directory, s["editorial"]).read_text()
            for patch in s.get("editorial_patches", []):
                if original_editorial.count(patch["old"]) != 1:
                    raise ValueError(f"{pid}: editorial patch must match exactly once: {patch}")
                original_editorial = original_editorial.replace(patch["old"], patch["new"], 1)
            explanation, edits = sanitize(editorial_without_programs(original_editorial), image_resolver=resolve_image)
            audit.append({"id": anonymous_id, "kind": f"editorial_{i}", "edits": edits})
            code = code_blocks(source_path(root, directory, s["std_source"]).read_text())[s["code_block_index"]][1]
            original_code_sha = sha(code)
            for patch in s.get("std_patches", []):
                if code.count(patch["old"]) != 1:
                    raise ValueError(f"{pid}: std patch must match exactly once: {patch}")
                code = code.replace(patch["old"], patch["new"], 1)
            code = strip_cpp_comments(code)
            if LEAK_PATTERN.search(code):
                raise ValueError(f"{pid}: identity/rating leak remains in std")
            std = {"language": "cpp17", "interface": s.get("std_interface", "stdin_stdout"), "code": code}
            solutions.append({"method_id": f"method_{i}", "editorial_md": explanation, "std": std})
            code_path = out / "std" / anonymous_id / f"method_{i}.cpp"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text(code)
            current_code_paths.add(code_path.resolve())
            refs.append({**s, "method_id": f"method_{i}", "original_code_sha256": original_code_sha,
                         "input_code_sha256": sha(code), "std_path": str(code_path.relative_to(out))})
        item = {"id": anonymous_id, "statement_md": statement, "solutions": solutions}
        rewrite_audit.extend(apply_rewrite(root, item))
        if any(LEAK_PATTERN.search(s["editorial_md"]) for s in solutions) or LEAK_PATTERN.search(statement):
            raise ValueError(f"{pid}: leakage scanner still finds explicit identifiers/ratings")
        inputs.append(item)
        level = BUCKET_LEVELS[bucket]
        labels.append({"id": anonymous_id, "problem_id": pid, "level": level, "label": LEVELS[level],
                       "bucket": bucket, "label_source": "supplied_directory_annotation", "taxonomy": "luogu_2026_8_levels"})
        provenance.append({"id": anonymous_id, "problem_id": pid, "source_dir": str(directory.relative_to(root)),
                           "manifest": str(mpath.relative_to(root)), "selections": refs, "input_sha256": sha(json.dumps(item, ensure_ascii=False, sort_keys=True))})
        catalog.append({"id": anonymous_id, "problem_id": pid, "bucket": bucket, "level": level,
                        "label": LEVELS[level], "source_articles": article_count, "families": len(m["families"]),
                        "selected": len(solutions), "rejected": len(m.get("rejected", []))})
    # Stable shuffled order, independent of level and raw directory traversal.
    inputs.sort(key=lambda x: sha("order-v1/" + x["id"]))
    final_asset_names = set(re.findall(r'!\[原文插图\]\(assets/([A-Za-z0-9_.-]+)\)', json.dumps(inputs, ensure_ascii=False)))
    for path in (out / "assets").glob("*"):
        if path.is_file() and path.name not in final_asset_names:
            path.unlink()
    for filename, rows in [("inputs.jsonl", inputs), ("labels.jsonl", labels), ("provenance.jsonl", provenance),
                           ("excluded.jsonl", excluded), ("sanitization_audit.jsonl", audit), ("source_index.jsonl", source_index),
                           ("rewrite_audit.jsonl", rewrite_audit)]:
        write_jsonl(out / filename, rows)
    prompt_dir = out / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    for item in inputs:
        (prompt_dir / f"{item['id']}.md").write_text(render_prompt(item))
    # These directories contain generated artifacts only. Retire stale selections.
    for path in (out / "std").rglob("*.cpp"):
        if path.resolve() not in current_code_paths:
            path.unlink()
    current_prompt_names = {f"{i['id']}.md" for i in inputs}
    for path in prompt_dir.glob("*.md"):
        if path.name not in current_prompt_names:
            path.unlink()
    (out / "rubric.txt").write_text(RUBRIC + "\n")
    write_json(out / "asset_provenance.json", asset_manifest)
    write_json(out / "output.schema.json", OUTPUT_SCHEMA)
    with (out / "catalog.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(catalog[0]))
        writer.writeheader()
        writer.writerows(catalog)
    stats = {"dataset_version": "0.2.0", "source_problems": len(list(raw.glob("*/*/statement.md"))),
             "eligible_problems": len(inputs), "excluded_problems": len(excluded), "source_articles": total_articles,
             "families": sum(c["families"] for c in catalog), "selected_methods": sum(c["selected"] for c in catalog),
             "rejected_articles": sum(c["rejected"] for c in catalog),
             "label_distribution": dict(sorted(Counter(r["level"] for r in labels).items())),
             "selected_count_distribution": dict(sorted(Counter(c["selected"] for c in catalog).items())),
             "input_characters": sum(len(render_prompt(i)) for i in inputs),
             "image_reference_count": sum(json.dumps(i, ensure_ascii=False).count("![原文插图]") for i in inputs),
             "missing_image_count": sum(json.dumps(i, ensure_ascii=False).count("原文插图，未能获取") for i in inputs),
             "cached_images_used": len(final_asset_names),
             "source_images_resolved_before_rewrite": len(used_assets),
             "taxonomy_source": "https://www.luogu.com.cn/discuss/1312513",
             "taxonomy_checked_date": "2026-11-13", "judged_accepted_std_claim": False}
    write_json(out / "statistics.json", stats)
    if len(list((root / "curation/rewrites").glob("*.json"))) != len(inputs):
        raise ValueError("Rewrite inventory does not match the complete dataset")
    return stats

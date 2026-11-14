"""Apply reviewed prose revisions, bound to exact source hashes."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .core import LEAK_PATTERN, sha


def apply_rewrite(root, item):
    path = Path(root) / "curation/rewrites" / (item["id"] + ".json")
    revision = json.loads(path.read_text(encoding="utf-8"))
    if revision["id"] != item["id"] or revision["source_statement_sha256"] != sha(item["statement_md"]):
        raise ValueError(f"Rewrite source statement changed: {item['id']}")
    if len(revision["solutions"]) != len(item["solutions"]):
        raise ValueError(f"Rewrite solution inventory changed: {item['id']}")
    original_statement = item["statement_md"]
    rewritten = revision["statement_md"]
    annex = original_statement.split("## 输入格式", 1)[1]
    expected_annex = annex
    for patch in revision.get("annex_patches", []):
        if expected_annex.count(patch["old"]) != 1:
            raise ValueError(f"Annex patch source changed: {item['id']}")
        expected_annex = expected_annex.replace(patch["old"], patch["new"], 1)
    if rewritten.split("## 输入格式", 1)[1] != expected_annex:
        raise ValueError(f"Technical annex changed without review: {item['id']}")
    if rewritten == original_statement or LEAK_PATTERN.search(rewritten):
        raise ValueError(f"Unchanged/leaking statement rewrite: {item['id']}")
    item["statement_md"] = rewritten
    audit = [{"id": item["id"], "kind": "statement", "before_sha256": sha(original_statement),
              "after_sha256": sha(rewritten), "technical_annex_byte_identical": not revision.get("annex_patches"),
              "annex_patches": revision.get("annex_patches", [])}]
    for old, new in zip(item["solutions"], revision["solutions"]):
        if old["method_id"] != new["method_id"] or sha(old["editorial_md"]) != new["source_editorial_sha256"]:
            raise ValueError(f"Rewrite source editorial changed: {item['id']} {old['method_id']}")
        if not new["editorial_md"].strip() or old["editorial_md"] == new["editorial_md"] or LEAK_PATTERN.search(new["editorial_md"]):
            raise ValueError(f"Empty/unchanged/leaking editorial rewrite: {item['id']}")
        audit.append({"id": item["id"], "kind": old["method_id"],
                      "before_sha256": sha(old["editorial_md"]), "after_sha256": sha(new["editorial_md"]),
                      "std_sha256": sha(old["std"]["code"])})
        old["editorial_md"] = new["editorial_md"]
    return audit

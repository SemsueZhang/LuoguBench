from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

LEVELS = {
    1: "入门", 2: "普及-", 3: "普及", 4: "普及+/提高-",
    5: "提高", 6: "提高+/省选-", 7: "省选/NOI-", 8: "NOI/NOI+/CTS",
}
# Eight-level 2026 taxonomy, verified against the originating official discussion.
BUCKET_LEVELS = {
    "red": 1, "orange": 2, "yellow": 3, "green": 4,
    "cyan": 5, "blue": 6, "purple": 7, "black_easy": 8, "black_hard": 8,
}


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{i}: {e}") from e
    return rows


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_input_item(item):
    if not isinstance(item, dict) or set(item) != {"id", "statement_md", "solutions"}:
        raise ValueError("Only label-free benchmark inputs with exact allowed fields may be used")
    if not isinstance(item["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", item["id"]):
        raise ValueError("Input ID must be a nonempty safe filename identifier")
    if not isinstance(item["statement_md"], str) or not item["statement_md"].strip():
        raise ValueError("Missing statement")
    if not isinstance(item["solutions"], list) or not 1 <= len(item["solutions"]) <= 3:
        raise ValueError("Each item must contain 1..3 solutions")
    seen = set()
    for solution in item["solutions"]:
        if not isinstance(solution, dict) or set(solution) != {"method_id", "editorial_md", "std"}:
            raise ValueError("Unexpected solution fields in label-free input")
        method_id = solution["method_id"]
        if not isinstance(method_id, str) or not re.fullmatch(r"method_[1-3]", method_id) or method_id in seen:
            raise ValueError("Invalid/duplicate method_id")
        seen.add(method_id)
        if not isinstance(solution["editorial_md"], str) or not solution["editorial_md"].strip():
            raise ValueError("Missing editorial")
        std = solution["std"]
        if not isinstance(std, dict) or set(std) != {"language", "interface", "code"}:
            raise ValueError("Unexpected std fields in label-free input")
        if std["language"] != "cpp17" or std["interface"] not in ("stdin_stdout", "library"):
            raise ValueError("Invalid std language/interface")
        if not isinstance(std["code"], str) or not std["code"].strip():
            raise ValueError("Missing std")


def validate_label(row):
    if not isinstance(row, dict) or not {"id", "problem_id", "bucket", "level", "label"} <= set(row):
        raise ValueError("Invalid label schema")
    if not isinstance(row["id"], str) or not row["id"]:
        raise ValueError("Invalid label ID")
    if type(row["level"]) is not int or row["level"] not in LEVELS or row["label"] != LEVELS[row["level"]]:
        raise ValueError("Invalid label: exact integer level and matching name required")


def code_blocks(text):
    """Fenced blocks in appearance order, including a final unclosed fence."""
    blocks = []
    active = None
    lines = []
    for line in text.splitlines(keepends=True):
        fence = re.match(r"^[ \t]*(`{3,}|~{3,})([^\n]*)\n?$", line)
        if active is None:
            if fence:
                active = (fence[1][0], len(fence[1]), fence[2].strip())
                lines = []
        elif fence and fence[1][0] == active[0] and len(fence[1]) >= active[1] and not fence[2].strip():
            blocks.append((active[2], "".join(lines)))
            active = None
        else:
            lines.append(line)
    if active:
        blocks.append((active[2], "".join(lines)))
    return blocks


def strip_cpp_comments(code):
    """Remove source identity in comments without changing string/char literals."""
    pattern = re.compile(
        r'R"([^\s()\\]{0,16})\(.*?\)\1"|"(?:\\.|[^"\\])*"|'
        r"'(?:\\.|[^'\\])*'|//[^\n]*|/\*.*?\*/", re.S,
    )
    def replace(m):
        s = m[0]
        if s.startswith("//") or s.startswith("/*"):
            return " " + "\n" * s.count("\n")
        return s
    return pattern.sub(replace, code).strip() + "\n"


LEAK_PATTERN = re.compile(
    r"(?i)\bP\d{3,}\b|[红橙黄绿青蓝紫黑](?:色)?题|"
    r"(?:入门|普及|提高|省选)\s*[/+−-]|(?:NOI/NOI)|"
    r"(?:洛谷|本题|这题|该题).{0,12}(?:难度|评级|定级)|"
    r"(?:难度|评级|定级).{0,12}(?:红|橙|黄|绿|青|蓝|紫|黑|洛谷)"
)


def sanitize(text, *, statement=False, image_resolver=None):
    """Deterministic metadata redaction; original text is preserved separately."""
    changes = []
    def sub(pattern, replacement, flags=0):
        nonlocal text
        text, n = re.subn(pattern, replacement, text, flags=flags)
        if n:
            changes.append({"pattern": pattern, "count": n})
    # Drop the first top-level title (typically the exact contest and problem name).
    sub(r"\A\s*# [^\n]*\n", "")
    # URLs can contain problem IDs, source identity and color labels.
    def image_reference(match):
        url = match[1].strip()
        path = image_resolver(url) if image_resolver else None
        return f"![原文插图]({path})" if path else "[原文插图，未能获取]"
    sub(r"!\[[^\]]*\]\(([^\n)]*)\)", image_reference)
    sub(r"\[([^\]\n]*)\]\((?:https?://)[^\n)]*\)", r"\1")
    sub(r"<?https?://[^\s<>)）。，！？]+>?", "[外部链接已隐藏]")
    sub(r"(?i)\bP\d{3,}\b", "[题号已隐藏]")
    sub(r"\[(?:NOIP|NOI|CSP|GESP|IOI|APIO|WC|省选)[^\]\n]*\]", "", re.I)
    # Source annotations and explicit author ratings are not task data. Remove only
    # the offending sentence, preserving later mathematics on the same line.
    kept = []
    for line in text.splitlines():
        if re.search(r"^(?:#+\s*)?(?:来源[:： ]*)?(?:NOIP|CSP[- ]?[JS]|GESP)\s*\d{4}", line, re.I):
            changes.append({"removed_metadata_line": line})
        else:
            fragments = re.split(r"(?<=[，；。！？])", line)
            clean_fragments = []
            for fragment in fragments:
                subjective = not statement and re.search(
                    r"难度|(?:省选|普及).{0,8}(?:最简单|不可能考)|"
                    r"(?:本题|这题|这道题|一道).{0,12}(?:很难|简单|不难|好题)|"
                    r"(?:题目来源|祝大家.*(?:rp|RP))", fragment)
                technical = re.search(r"\$|\\\(|DP|递推|前缀和|后缀|线段树|复杂度|二分|分治|方程|转移|等于|贪心|树状数组", fragment, re.I)
                if (LEAK_PATTERN.search(fragment) or subjective) and not technical:
                    changes.append({"removed_rating_clause": fragment})
                else:
                    masked = LEAK_PATTERN.sub("[等级描述已隐藏]", fragment)
                    if masked != fragment:
                        changes.append({"masked_rating_clause": fragment})
                    clean_fragments.append(masked)
            kept.append("".join(clean_fragments))
    text = "\n".join(kept)
    sub(r"(?<![A-Za-z])(?:NOIP|CSP(?:-[JS])?|GESP|IOI|NOI)\s*(?:20\d{2})?(?:\s*(?:D[12])?T[1-9])?(?![A-Za-z0-9])", "[竞赛来源已隐藏]", re.I)
    # Mask remaining direct level names/source divisions without deleting task sentences.
    sub(r"(?:普及组|提高组|省选联考)", "[来源分组已隐藏]")
    sub(r"[红橙黄绿青蓝紫黑](?:色)?题", "[等级描述已隐藏]")
    return text.strip() + "\n", changes


def samples(statement):
    blocks = []
    kind = None
    active = False
    lines = []
    for line in statement.splitlines():
        if re.match(r"^#+\s*(?:样例输入|输入样例)", line):
            kind = "input"
        elif re.match(r"^#+\s*(?:样例输出|输出样例)", line):
            kind = "output"
        elif line.strip().startswith("```"):
            if active:
                blocks.append((kind, "\n".join(lines) + "\n"))
                active = False
                kind = None
            elif kind:
                active = True
                lines = []
        elif active:
            lines.append(line)
    result = []
    pending = None
    for kind, value in blocks:
        if kind == "input":
            pending = value
        elif kind == "output" and pending is not None:
            available = bool(pending.strip() and value.strip()) and not re.search(
                r"见附件|附件中|详见|见下发|下载|\.in/ans|这个样例满足|^\s*见\s+\S+\.(?:in|ans)",
                pending + value, re.M)
            result.append({"input": pending, "output": value, "available": available})
            pending = None
    return result

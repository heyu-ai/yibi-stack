#!/usr/bin/env python3
"""Lint：`.claude/rules/*.md` frontmatter 不得使用會被靜默忽略的路徑 key。

Claude Code 只認得小寫 `paths:` 作為 rule 的路徑範圍。`globs:`、`glob:`、
`path:`、`pattern:`，以及 `Paths:` 等大小寫錯誤的變體都會被靜默忽略，導致原本
預期按路徑載入的 rule 變成每個 session 全量載入。

本 lint 掃描 `.claude/rules/*.md`：無 frontmatter 合法；有 frontmatter 時須為
YAML-ish top-level mapping。只 deny 已知壞 key，不推定完整 allow-list。若有精確小寫
`paths:`，其值須非空，並接受 YAML list 與純量字串兩種形式。

解析僅使用 regex 與逐行判斷，不依賴 YAML library。

Usage:
  python3 scripts/lint_rule_frontmatter.py

Exit code:
  0 -> 無違規
  1 -> 有違規（錯誤 frontmatter key、空 paths 或 malformed frontmatter）
  2 -> 設定錯誤（rules 目錄缺失）
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / ".claude" / "rules"

_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$")
_BAD_ALIASES = {"globs", "glob", "path", "pattern"}
_EMPTY_PATH_VALUES = {"", "[]", "null", "~", "''", '""'}


def lint_frontmatter(text: str) -> list[tuple[int, str]]:
    """回傳 [(line_no, reason), ...]；無 frontmatter 回傳空 list。"""
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []

    end = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip() == "---"), None)
    if end is None:
        return [(1, "frontmatter 缺少結束分隔線 `---`")]

    violations: list[tuple[int, str]] = []
    top_level: list[tuple[str, str, int, int]] = []
    for index, line in enumerate(lines[1:end], 1):
        line_no = index + 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            if not top_level:
                violations.append((line_no, "縮排行出現在任何 top-level key 之前"))
            continue
        if line.startswith("-"):
            continue
        match = _TOP_LEVEL_KEY_RE.fullmatch(line)
        if match is None:
            violations.append((line_no, "不是有效的 top-level `key: value` mapping"))
            continue
        top_level.append((match.group(1), match.group(2) or "", line_no, index))

    if not top_level and not violations:
        violations.append((1, "frontmatter 不含任何 top-level mapping"))

    for position, (key, value, line_no, index) in enumerate(top_level):
        lowered = key.lower()
        if lowered in _BAD_ALIASES or (lowered == "paths" and key != "paths"):
            violations.append((line_no, f"`{key}:` 是會被靜默忽略的路徑 key"))
            continue
        if key != "paths":
            continue
        scalar_value = re.sub(r"(?:^|\s+)#.*$", "", value).strip()
        if (
            len(scalar_value) >= 2
            and scalar_value[0] == scalar_value[-1]
            and scalar_value[0] in "'\""
        ):
            scalar_value = scalar_value[1:-1].strip()
        scalar_value = re.sub(r"^\[\s*\]$", "[]", scalar_value)
        if scalar_value not in _EMPTY_PATH_VALUES:
            continue
        next_index = top_level[position + 1][3] if position + 1 < len(top_level) else end
        children = [line.strip() for line in lines[index + 1 : next_index] if line.strip()]
        list_values = [child[1:].strip() for child in children if child.startswith("-")]
        if not list_values or not any(item and not item.startswith("#") for item in list_values):
            violations.append((line_no, "`paths:` 的值不可為空"))

    return violations


def main() -> int:
    if not RULES_DIR.is_dir():
        print(f"[FAIL] 找不到 rules 目錄：{RULES_DIR}", file=sys.stderr)
        return 2

    violations: list[str] = []
    checked = 0
    for rule_file in sorted(RULES_DIR.glob("*.md")):
        if not rule_file.is_file():
            continue
        try:
            text = rule_file.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[WARN] 無法讀取 .claude/rules/{rule_file.name}：{e}", file=sys.stderr)
            continue
        checked += 1
        for line_no, reason in lint_frontmatter(text):
            violations.append(f"  .claude/rules/{rule_file.name}:{line_no}: {reason}")

    if violations:
        print(f"[FAIL] rule frontmatter 有 {len(violations)} 個違規：", file=sys.stderr)
        for violation in violations:
            print(violation, file=sys.stderr)
        print(
            "\n修法：路徑範圍只使用精確小寫 `paths:`，並提供非空的 list 或純量值。",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] 已檢查 {checked} 個 rule，frontmatter 無違規")
    return 0


if __name__ == "__main__":
    sys.exit(main())

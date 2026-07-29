#!/usr/bin/env python3
"""挑出與本次委託相關的 `.claude/rules/*.md`，供 `/codex-cli` 的 packet 引用。

Claude Code 依 rule frontmatter 的 `paths:` 決定何時載入某個 rule：沒有 `paths:` key
的每個 session 全量載入，有的則只在工具碰到匹配路徑時載入。Codex 沒有這個機制，
所以委託前要由本 script 把「這次任務會碰到的路徑對應到哪些 rule」算出來，寫進 packet
的必讀清單。

glob 語意對齊 Claude Code：非錨定（在任意路徑深度匹配），`**` 跨層、`*` 不跨 `/`。

Usage:
  python3 select_rules.py --repo-root <ROOT> [<changed-path> ...]

不給 changed-path 時只列出全量載入的 rule。

Exit code:
  0 -> 正常（包含「該 repo 沒有 .claude/rules/」的情況，此時 stderr 會有 [WARN]）
  2 -> 參數錯誤或 repo root 不存在
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$")
_QUOTES = "'\""


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """把 Claude Code rule 的 `paths:` glob 轉成 regex。

    非錨定：pattern 前面允許任意路徑前綴，所以 `skills/**` 也會匹配
    `plugins/growth/skills/mycelium/SKILL.md`。
    """
    parts = ["(?:.*/)?"]
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            # `**/` 可匹配零層目錄：`tasks/**/models.py` 要能命中 `tasks/models.py`
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts) + r"\Z")


def _strip_quotes(value: str) -> str:
    value = re.sub(r"(?:^|\s+)#.*$", "", value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTES:
        return value[1:-1].strip()
    return value


def parse_paths(text: str) -> list[str] | None:
    """回傳 rule 的 `paths:` pattern 清單；沒有 `paths:` key 時回傳 None。

    None 表示「全量載入」，與空 list（有 key 但值為空，屬 lint 違規）語意不同。
    """
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip() == "---"), None)
    if end is None:
        return None

    for index, line in enumerate(lines[1:end], 1):
        match = _TOP_LEVEL_KEY_RE.fullmatch(line)
        if match is None or match.group(1) != "paths":
            continue
        raw = re.sub(r"(?:^|\s+)#.*$", "", match.group(2) or "").strip()
        # YAML flow sequence（`paths: ["tasks/**", "scripts/**"]`）——單一 pattern 的 rule
        # 最容易寫成這個形式。不特別處理的話它會落進下面的 scalar 分支，變成一個帶著中括號
        # 與引號的 literal pattern，匹配不到任何真實路徑，然後靜默漏掉該 rule。
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            return [item for item in (_strip_quotes(part) for part in inner.split(",")) if item]
        scalar = _strip_quotes(raw)
        if scalar and scalar not in {"null", "~"}:
            return [scalar]
        patterns = []
        for child in lines[index + 1 : end]:
            stripped = child.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not child[0].isspace() and not stripped.startswith("-"):
                break
            if stripped.startswith("-"):
                item = _strip_quotes(stripped[1:])
                if item:
                    patterns.append(item)
        return patterns
    return None


def frontmatter_is_malformed(text: str) -> bool:
    """frontmatter 有起始 `---` 但缺結束 `---` 時回 True。

    這種檔案會被 `parse_paths` 當成「沒有 frontmatter」而回 None（即全量載入）。方向是
    fail-safe——多載入一個 rule 不會讓 Codex 少收到規範——但它**靜默**，與同一個函式對
    「有 `paths:` key 卻解析不出 pattern」會發 `[WARN]`（見 `select`）的處理不一致。
    呼叫端用本函式補上那個 `[WARN]`，讓兩種「frontmatter 壞掉」得到相同的診斷待遇。
    """
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    return next((i for i, line in enumerate(lines[1:], 1) if line.rstrip() == "---"), None) is None


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def normalize_path(path: str) -> str:
    """去掉開頭的 `./`，但不動到 dot-prefixed 路徑本身。

    不可用 `str.lstrip("./")`：它吃的是**字元集合**不是前綴，`.claude/hooks/x.py` 會被削成
    `claude/hooks/x.py`，於是 `paths: [".claude/hooks/**"]` 這種 rule 永遠不匹配——exit 0、
    無診斷，正是本 script 要防的失敗。
    """
    while path.startswith("./"):
        path = path[2:]
    return path


def select(rules_dir: Path, changed: list[str]) -> tuple[list[str], int]:
    """回傳（packet 用的 markdown 清單行, 命中的 path-scoped rule 數）。

    第二個值與 `len(lines)` 不同：`lines` 還含 always-loaded rule。呼叫端必須用它判斷
    「給了路徑卻沒有任何 scoped rule 命中」——用 `lines` 判斷的話，只要 repo 有任何一個
    always-loaded rule 就永遠不成立。
    """
    selected: list[str] = []
    scoped_hits = 0
    for rule_file in sorted(rules_dir.glob("*.md")):
        if not rule_file.is_file():
            continue
        try:
            text = rule_file.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[WARN] 無法讀取 {rule_file}：{e}", file=sys.stderr)
            continue

        rel = f".claude/rules/{rule_file.name}"
        title = title_of(text, rule_file.stem)
        patterns = parse_paths(text)
        if patterns is None:
            if frontmatter_is_malformed(text):
                print(
                    f"[WARN] {rel} frontmatter 不完整（有起始 --- 但缺結束 ---），"
                    "以全量載入計；請回頭修它的 frontmatter",
                    file=sys.stderr,
                )
            selected.append(f"- `{rel}` — {title}（always loaded）")
            continue
        if not patterns:
            print(
                f"[WARN] {rel} 有 paths: key 但解析不出任何 pattern，該 rule 不會被選入",
                file=sys.stderr,
            )
            continue
        hit = next(
            (
                pattern
                for pattern in patterns
                if any(glob_to_regex(pattern).match(path) for path in changed)
            ),
            None,
        )
        if hit is not None:
            scoped_hits += 1
            selected.append(f"- `{rel}` — {title}（matched `{hit}`）")
    return selected, scoped_hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="挑出與本次委託相關的 .claude/rules/*.md",
        allow_abbrev=False,
    )
    parser.add_argument("--repo-root", required=True, help="目標 repo 的絕對路徑")
    parser.add_argument("paths", nargs="*", help="本次任務會碰到的路徑（相對 repo root）")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    if not repo_root.is_dir():
        print(f"[FAIL] repo root 不存在：{repo_root}", file=sys.stderr)
        return 2

    rules_dir = repo_root / ".claude" / "rules"
    if not rules_dir.is_dir():
        print(
            f"[WARN] {repo_root} 沒有 .claude/rules/ —— 這次委託只有 contract.md 的通用約束，"
            "沒有 repo 專屬規範。",
            file=sys.stderr,
        )
        return 0

    changed = [normalize_path(path) for path in args.paths]
    lines, scoped_hits = select(rules_dir, changed)
    if changed and scoped_hits == 0:
        print(
            f"[WARN] 給定的 {len(changed)} 個路徑沒有命中任何 path-scoped rule —— "
            "確認路徑相對 repo root 且拼字正確，否則 packet 會缺少該檔案適用的規範。",
            file=sys.stderr,
        )
    if not lines:
        print(
            f"[WARN] {rules_dir} 裡沒有任何 rule 可列出（給定 {len(changed)} 個路徑）",
            file=sys.stderr,
        )
        return 0

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

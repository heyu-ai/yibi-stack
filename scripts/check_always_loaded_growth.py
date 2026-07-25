#!/usr/bin/env python3
"""檢查一個 change 是否讓 always-loaded rule 面淨增。

`.claude/rules/*.md` 中 frontmatter **無** `paths:` key 者，每個 session 全量載入
（本 repo 目前為 01/02/03/13/15/16）。retro-evidence-gate 的自我約束要求：治規則
通膨的 change 不得自己讓 always-loaded 面變肥——規範應寫進 scoped rule（如 rule 11，
`paths: skills/**`），而非全量載入檔。

用法：
  # baseline 模式：印出目前 always-loaded 檔清單與總行數
  python3 scripts/check_always_loaded_growth.py

  # check 模式：對 <base>..working 的 git diff，算 always-loaded 檔的淨增行數，
  # 非 0 即 [FAIL]（exit 1）。數字一律印出。
  python3 scripts/check_always_loaded_growth.py --base origin/main

Exit code:
  0 -> baseline 模式成功，或 check 模式淨增 = 0
  1 -> check 模式淨增 != 0（always-loaded 面變動）
  2 -> 設定錯誤（rules 目錄缺失 / git 不可用）

`always_loaded_files()` 與 `has_paths_key()` 為純函式，供測試以合成內容呼叫。
"""

import re
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / ".claude" / "rules"

_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]*.*)?$")


def has_paths_key(text: str) -> bool:
    """frontmatter 是否含精確小寫 top-level `paths:` key（無 frontmatter -> False）。"""
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    end = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip() == "---"), None)
    if end is None:
        return False
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or line[0].isspace():
            continue
        match = _TOP_LEVEL_KEY_RE.fullmatch(line)
        if match is not None and match.group(1) == "paths":
            return True
    return False


def always_loaded_files() -> list[Path]:
    """回傳 `.claude/rules/*.md` 中無 `paths:` key（全量載入）的檔案，已排序。"""
    if not RULES_DIR.is_dir():
        return []
    result: list[Path] = []
    for rule_file in sorted(RULES_DIR.glob("*.md")):
        if not rule_file.is_file():
            continue
        try:
            text = rule_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if not has_paths_key(text):
            result.append(rule_file)
    return result


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def net_growth(base_ref: str, files: list[Path]) -> int:
    """回傳 base..working 對指定檔案的淨增行數（added - removed）。"""
    if not files:
        return 0
    cmd = [
        "git",
        "-C",
        str(REPO_ROOT),
        "diff",
        "--numstat",
        base_ref,
        "--",
        *[_rel(f) for f in files],
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # nosec B603
    if proc.returncode != 0:
        raise RuntimeError(f"git diff 失敗（base={base_ref}）：{proc.stderr.strip()}")
    total = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        added, removed = parts[0], parts[1]
        if added == "-" or removed == "-":
            # 二進位檔；always-loaded 皆為 markdown，理論上不會發生，保守跳過
            continue
        total += int(added) - int(removed)
    return total


def main(argv: list[str]) -> int:
    if not RULES_DIR.is_dir():
        print(f"[FAIL] 找不到 rules 目錄：{RULES_DIR}", file=sys.stderr)
        return 2

    files = always_loaded_files()
    base_ref: str | None = None
    if "--base" in argv:
        idx = argv.index("--base")
        if idx + 1 >= len(argv):
            print("[FAIL] --base 需要一個 ref 參數", file=sys.stderr)
            return 2
        base_ref = argv[idx + 1]

    if base_ref is None:
        total_lines = 0
        print(f"[OK] always-loaded rule 檔（無 paths: key），共 {len(files)} 個：")
        for f in files:
            n = len(f.read_text(encoding="utf-8").splitlines())
            total_lines += n
            print(f"  {_rel(f)}: {n} 行")
        print(f"baseline 總行數：{total_lines}")
        return 0

    try:
        growth = net_growth(base_ref, files)
    except RuntimeError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    print(f"always-loaded 面淨增行數（{base_ref}..working）：{growth}")
    if growth != 0:
        print(
            f"[FAIL] always-loaded 面淨增 {growth} 行（應為 0）。"
            "規範內容請寫進 scoped rule（如 rule 11，paths: skills/**），"
            "而非全量載入檔（01/02/03/13/15/16）。",
            file=sys.stderr,
        )
        return 1
    print("[OK] always-loaded 面淨增為 0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""檢查一個 change 是否讓 always-loaded rule 面淨增。

`.claude/rules/*.md` 中 frontmatter **無** `paths:` key 者，每個 session 全量載入
（本 repo 目前為 01/02/03/13/15/16）。retro-evidence-gate 的自我約束要求：治規則
通膨的 change 不得自己讓 always-loaded 面變肥——規範應寫進 scoped rule（如 rule 11，
`paths: skills/**`），而非全量載入檔。

用法：
  # baseline 模式：印出目前 always-loaded 檔清單與總行數
  python3 scripts/check_always_loaded_growth.py

  # check 模式：對 merge-base(<base>, HEAD)..working 的淨增行數，非 0 即 [FAIL]（exit 1）。
  # 數字一律印出。--base <ref> 與 --base=<ref> 兩種形式皆可。
  python3 scripts/check_always_loaded_growth.py --base origin/main

Exit code:
  0 -> baseline 模式成功，或 check 模式淨增 = 0
  1 -> check 模式淨增 != 0（always-loaded 面變動）
  2 -> 設定錯誤（rules 目錄缺失 / git 不可用 / 參數錯誤）

`always_loaded_files()` 與 `has_paths_key()` 為純函式，供測試以合成內容呼叫。

淨增計算涵蓋三種 always-loaded 成員資格變化，不只是「目前仍是 always-loaded 的檔案」
這個交集內的逐行 diff：
  1. 新增（含尚未 `git add` 的 untracked 檔）或由 `paths:`-scoped 轉為 always-loaded
     -> 整檔（working 版本）行數計入淨增。
  2. 刪除，或由 always-loaded 轉為 `paths:`-scoped -> 整檔（base 版本）行數計入淨減。
  3. 兩邊都是 always-loaded -> 正常逐行 diff（added - removed）。
"""

import re
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / ".claude" / "rules"

_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]*.*)?$")


def _run_git(*args: str) -> str:
    """執行 git 指令，回傳 stdout；任何失敗（含 git 不可用 / 逾時）皆轉為 RuntimeError。"""
    cmd = ["git", "-C", str(REPO_ROOT), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # nosec B603
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"git {' '.join(args)} 無法執行：{e}") from e
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗：{proc.stderr.strip()}")
    return proc.stdout


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
        except OSError as e:
            print(
                f"[WARN] 無法讀取 {rule_file}：{e}（此檔不計入 always-loaded 檔案清單）",
                file=sys.stderr,
            )
            continue
        if not has_paths_key(text):
            result.append(rule_file)
    return result


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _merge_base(base_ref: str) -> str:
    return _run_git("merge-base", base_ref, "HEAD").strip()


def _always_loaded_paths_at_ref(ref: str) -> set[str]:
    """回傳指定 ref 版本中，`.claude/rules/*.md` 裡無 `paths:` key 的檔案相對路徑集合。"""
    listing = _run_git("ls-tree", "-r", "--name-only", ref, "--", ".claude/rules")
    result: set[str] = set()
    for rel in listing.splitlines():
        rel = rel.strip()
        if not rel.endswith(".md"):
            continue
        try:
            content = _run_git("show", f"{ref}:{rel}")
        except RuntimeError:
            # 該 ref 下讀不到此檔（理論上不會發生，ls-tree 剛列出它）；保守不計入。
            continue
        if not has_paths_key(content):
            result.add(rel)
    return result


def _line_count_at_ref(ref: str, rel_path: str) -> int:
    try:
        content = _run_git("show", f"{ref}:{rel_path}")
    except RuntimeError:
        return 0
    return len(content.splitlines())


def _numstat_delta(ref: str, rel_path: str) -> int:
    """回傳單一檔案在 ref..working 的逐行淨增（added - removed）；忽略二進位檔。"""
    output = _run_git("diff", "--numstat", ref, "--", rel_path)
    total = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        added, removed = parts[0], parts[1]
        if added == "-" or removed == "-":
            continue  # 二進位檔；always-loaded 皆為 markdown，理論上不會發生，保守跳過
        total += int(added) - int(removed)
    return total


def net_growth(base_ref: str, current_files: list[Path]) -> int:
    """回傳 merge-base(base_ref, HEAD)..working 的 always-loaded 面淨增行數。

    不只算「目前仍是 always-loaded 的檔案」這個交集內的逐行 diff——那樣會漏掉：
    (a) 尚未 `git add` 的新 always-loaded 檔（untracked，`git diff --numstat` 看不到）；
    (b) 在 base 存在、但 working 已刪除或轉為 `paths:`-scoped 的檔案（同樣不在交集內，
        其行數變化會被完全忽略而非正確地計入淨減）。
    """
    merge_base = _merge_base(base_ref)
    base_paths = _always_loaded_paths_at_ref(merge_base)
    current_paths = {_rel(f) for f in current_files}

    total = 0
    for rel in current_paths - base_paths:
        # 新增（含 untracked）或由 scoped 轉為 always-loaded：整檔（working）行數計入淨增。
        total += len((REPO_ROOT / rel).read_text(encoding="utf-8").splitlines())
    for rel in base_paths - current_paths:
        # 刪除，或由 always-loaded 轉為 scoped：整檔（base 版本）行數計入淨減。
        total -= _line_count_at_ref(merge_base, rel)
    for rel in current_paths & base_paths:
        # 兩邊都是 always-loaded：正常逐行 diff。
        total += _numstat_delta(merge_base, rel)
    return total


def _parse_base_arg(argv: list[str]) -> str | None:
    """解析 `--base <ref>` 或 `--base=<ref>` 形式；無 --base 回傳 None；其餘一律 ValueError。

    不接受未知參數而靜默忽略——先前只認 `--base` 分開token的形式，`--base=<ref>`
    （最常見的等號寫法）完全不觸發任何比對，靜默落回 baseline 模式並 exit 0。
    """
    i = 0
    base_ref: str | None = None
    while i < len(argv):
        arg = argv[i]
        if arg == "--base":
            if i + 1 >= len(argv):
                raise ValueError("--base 需要一個 ref 參數")
            base_ref = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--base="):
            value = arg[len("--base=") :]
            if not value:
                raise ValueError("--base= 需要一個非空 ref 值")
            base_ref = value
            i += 1
            continue
        raise ValueError(f"未知參數：{arg}")
    return base_ref


def main(argv: list[str]) -> int:
    if not RULES_DIR.is_dir():
        print(f"[FAIL] 找不到 rules 目錄：{RULES_DIR}", file=sys.stderr)
        return 2

    files = always_loaded_files()
    try:
        base_ref = _parse_base_arg(argv)
    except ValueError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2

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

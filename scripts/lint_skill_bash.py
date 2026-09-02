#!/usr/bin/env python3
"""Lint bash fenced blocks in SKILL.md / commands markdown files.

從 commands/*.md、skills/**/SKILL.md、.claude/commands/*.md、
plugins/**/SKILL.md、plugins/**/commands/*.md 抽取
所有 ```bash fenced block，透過現有 PreToolUse hook 驗證是否有
bash anti-pattern 違規。

把 runtime 才知道的問題提前到 commit 時間：
- .claude/hooks/bash-ap1-inline-check.sh（AP1：inline Python / osascript /
  grep BRE / nested subshell）
- .claude/hooks/bash-ap2-check.py（AP2：Unicode em dash / emoji 等）

Usage:
  python3 scripts/lint_skill_bash.py          # warn-only（預設）
  python3 scripts/lint_skill_bash.py --fail   # 有違規時 exit 1

Default warn-only 模式在初期部署使用；所有現有違規修完後改為 --fail 模式。

**斷掉的 symlink 一律硬失敗**（不受 warn-only 影響，且不依賴 hook 檔案是否存在）：
頂層 `commands/<cmd>.md` 是指向 `plugins/<pack>/...` 的 symlink，刪除或搬動 plugin 端
而漏了 `git rm` 頂層 symlink，`commands/*.md` 這條 glob 仍會命中該路徑但
`read_text()` 拋 FileNotFoundError。在此之前那是未捕捉的 traceback，會讓 pre-commit
與 CI 一起掛，且錯誤訊息不指出是哪個 symlink——連 lint 都跑不了來查。改為具名
`[FAIL]` 後，失敗仍是失敗，但訊息可行動。

**這條硬失敗只涵蓋 `commands/<cmd>.md`，不涵蓋 `skills/<name>`。** `MD_GLOBS` 對
skills 的樣式是 `skills/**/SKILL.md`——pathlib 的 `**` **不會下降到斷線的目錄
symlink**（`.claude/rules/02-error-and-import.md` 已記載：`Path.rglob()` / `**`
不跟隨 symlink）。故一個斷掉的 `skills/<name>` 目錄 symlink 對這條 glob 完全不可見，
既有 `find_broken_links()` 也就永遠偵測不到它——那一半的涵蓋面交給
`scripts/lint_plugin_layout.py` 的斷言 1（`check_root_symlinks()`，用
`SKILLS_DIR.iterdir()` 逐一檢查，不受 `**` 的限制）。

Exit code:
  0 -> 所有 block 通過，或 warn-only 模式（即使有 anti-pattern 違規）
  1 -> --fail 模式且有 anti-pattern 違規；或（任何模式）偵測到斷掉的 commands/*.md
       symlink；或（任何模式）掃描過程中有檔案讀取失敗（結構性錯誤，不受 warn-only
       影響——讀不到檔案代表掃描不完整，與「掃描完但發現風格違規」是不同性質的失敗）
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

FAIL_MODE = "--fail" in sys.argv

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
AP1_HOOK = HOOKS_DIR / "bash-ap1-inline-check.sh"
AP2_HOOK = HOOKS_DIR / "bash-ap2-check.py"

BASH_FENCE = re.compile(r"^```bash\s*\n(.*?)\n```", re.DOTALL | re.MULTILINE)

# --add-dir followed by a value that is NOT absolute (no leading / or $).
# Supports both whitespace and = separators: --add-dir . | --add-dir=.
# Captures: --add-dir . | --add-dir ./foo | --add-dir foo/bar | --add-dir=.
# Safe (not matched): --add-dir "$VAR" | --add-dir /abs/path | --add-dir "${VAR}"
_RELATIVE_ADD_DIR = re.compile(
    r"--add-dir(?:\s+|=)"
    r"(?:"
    r'"([^/$][^"]*)"'  # double-quoted relative: --add-dir "."
    r"|"
    r"'([^/$][^']*)'"  # single-quoted relative: --add-dir '.'
    r"|"
    r"([^/$\s\"'][^\s]*)"  # unquoted relative: --add-dir .
    r")"
)

MD_GLOBS = [
    "commands/*.md",
    "skills/**/SKILL.md",
    ".claude/commands/*.md",
    "plugins/**/SKILL.md",
    "plugins/**/commands/*.md",
]


def find_markdown_files() -> list[Path]:
    files: list[Path] = []
    for pattern in MD_GLOBS:
        files.extend(REPO_ROOT.glob(pattern))
    return sorted(set(files))


def find_broken_links(files: list[Path]) -> list[Path]:
    """回傳 glob 命中但無法解析的路徑（斷掉的 symlink）。

    `Path.glob()` 以名稱比對，會命中 dangling symlink；`exists()` 走訪連結目標故回傳
    False。兩者的差集就是壞掉的 symlink。（實測：glob 命中、exists=False、
    is_symlink=True、read_text 拋 FileNotFoundError errno=2。）
    """
    return [p for p in files if not p.exists()]


def extract_bash_blocks(path: Path) -> list[tuple[int, str]]:
    """回傳 [(起始行號, bash block 內容), ...] 清單。

    呼叫端須先以 find_broken_links() 濾掉斷掉的 symlink；此處的 OSError 保護是
    TOCTOU 防線（檢查與讀取之間檔案可能被移除），見 .claude/rules/02。
    """
    content = path.read_text(encoding="utf-8")
    blocks = []
    for m in BASH_FENCE.finditer(content):
        line_no = (
            content[: m.start()].count("\n") + 2
        )  # +2: skip fence line, point to first bash line
        code = m.group(1)
        blocks.append((line_no, code))
    return blocks


def check_relative_add_dir(block: str) -> list[str]:
    """Return diagnostics for every --add-dir with a relative path in the block."""
    results: list[str] = []
    for m in _RELATIVE_ADD_DIR.finditer(block):
        value = m.group(1) or m.group(2) or m.group(3)
        results.append(
            f"--add-dir 使用相對路徑 '{value}'；"
            "agy 1.1.22 不再解析相對路徑，必須傳絕對路徑"
            '（如 "$REPO_ROOT"）'
        )
    return results


def _run_hook(hook_cmd: list[str], command: str) -> tuple[int, str]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    result = subprocess.run(
        hook_cmd,
        input=payload,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.returncode, result.stdout.strip()


_HOOKS: list[tuple[list[str], str]] = [
    ([str(AP1_HOOK)], "AP1"),
    (["python3", str(AP2_HOOK)], "AP2"),
]


def _active_hooks() -> list[tuple[list[str], str]]:
    return [(cmd, label) for cmd, label in _HOOKS if Path(cmd[-1]).exists()]


def lint_file(path: Path, active_hooks: list[tuple[list[str], str]]) -> tuple[list[str], list[str]]:
    """回傳 (anti_pattern_violations, structural_errors)。

    兩者分開回傳，不合併成一個清單——結構性讀取失敗（OSError）代表掃描本身不完整，
    必須讓呼叫端無條件 exit 1；若併入 anti-pattern violations 清單，warn-only 模式
    會把它跟「掃描完、發現風格問題」同等對待，回報成功，而使用者無法區分
    「沒有壞 symlink/讀取問題」與「掃描根本沒跑完」。
    """
    anti_pattern: list[str] = []
    structural: list[str] = []
    rel = path.relative_to(REPO_ROOT)
    try:
        blocks = extract_bash_blocks(path)
    except OSError as e:
        # TOCTOU：find_broken_links() 之後、讀取之前檔案被移除或權限變更
        structural.append(f"  {rel}: 無法讀取（{type(e).__name__}: {e.strerror}）")
        return anti_pattern, structural
    for line_no, block in blocks:
        for hook_cmd, label in active_hooks:
            code, msg = _run_hook(hook_cmd, block)
            if code == 2:
                first_line = msg.split("\n")[0] if msg else "violation"
                anti_pattern.append(f"  {rel}:{line_no}: [{label}] {first_line}")
            elif code not in (0, 1):
                anti_pattern.append(f"  {rel}:{line_no}: [{label}] hook exited {code} (crash?)")
    return anti_pattern, structural


def main() -> int:
    files = find_markdown_files()
    if not files:
        print("[SKIP] 找不到 markdown 檔案可驗證")
        return 0

    # 結構性錯誤先擋，且不依賴 hook 是否存在：斷掉的 symlink 不是 style 問題，
    # warn-only 也必須失敗。這一步必須在下面的 hook-availability 檢查之前執行——
    # 否則 hook 檔案缺失時的早退（見下）會讓這裡永遠跑不到，dangling symlink
    # 完全偵測不到卻回報 exit 0（SF-2 finding：兩者曾經順序相反）。
    broken = find_broken_links(files)
    if broken:
        print(f"[FAIL] 偵測到 {len(broken)} 個斷掉的 symlink：", file=sys.stderr)
        for p in broken:
            target = os.readlink(p) if p.is_symlink() else "(不是 symlink，路徑無法解析)"
            print(f"  {p.relative_to(REPO_ROOT)} -> {target}", file=sys.stderr)
        print(
            "\n修法：plugin 端的 command/skill 被刪除或搬到別的 pack 時，頂層 symlink 必須"
            "一併處理——\n"
            "  搬動 -> 重指到新路徑（與 git mv 同一個 commit）\n"
            "  刪除 -> git rm 該 symlink\n"
            "驗證時用 `ls <link>/`（帶尾斜線）解參考，`ls -la <link>` 對斷掉的 symlink 也會成功。",
            file=sys.stderr,
        )
        return 1

    # --add-dir 相對路徑偵測：獨立於 hook，與 dangling symlink 同等級——安全性守門
    # 不受 hook 可用性影響。在 hook-availability 檢查之前執行。
    add_dir_violations: list[str] = []
    for f in files:
        rel = f.relative_to(REPO_ROOT)
        try:
            blocks = extract_bash_blocks(f)
        except OSError as e:
            # no-hooks 路徑不會走到 lint_file()，所以這裡必須自行回報
            print(
                f"  [WARN] {rel}: 無法讀取（{type(e).__name__}），跳過 --add-dir 偵測",
                file=sys.stderr,
            )
            continue
        for line_no, block in blocks:
            for diag in check_relative_add_dir(block):
                add_dir_violations.append(f"  {rel}:{line_no}: [ADD-DIR] {diag}")

    active_hooks = _active_hooks()
    if not active_hooks:
        print(
            "[WARN] lint_skill_bash: no hook files found — skipping anti-pattern"
            " validation (check HOOKS_DIR)",
            file=sys.stderr,
        )
        if add_dir_violations:
            level = "[FAIL]" if FAIL_MODE else "[WARN]"
            print(
                f"{level} --add-dir 相對路徑違規（{len(add_dir_violations)} 個）：",
                file=sys.stderr,
            )
            for v in add_dir_violations:
                print(v, file=sys.stderr)
            print(file=sys.stderr)
            print(
                '修法：傳絕對路徑（如 "$REPO_ROOT"），見 .claude/rules/13-bash-anti-patterns.md',
                file=sys.stderr,
            )
            if not FAIL_MODE:
                print(
                    "提示：用 --fail 旗標可讓此 script 在有違規時 exit 1",
                    file=sys.stderr,
                )
            return 1 if FAIL_MODE else 0
        return 0

    all_violations: list[str] = list(add_dir_violations)
    all_structural: list[str] = []
    for f in files:
        violations, structural = lint_file(f, active_hooks)
        all_violations.extend(violations)
        all_structural.extend(structural)

    # 結構性讀取失敗一律硬失敗，不受 warn-only / --fail 影響——與上面的斷線 symlink
    # 檢查同一個等級：讀不到檔案代表掃描不完整，不是「掃描完發現風格違規」。
    if all_structural:
        print(
            f"[FAIL] {len(all_structural)} 個檔案讀取失敗（結構性錯誤，不受 warn-only 影響）：",
            file=sys.stderr,
        )
        for s in all_structural:
            print(s, file=sys.stderr)
        return 1

    if all_violations:
        level = "[FAIL]" if FAIL_MODE else "[WARN]"
        print(f"{level} bash anti-pattern 違規（{len(all_violations)} 個）：")
        for v in all_violations:
            print(v)
        print()
        print("修法：依照 .claude/rules/13-bash-anti-patterns.md 規則調整")
        if not FAIL_MODE:
            print("提示：用 --fail 旗標可讓此 script 在有違規時 exit 1")
        return 1 if FAIL_MODE else 0

    print(f"[OK] 已驗證 {len(files)} 個 markdown 檔案，無 bash anti-pattern 違規")
    return 0


if __name__ == "__main__":
    sys.exit(main())

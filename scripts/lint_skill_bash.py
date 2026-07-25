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

**斷掉的 symlink 一律硬失敗**（不受 warn-only 影響）：頂層 `commands/<cmd>.md` 與
`skills/<name>` 是指向 `plugins/<pack>/...` 的 symlink，刪除或搬動 plugin 端而漏了
`git rm` 頂層 symlink，glob 仍會命中該路徑但 `read_text()` 拋 FileNotFoundError。
在此之前那是未捕捉的 traceback，會讓 pre-commit 與 CI 一起掛，且錯誤訊息不指出是哪個
symlink——連 lint 都跑不了來查。改為具名 `[FAIL]` 後，失敗仍是失敗，但訊息可行動。

Exit code:
  0 -> 所有 block 通過，或 warn-only 模式（即使有 anti-pattern 違規）
  1 -> --fail 模式且有 anti-pattern 違規，或（任何模式）偵測到斷掉的 symlink
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
_ACTIVE_HOOKS = [(cmd, label) for cmd, label in _HOOKS if Path(cmd[-1]).exists()]
if not _ACTIVE_HOOKS:
    print("[WARN] lint_skill_bash: no hook files found — skipping validation (check HOOKS_DIR)")
    import sys as _sys

    _sys.exit(0)


def lint_file(path: Path) -> list[str]:
    violations: list[str] = []
    rel = path.relative_to(REPO_ROOT)
    try:
        blocks = extract_bash_blocks(path)
    except OSError as e:
        # TOCTOU：find_broken_links() 之後、讀取之前檔案被移除或權限變更
        return [f"  {rel}: 無法讀取（{type(e).__name__}: {e.strerror}）"]
    for line_no, block in blocks:
        for hook_cmd, label in _ACTIVE_HOOKS:
            code, msg = _run_hook(hook_cmd, block)
            if code == 2:
                first_line = msg.split("\n")[0] if msg else "violation"
                violations.append(f"  {rel}:{line_no}: [{label}] {first_line}")
            elif code not in (0, 1):
                violations.append(f"  {rel}:{line_no}: [{label}] hook exited {code} (crash?)")
    return violations


def main() -> int:
    files = find_markdown_files()
    if not files:
        print("[SKIP] 找不到 markdown 檔案可驗證")
        return 0

    # 結構性錯誤先擋：斷掉的 symlink 不是 style 問題，warn-only 也必須失敗。
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

    all_violations: list[str] = []
    for f in files:
        all_violations.extend(lint_file(f))

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

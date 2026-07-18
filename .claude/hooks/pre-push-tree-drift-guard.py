#!/usr/bin/env python3
"""PreToolUse hook: push 前擋下「已驗證的樹 != 要 push 的樹」。

pre-commit 的 formatter hook（ruff-format、trailing-whitespace 等）是**就地改檔**，
不是唯讀檢查。於是這條路徑會靜默失敗：

    commit -> make ci（formatter 就地改寫工作區）-> 綠 -> push

本地綠是真的，但那個改寫從未進 commit，CI 端沒有工作區可以 commit，必然紅。
（實例：yibi-stack PR #248，本地 make ci 全綠、CI 的 ruff-format 紅。）

本 hook 在 push 這個時間點檢查已追蹤檔案是否有未 commit 的改動——因為乾淨的流程
（改 -> CI -> commit -> push）在 push 前必然已經把驗證過的內容 commit 了。刻意不在
「跑完 make ci 當下」檢查：那一刻正常流程與 bug 流程的工作區狀態完全相同，無從分辨。

只看已追蹤檔案（git diff），不看未追蹤檔案：未追蹤檔（產生物、暫存檔）不影響
push 出去的樹，納入只會製造誤報。

Exit code:
  0 -> 放行
  2 -> 攔截（block）並顯示說明

規則來源：~/.claude/CLAUDE.md「Verification Before Claiming Done」
"""

import json
import re
import subprocess  # nosec B404
import sys

# 只匹配作為指令執行的 git push（允許 git -C <path> push 與前置 env var 賦值），
# 不匹配出現在 commit message 或 echo 字串內的 literal text。
_GIT_PUSH_CMD = re.compile(
    r"(?:^|[;&|]|\n)\s*(?:\w+=\S+\s+)*git\s+(?:-C\s+\S+\s+)*push\b",
    re.MULTILINE,
)


def _dirty_tracked_files() -> list[str]:
    """回傳有未 commit 改動的已追蹤檔案（unstaged + staged）。

    --cached 之外再跑一次無 flag 版本，是為了同時涵蓋「已 stage 但未 commit」——
    兩者都會讓 push 出去的樹與工作區不一致。
    """
    files: list[str] = []
    for args in (["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]):
        result = subprocess.run(  # nosec B603 B607
            args,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []  # fail-open：git 不可用或非 repo，不擋
        files.extend(line for line in result.stdout.splitlines() if line)
    return sorted(set(files))


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            sys.exit(0)
        command: str = data.get("tool_input", {}).get("command", "")
    except Exception:
        sys.exit(0)

    if not _GIT_PUSH_CMD.search(command):
        sys.exit(0)

    dirty = _dirty_tracked_files()
    if not dirty:
        sys.exit(0)

    listed = "\n".join(f"    {f}" for f in dirty)
    print(
        "[BLOCKED] 有未 commit 的已追蹤改動，你驗證過的樹不是你要 push 的樹\n"
        "\n"
        f"{listed}\n"
        "\n"
        "若這些是 pre-commit 的 formatter 就地改寫（ruff-format 等），\n"
        "它們沒進 commit，CI 會在同一個 hook 上必然變紅——本地綠是真的，\n"
        "但那個綠來自工作區，不是來自你 push 出去的 commit。\n"
        "\n"
        "出路（擇一）：\n"
        "  1. 這些改動該進 PR：git add <files> && git commit\n"
        "  2. 這些是無關的 WIP：git stash 之後再 push\n"
        "\n"
        "規則來源：~/.claude/CLAUDE.md「Verification Before Claiming Done」"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()

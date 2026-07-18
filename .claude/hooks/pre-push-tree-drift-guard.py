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
import os
import re
import subprocess  # nosec B404
import sys

# 只匹配作為指令執行的 git push（允許 git -C <path> push 與前置 env var 賦值），
# 不匹配出現在 commit message 或 echo 字串內的 literal text。
_PATH_TOKEN = r'(?:"[^"]*"|\'[^\']*\'|[^\s;&|]+)'
_GIT_PUSH_CMD = re.compile(
    rf"(?:^|[;&|]|\n)\s*(?:\w+=\S+\s+)*git\s+(?:-C\s+{_PATH_TOKEN}\s+)*push\b",
    re.MULTILINE,
)
_GIT_C_ARG = re.compile(rf"-C\s+({_PATH_TOKEN})")
_UNRESOLVABLE_PATH = re.compile(r"['\"$`~()]")
_NOT_A_GIT_REPO = "not a git repository"
_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


class GitCheckError(RuntimeError):
    """Git tree state could not be verified safely."""


def _resolve_git_cwd(match: re.Match[str]) -> str | None:
    """Resolve repeated literal -C paths using Git's cumulative semantics.

    Each relative -C is relative to the preceding location; an absolute path resets
    the base. Shell-expanded or quoted paths are deliberately rejected because the
    hook cannot reproduce shell evaluation safely and guessing would fail open.
    """
    paths = _GIT_C_ARG.findall(match.group(0))
    if not paths:
        return None
    if any(_UNRESOLVABLE_PATH.search(path) for path in paths):
        raise GitCheckError("無法靜態解析 git -C 路徑，無法確認目標工作樹。")

    cwd = os.getcwd()
    for path in paths:
        cwd = os.path.normpath(os.path.join(cwd, path))
    return cwd


def _dirty_tracked_files(cwd: str | None = None) -> list[str]:
    """回傳有未 commit 改動的已追蹤檔案（unstaged + staged）。

    --cached 之外再跑一次無 flag 版本，是為了同時涵蓋「已 stage 但未 commit」——
    兩者都會讓 push 出去的樹與工作區不一致。
    """
    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    env["LC_ALL"] = "C"

    files: list[str] = []
    for args in (["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]):
        try:
            result = subprocess.run(  # nosec B603 B607
                args,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
            )
        except OSError as e:
            raise GitCheckError(f"Git 檢查失敗：{e}") from e
        if result.returncode != 0:
            if _NOT_A_GIT_REPO in result.stderr.lower():
                return []  # 真正的非 Git 目錄不屬於本 guard 的保護範圍。
            detail = result.stderr.strip() or f"git 結束碼 {result.returncode}"
            raise GitCheckError(f"Git 檢查失敗：{detail}")
        files.extend(line for line in result.stdout.splitlines() if line)
    return sorted(set(files))


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            sys.exit(0)
        command = data.get("tool_input", {}).get("command", "")
    except Exception:
        sys.exit(0)

    if not isinstance(command, str):
        sys.exit(0)

    match = _GIT_PUSH_CMD.search(command)
    if match is None:
        sys.exit(0)

    try:
        cwd = _resolve_git_cwd(match)
        dirty = _dirty_tracked_files(cwd)
    except GitCheckError as e:
        print(f"[BLOCKED] {e}\n請改用可靜態解析的 git -C 路徑後再 push。")
        sys.exit(2)
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

#!/usr/bin/env python3
"""PreToolUse hook: 防止 worktree checkout main/master branch.

攔截兩個向量：
  1. EnterWorktree tool  — branch 參數為 main/master
  2. Bash tool           — git worktree add <path> main|master

Exit codes:
  0 -> 放行
  2 -> 攔截，並把 stdout 訊息顯示給使用者

原因：linked worktree 佔用 main，讓主 repo 無法 git checkout main，
      導致 /clean-merged 等工具失效。
"""

import json
import re
import sys

_PROTECTED = frozenset(("main", "master"))

_BLOCK_MSG = """\
BLOCKED: worktree 禁止 checkout '{branch}'!

原因：linked worktree 佔用 main 後，主 repo 無法執行 git checkout main，
      /clean-merged 等工具將全部失效。

請改用 feature branch：
  git checkout -b <feature-branch>
  git worktree add .claude/worktrees/<name> <feature-branch>
"""


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name: str = data.get("tool_name", "")
    tool_input: dict = data.get("tool_input", {})

    # --- Vector 1: EnterWorktree tool ----------------------------------------
    if tool_name == "EnterWorktree":
        branch = tool_input.get("branch", "")
        if branch in _PROTECTED:
            print(_BLOCK_MSG.format(branch=branch))
            sys.exit(2)
        sys.exit(0)

    # --- Vector 2: Bash tool — git worktree add --------------------------------
    if tool_name != "Bash":
        sys.exit(0)

    cmd: str = tool_input.get("command", "")
    if not cmd:
        sys.exit(0)

    for part in re.split(r"&&|\|\||[;\n]", cmd):
        stripped = part.strip().lstrip("(").strip()
        if not re.match(r"git\s+worktree\s+add\b", stripped):
            continue
        # Positional args after "git worktree add" (skip flags starting with -)
        tokens = stripped.split()
        positional = [t for t in tokens[3:] if not t.startswith("-")]
        # positional[0] = path, positional[1] = branch (optional)
        if len(positional) >= 2 and positional[-1] in _PROTECTED:
            print(_BLOCK_MSG.format(branch=positional[-1]))
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()

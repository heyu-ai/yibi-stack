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

Known limitations (static analysis; determined bypass is possible):
  - git -C <path> worktree add ... pattern not matched (regex anchored to "git worktree add")
  - ENV=val git worktree add ... prefix not stripped
"""

import json
import re
import shlex
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

# -b/-B both introduce a new branch name as their next token.
# --orphan does NOT take an argument value in modern git (branch name comes via -b).
_FLAGS_WITH_BRANCH = frozenset(("-b", "-B"))

# Detach flags: worktree in detached HEAD, does not lock the branch ref.
_DETACH_FLAGS = frozenset(("-d", "--detach"))


def _normalize_ref(ref: str) -> str:
    """Strip refs/heads/ prefix for comparison against _PROTECTED."""
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return ref


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if not isinstance(data, dict):
        sys.exit(0)

    tool_name: str = data.get("tool_name", "")
    raw_input = data.get("tool_input")
    if not isinstance(raw_input, dict):
        sys.exit(0)
    tool_input: dict[str, object] = raw_input

    # --- Vector 1: EnterWorktree tool ----------------------------------------
    if tool_name == "EnterWorktree":
        branch = tool_input.get("branch", "")
        if isinstance(branch, str) and branch in _PROTECTED:
            print(_BLOCK_MSG.format(branch=branch))
            sys.exit(2)
        sys.exit(0)

    # --- Vector 2: Bash tool — git worktree add --------------------------------
    if tool_name != "Bash":
        sys.exit(0)

    cmd = tool_input.get("command", "")
    if not isinstance(cmd, str) or "worktree" not in cmd:
        sys.exit(0)

    for part in re.split(r"&&|\|\||[;\n]", cmd):
        stripped = part.strip().lstrip("(").strip()
        if not re.match(r"git\s+worktree\s+add\b", stripped):
            continue

        try:
            tokens = shlex.split(stripped)
        except ValueError:
            tokens = stripped.split()

        # Detach flags: detached HEAD does not lock the branch ref.
        if any(t in _DETACH_FLAGS for t in tokens):
            continue

        # Walk tokens[3:] (after "git worktree add").
        # Capture -b/-B value as the new branch name being created.
        # When -b/-B is used, the last remaining positional is the start-point
        # (base commit), not the checkout target.
        positional: list[str] = []
        new_branch: str | None = None
        i = 3
        while i < len(tokens):
            t = tokens[i]
            if t in _FLAGS_WITH_BRANCH:
                if i + 1 < len(tokens):
                    new_branch = tokens[i + 1]
                i += 2
            elif t.startswith("-"):
                i += 1
            else:
                positional.append(t)
                i += 1

        if new_branch is not None and _normalize_ref(new_branch) in _PROTECTED:
            print(_BLOCK_MSG.format(branch=new_branch))
            sys.exit(2)

        if new_branch is None and len(positional) >= 2:
            if _normalize_ref(positional[-1]) in _PROTECTED:
                print(_BLOCK_MSG.format(branch=positional[-1]))
                sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()

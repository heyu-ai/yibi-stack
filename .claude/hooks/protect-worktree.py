#!/usr/bin/env python3
"""PreToolUse hook: 防止 worktree checkout main/master branch.

攔截三個向量：
  1. EnterWorktree tool  — branch 參數為 main/master
  2. Bash tool           — git worktree add <path> main|master
  3. Bash tool           — 在 linked worktree 內 git checkout/switch main|master
                           （worktree 建好之後再切到 main，一樣會佔用 main ref）

Exit codes:
  0 -> 放行
  2 -> 攔截，原因寫到 stderr（exit 2 時 stdout 不會送達 model）

原因：linked worktree 佔用 main，讓主 repo 無法 git checkout main，
      導致 /clean-wt 等工具失效。

Known limitations (static analysis; determined bypass is possible):
  - git -C <path> worktree add ... not matched (regex anchored to "git worktree add")
  - ENV=val git worktree add ... prefix not stripped
  - shell aliases for 'git' not expanded
  - vector 3 判斷 linked worktree 時若 git 本身失敗（不在 repo、權限問題），一律放行：
    無法判斷時不擋，避免在非 git 目錄誤擋所有 checkout
"""

import json
import os
import re
import shlex
import subprocess  # nosec B404
import sys

_PROTECTED = frozenset(("main", "master"))

_BLOCK_MSG = """\
BLOCKED: worktree 禁止 checkout '{branch}'!

原因：linked worktree 佔用 main 後，主 repo 無法執行 git checkout main，
      /clean-wt 等工具將全部失效。

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
        return ref[len("refs/heads/") :]
    return ref


def _block(branch: str) -> None:
    print(_BLOCK_MSG.format(branch=branch), file=sys.stderr)
    sys.exit(2)


# checkout/switch 之後出現這些旗標，代表建立新 branch 或 detached，不會佔用 main ref
_SWITCH_SAFE_FLAGS = frozenset(
    ("-b", "-B", "-c", "-C", "--orphan", "-d", "--detach", "--create", "--force-create")
)


def _checkout_target(tokens: list[str]) -> tuple[str | None, str | None]:
    """解析 `git [-C dir] checkout|switch ...`，回傳 (要切到的受保護 branch, -C 目錄)。

    不是切換 branch 的形式（還原檔案的 `--`、建新 branch、detached）回傳 (None, None)。
    """
    if not tokens or tokens[0] != "git":
        return None, None
    i = 1
    git_dir: str | None = None
    while i < len(tokens) and tokens[i].startswith("-"):
        if tokens[i] in ("-C", "-c") and i + 1 < len(tokens):
            if tokens[i] == "-C":
                git_dir = tokens[i + 1]
            i += 2
        else:
            i += 1
    if i >= len(tokens) or tokens[i] not in ("checkout", "switch"):
        return None, None
    args = tokens[i + 1 :]
    if "--" in args or any(a.split("=", 1)[0] in _SWITCH_SAFE_FLAGS for a in args):
        return None, None
    positional = [a for a in args if not a.startswith("-")]
    if positional and _normalize_ref(positional[0]) in _PROTECTED:
        return positional[0], git_dir
    return None, None


def _is_linked_worktree(directory: str) -> bool:
    """directory 是否位於 linked worktree 內；git 失敗（無法判斷）時回傳 False。

    清掉繼承的 GIT_DIR 等變數：它們會蓋過 `git -C`（rule 17）。
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
    }
    try:
        res = subprocess.run(  # nosec B603 B607
            ["git", "-C", directory, "rev-parse", "--git-dir", "--git-common-dir"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    lines = res.stdout.splitlines()
    if res.returncode != 0 or len(lines) != 2:
        return False
    git_dir, common_dir = (os.path.realpath(os.path.join(directory, p)) for p in lines)
    return git_dir != common_dir


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
            _block(branch)
        sys.exit(0)

    if tool_name != "Bash":
        sys.exit(0)

    cmd = tool_input.get("command", "")
    if not isinstance(cmd, str):
        sys.exit(0)

    for part in re.split(r"&&|\|\||[;\n]", cmd):
        stripped = part.strip().lstrip("(").strip()
        try:
            tokens = shlex.split(stripped)
        except ValueError:
            tokens = stripped.split()

        # --- Vector 3: linked worktree 內 git checkout/switch main -------------
        target, git_dir = _checkout_target(tokens)
        if target is not None and _is_linked_worktree(git_dir or os.getcwd()):
            _block(target)

        # --- Vector 2: git worktree add ----------------------------------------
        if not re.match(r"git\s+worktree\s+add\b", stripped):
            continue

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
            _block(new_branch)

        if (
            new_branch is None
            and len(positional) >= 2
            and _normalize_ref(positional[-1]) in _PROTECTED
        ):
            _block(positional[-1])

    sys.exit(0)


if __name__ == "__main__":
    main()

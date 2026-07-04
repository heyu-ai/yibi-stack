---
name: protect-push
type: tool
scope: global
description: >
  Install a Claude Code PreToolUse hook to prevent direct git push from a worktree branch to
  origin/main. Applies to all projects using EnterWorktree or git worktree add.
  Trigger contexts: "install push protection", "configure worktree hook", "protect push",
  "new project initialization"
---

# protect-push

## Overview

This skill installs a PreToolUse hook in the target project's `.claude/` directory.
The hook automatically checks branch tracking before Claude executes any `git push`.

**Problem Statement**:

- Branches created by `EnterWorktree` or `git worktree add` track `origin/main` by default
- With `push.default=upstream`, any `git push` directly pushes to main, bypassing the PR workflow
- The `@{upstream}` syntax silently fails under zsh due to brace expansion;
  shell-level safety checks are unreliable

**Protection Mechanism**:

- Intercepts all `git push` commands in Bash
- Checks the upstream using `git config branch.X.remote` + `.merge`
  (no dependency on `@{upstream}` syntax)
- Blocks and displays a fix command if tracking points to `origin/main` or `origin/master`

## Execution Steps

### Step 1: Environment Check

Confirm you are in a git repo and `.claude/` exists:

```bash
git rev-parse --show-toplevel
[ -d .claude/ ] && echo "[OK] .claude/ 存在" || echo "[WARN] .claude/ 不存在，Step 2 會自動建立"
```

### Step 2: Run the Installer

Confirm the skill is installed, then run the install script (copies hook files,
creates or merges `settings.json`, and verifies — idempotent, safe to re-run):

```bash
SKILL_DIR="$HOME/.agents/skills/protect-push"
if [ ! -d "$SKILL_DIR" ]; then
    echo "[FAIL] protect-push skill 未安裝。請先在 yibi-stack 執行 make install-one SKILL=protect-push" >&2
    exit 1
fi
bash "$SKILL_DIR/scripts/install-hook.sh"
```

If the current cwd is not the target project (e.g. running from another directory),
pass the target repo root explicitly instead of `cd`-ing:

```bash
bash "$SKILL_DIR/scripts/install-hook.sh" /path/to/target-repo
```

The script exits non-zero with a `[FAIL]` message on any error
(not a git repo / skill files missing / settings.json corrupted).
It warns (`[WARN]`, stderr) when overwriting a `protect-push.sh` whose content differs
from the skill version — check `git diff` in the target repo if it may carry a customized hook.
On success the last line is `[DONE] 安裝完成！...`.

Implementation lives in `scripts/` (single source of truth — do not inline the
settings-merge logic here):

| Script | Responsibility |
|--------|----------------|
| `scripts/install-hook.sh` | Orchestrates: copy hook files → create-or-merge settings.json → verify |
| `scripts/merge-settings.py` | Owns the hook JSON definition; idempotent merge into `settings.json` |
| `scripts/verify-install.py` | Confirms the hook entry exists in `settings.json` |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `protect-push skill 未安裝` | Run `make install-one SKILL=protect-push` in the yibi-stack repo |
| Hook blocked a legitimate push | Run `git branch --unset-upstream && git push -u origin HEAD` to create a dedicated remote branch |
| settings.json format corrupted | Validate with `python3 -m json.tool .claude/settings.json` |
| Want to remove the hook | Delete the hook object from settings.json and remove `.claude/hooks/protect-push.sh` |

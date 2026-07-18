---
name: freeze
version: 0.1.0
description: Restrict file edits to a specific directory for the session, so the agent cannot touch unrelated code.
triggers:
  - freeze edits to directory
  - lock editing scope
  - restrict file changes
  - only edit this folder
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
hooks:
  PreToolUse:
    - matcher: "Edit"
      hooks:
        - type: command
          command: 'bash "$HOME/.claude/skills/freeze/hooks/check-freeze.sh"'
          statusMessage: "Checking freeze boundary..."
    - matcher: "Write"
      hooks:
        - type: command
          command: 'bash "$HOME/.claude/skills/freeze/hooks/check-freeze.sh"'
          statusMessage: "Checking freeze boundary..."
---
<!--
  Adapted from garrytan/gstack freeze skill (MIT, Copyright (c) 2026 Garry Tan);
  see LICENSE.gstack in this directory. Changes: boundary state lives under
  ~/.agents instead of ~/.gstack, hook path points at the global-install location
  for this skill, and gstack analytics writes are removed.
-->

## When to invoke this skill

Blocks Edit and Write outside an allowed directory. Use during debugging to
prevent accidentally "fixing" unrelated code, or any time you want to scope a
change to one module. Use when asked to "freeze", "restrict edits", "only edit
this folder", or "lock down edits". The `investigate` skill's Scope Lock phase
calls this after a root-cause hypothesis is formed.

# /freeze -- Restrict Edits to a Directory

Lock file edits to a specific directory. Any Edit or Write targeting a file
outside the allowed path is **blocked** (not just warned). The guard is inert
until you set a boundary, so installing this skill changes nothing until you run
`/freeze`.

## Setup

Ask the user which directory to restrict edits to. Use AskUserQuestion with a
text input (not multiple choice): "Which directory should I restrict edits to?
Files outside this path will be blocked from editing."

Once the user provides a directory path:

1. Resolve it to an absolute path:
   ```bash
   FREEZE_DIR=$(cd "<user-provided-path>" 2>/dev/null && pwd)
   echo "$FREEZE_DIR"
   ```

2. Ensure a trailing slash and save it to the boundary state file:
   ```bash
   FREEZE_DIR="${FREEZE_DIR%/}/"
   STATE_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.agents}"
   mkdir -p "$STATE_DIR"
   echo "$FREEZE_DIR" > "$STATE_DIR/freeze-dir.txt"
   echo "Freeze boundary set: $FREEZE_DIR"
   ```

Tell the user: "Edits are now restricted to `<path>/`. Any Edit or Write outside
this directory will be blocked. Run `/freeze` again to change the boundary, or
`/unfreeze` to remove it."

## How it works

The PreToolUse hook (`hooks/check-freeze.sh`) reads `file_path` from the Edit/Write
tool input and checks whether it starts with the freeze directory. If not, it
returns `permissionDecision: "deny"` and the edit is blocked. The boundary
persists for the session via `~/.agents/freeze-dir.txt`; the hook reads it on
every Edit/Write.

## Notes

- The trailing `/` on the boundary prevents `/src` from matching `/src-old`.
- Freeze applies to Edit and Write only. Read, Bash, Glob, Grep are unaffected.
- This prevents accidental edits, not a security boundary: Bash commands like
  `sed` can still modify files outside the boundary.
- To deactivate, run `/unfreeze` (or delete `~/.agents/freeze-dir.txt`).
- The state file is separate from gstack's own freeze (`~/.gstack/...`), so the
  two do not interfere if both are installed.

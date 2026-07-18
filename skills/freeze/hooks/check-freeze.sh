#!/usr/bin/env bash
# check-freeze.sh -- PreToolUse hook for the /freeze skill.
#
# Reads the Edit/Write tool-call JSON from stdin and checks whether file_path is
# inside the freeze boundary directory recorded by /freeze. Prints
# {"permissionDecision":"deny","message":"..."} to block, or {} to allow.
#
# Adapted from garrytan/gstack freeze/bin/check-freeze.sh (MIT, Copyright (c) 2026
# Garry Tan; see ../LICENSE.gstack). Changes from upstream: the boundary state
# lives under ~/.agents (this stack's agent home) instead of ~/.gstack, and the
# gstack analytics write on each deny is removed. Kept to bash 3.2 constructs
# (macOS ships bash 3.2; see .claude/rules/13-bash-anti-patterns.md AP4).
set -euo pipefail

INPUT=$(cat)

# Boundary state file. CLAUDE_PLUGIN_DATA when running as a plugin; otherwise the
# stack's agent home. Deliberately NOT ~/.gstack, so a co-installed gstack freeze
# does not share this one's boundary.
STATE_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.agents}"
FREEZE_FILE="$STATE_DIR/freeze-dir.txt"

# No boundary set -> allow everything (fail-open: the guard is inert until armed).
if [ ! -f "$FREEZE_FILE" ]; then
  echo '{}'
  exit 0
fi

FREEZE_DIR=$(tr -d '[:space:]' < "$FREEZE_FILE")
if [ -z "$FREEZE_DIR" ]; then
  echo '{}'
  exit 0
fi

# Extract file_path from the tool_input JSON. Try grep/sed, fall back to Python
# for escaped quotes.
FILE_PATH=$(printf '%s' "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//;s/"$//' || true)
if [ -z "$FILE_PATH" ]; then
  FILE_PATH=$(printf '%s' "$INPUT" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read()).get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)
fi

# Could not extract a path -> allow (do not block on a parse failure).
if [ -z "$FILE_PATH" ]; then
  echo '{}'
  exit 0
fi

# Resolve to absolute.
case "$FILE_PATH" in
  /*) ;;
  *) FILE_PATH="$(pwd)/$FILE_PATH" ;;
esac

# Normalize: collapse double slashes, drop trailing slash.
FILE_PATH=$(printf '%s' "$FILE_PATH" | sed 's|/\+|/|g;s|/$||')

# Resolve symlinks and .. (POSIX-portable, works on macOS bash 3.2).
_resolve_path() {
  local _dir _base
  _dir="$(dirname "$1")"
  _base="$(basename "$1")"
  _dir="$(cd "$_dir" 2>/dev/null && pwd -P || printf '%s' "$_dir")"
  printf '%s/%s' "$_dir" "$_base"
}
FILE_PATH=$(_resolve_path "$FILE_PATH")
FREEZE_DIR=$(_resolve_path "$FREEZE_DIR")

# Inside the boundary -> allow; outside -> deny.
case "$FILE_PATH" in
  "${FREEZE_DIR}/"*|"${FREEZE_DIR}")
    echo '{}'
    ;;
  *)
    printf '{"permissionDecision":"deny","message":"[freeze] Blocked: %s is outside the freeze boundary (%s). Only edits within the frozen directory are allowed. Run /unfreeze to lift it."}\n' "$FILE_PATH" "$FREEZE_DIR"
    ;;
esac

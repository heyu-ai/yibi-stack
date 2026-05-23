#!/usr/bin/env bash
# PreToolUse hook: pre-commit gate for staged files on git commit.
# Runs markdownlint on staged .md files and ruff format --check on staged .py files.
# Replaces markdownlint-pre-commit.sh.
set -euo pipefail

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null || true)

# Only fire on git commit commands
if ! printf '%s' "$cmd" | grep -qE '^git commit'; then
  exit 0
fi

# Skip in effort=low (rapid iteration mode).
# Note: this is the only mechanism that auto-blocks format violations before commit.
if [ "${CLAUDE_EFFORT:-normal}" = "low" ]; then
  echo "[SKIP] pre-commit gate skipped (CLAUDE_EFFORT=low)" >&2
  exit 0
fi

# ── markdownlint on staged .md files ─────────────────────────────────────
staged_md=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep '\.md$' || true)
if [ -n "$staged_md" ]; then
  echo "[pre-commit] markdownlint: checking staged .md files..."
  if ! printf '%s\n' "$staged_md" | tr '\n' '\0' | xargs -0 npx markdownlint-cli2 2>&1; then
    echo "[FAIL] markdownlint check failed -- fix violations before committing" >&2
    exit 2
  fi
  echo "[OK] markdownlint passed"
fi

# ── ruff format --check on staged .py files ──────────────────────────────
staged_py=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep '\.py$' || true)
if [ -n "$staged_py" ]; then
  echo "[pre-commit] ruff format: checking staged .py files..."
  if ! printf '%s\n' "$staged_py" | tr '\n' '\0' | xargs -0 ruff format --check 2>&1; then
    echo "[FAIL] ruff format check failed -- run: ruff format <files>" >&2
    exit 2
  fi
  echo "[OK] ruff format passed"
fi

exit 0

#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   scripts/install-rules-to-repo.sh <target-repo-path> [--copy|--symlink]
#
# Default mode: --symlink (points to yibi-stack rule files; single-machine only,
#               symlinks use absolute paths and break on clone or machine migration)
# --copy mode: copies current version (use when yibi-stack path may change, or for
#              external collaborators who can't rely on a local yibi-stack checkout)
#
# Only propagates generic rules:
#   13-bash-anti-patterns.md  -- AP1/AP2/AP3 + quoting hygiene
#   15-irreversible-operations.md
#   16-allowlist-hygiene.md
#
# yibi-stack-specific rules (04-11, scoped to tasks/**) are NOT propagated.

TARGET="${1:?usage: install-rules-to-repo.sh <target-repo> [--copy|--symlink]}"
MODE="${2:---symlink}"

if [ "$MODE" != "--copy" ] && [ "$MODE" != "--symlink" ]; then
    echo "[FAIL] unknown mode '$MODE': expected --copy or --symlink" >&2
    exit 1
fi

# Portable script-dir resolution: avoids realpath (unavailable on macOS < Ventura)
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
YIBI_RULES_DIR="$SCRIPT_DIR/../.claude/rules"
TARGET_RULES_DIR="$TARGET/.claude/rules"

if [ ! -d "$TARGET" ]; then
    echo "[FAIL] target repo not found: $TARGET" >&2
    exit 1
fi

if [ ! -d "$TARGET/.git" ] && [ ! -f "$TARGET/.git" ]; then
    echo "[FAIL] not a git repo (no .git): $TARGET" >&2
    exit 1
fi

mkdir -p "$TARGET_RULES_DIR"

for RULE in 13-bash-anti-patterns.md 15-irreversible-operations.md 16-allowlist-hygiene.md; do
    SRC="$YIBI_RULES_DIR/$RULE"
    DST="$TARGET_RULES_DIR/$RULE"

    if [ ! -f "$SRC" ]; then
        echo "[FAIL] source rule missing: $SRC" >&2
        exit 1
    fi

    if [ "$MODE" = "--copy" ]; then
        cp "$SRC" "$DST"
        echo "[OK] copied  $RULE"
    else
        ln -sfn "$SRC" "$DST"
        echo "[OK] linked  $RULE -> $SRC"
    fi
done

echo "[OK] 3 rules installed to $TARGET_RULES_DIR (mode=$MODE)"
echo ""
echo "Next steps for target repo:"
if [ "$MODE" = "--copy" ]; then
    echo "  1. git add .claude/rules/"
    echo "  2. Update target CLAUDE.md to document the rules installed in .claude/rules/"
else
    echo "  1. Add .claude/rules/*.md to .gitignore (symlinks use absolute paths, break on clone)"
    echo "  2. Update target CLAUDE.md to document the symlink-based rule install from yibi-stack"
fi

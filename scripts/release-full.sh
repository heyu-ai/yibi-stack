#!/usr/bin/env bash
set -euo pipefail

TYPE="${1:-}"
if [ -z "$TYPE" ]; then
    echo "[FAIL] Usage: make release TYPE=patch|minor|major" >&2
    exit 1
fi

BUMP_SH="$HOME/.claude/skills/bump-version/scripts/bump.sh"
CHANGELOG_SH="$HOME/.claude/skills/bump-version/scripts/changelog.sh"
GATES_SH="$HOME/.claude/skills/bump-version/scripts/gates.sh"
RELEASE_SH="$HOME/.claude/skills/bump-version/scripts/release.sh"

if [ ! -x "$BUMP_SH" ]; then
    echo "[FAIL] bump-version skill not installed." >&2
    echo "       Run: make install-one SKILL=bump-version" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
SYNC_SH="$REPO_ROOT/scripts/sync-plugin-versions.sh"

echo "=== Step 1: Bump $TYPE version ==="
"$BUMP_SH" "$TYPE"

ENV_FILE="/tmp/bump_version_result.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "[FAIL] bump.sh did not produce $ENV_FILE" >&2
    exit 1
fi
source "$ENV_FILE"
echo "  New version: $BUMP_VERSION (tag: $TAG_VERSION)"

echo ""
echo "=== Step 2: Sync plugin versions to $TAG_VERSION ==="
bash "$SYNC_SH" "$TAG_VERSION"

echo ""
echo "=== Step 3: Generate CHANGELOG ==="
"$CHANGELOG_SH" "$TAG_VERSION"

echo ""
echo "=== Step 4: Run test gates ==="
"$GATES_SH"

echo ""
echo "=== Step 5: Commit ==="
git add -A
git commit -m "chore(release): v${TAG_VERSION}"

echo ""
echo "=== Step 6: Tag + Release ==="
"$RELEASE_SH"

echo ""
echo "=== Release v${TAG_VERSION} complete ==="

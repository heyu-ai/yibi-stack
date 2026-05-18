#!/usr/bin/env bash
set -euo pipefail

TYPE="${1:-}"
if [ -z "$TYPE" ]; then
    echo "[FAIL] Usage: make release TYPE=patch|minor|major" >&2
    exit 1
fi

SKILL_DIR="$HOME/.claude/skills/bump-version/scripts"
BUMP_SH="$SKILL_DIR/bump.sh"
CHANGELOG_SH="$SKILL_DIR/changelog.sh"
GATES_SH="$SKILL_DIR/gates.sh"
RELEASE_SH="$SKILL_DIR/release.sh"

for script in "$BUMP_SH" "$CHANGELOG_SH" "$GATES_SH" "$RELEASE_SH"; do
    if [ ! -x "$script" ]; then
        echo "[FAIL] not executable: $script" >&2
        echo "       Run: make install-one SKILL=bump-version" >&2
        exit 1
    fi
done

REPO_ROOT=$(git rev-parse --show-toplevel)
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

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
cd "$REPO_ROOT"

if ! git diff --quiet HEAD || [ -n "$(git ls-files --others --exclude-standard)" ]; then
    echo "[FAIL] Working tree is dirty. Commit or stash changes before releasing." >&2
    exit 1
fi

rollback() {
    echo "[WARN] Release failed — reverting version files" >&2
    git checkout -- pyproject.toml CHANGELOG.md 2>/dev/null || true
    git checkout -- 'plugins/*/package.json' 2>/dev/null || true
}
trap rollback ERR

echo "=== Step 1: Bump $TYPE version ==="
ENV_FILE="/tmp/bump_version_result.env"
rm -f "$ENV_FILE"
"$BUMP_SH" "$TYPE"

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
trap - ERR
git add pyproject.toml CHANGELOG.md
git add plugins/*/package.json
git commit -m "chore(release): v${TAG_VERSION}"

echo ""
echo "=== Step 6: Tag + Release ==="
"$RELEASE_SH"

echo ""
echo "=== Release v${TAG_VERSION} complete ==="

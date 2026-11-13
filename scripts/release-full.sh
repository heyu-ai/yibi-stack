#!/usr/bin/env bash
set -euo pipefail

# 下面用 cd 取自己所在目錄；環境若設了 CDPATH，cd 會把目的地多印一行到 stdout，
# 讓 $(cd ... && pwd) 取到兩行（rule 17「Clear CDPATH before using cd」）。
export CDPATH=

TYPE="${1:-}"
if [ -z "$TYPE" ]; then
    echo "[FAIL] Usage: make release TYPE=patch|minor|major" >&2
    exit 1
fi

# 空 release 偵測（v1.13.0 事故）：release 流程原本不檢查「自上個 tag 以來有沒有
# 新 commit」，第二次 make release 在零新內容下照樣 bump -> gates -> tag，每一步都
# 「成功」，產出與前版零 diff 的空版本。上個 tag 到 HEAD 之間沒有任何 commit 就在
# 最前端拒絕；刻意重發同內容版本時用 FORCE=1 覆寫。放在 skill 檢查之前：fail fast，
# 也讓測試不依賴本機是否裝了 bump-version skill。
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [ -n "$LAST_TAG" ] && [ "${FORCE:-0}" != "1" ]; then
    NEW_COMMITS=$(git rev-list --count "${LAST_TAG}..HEAD")
    if [ "$NEW_COMMITS" -eq 0 ]; then
        echo "[FAIL] 自上個 tag（${LAST_TAG}）以來沒有任何新 commit -- 拒絕空 release" >&2
        echo "       確定要重發同內容版本時：FORCE=1 make release TYPE=${TYPE}" >&2
        exit 1
    fi
fi

# bump-version 由 dev-cycle plugin 提供。PR #627 之後 make install 不再把 plugin 提供的 skill 連到
# ~/.claude/skills/，所以預設值不能再指向 $HOME/.claude/skills/bump-version（乾淨安裝下不存在，
# make release 會一律 not executable）。改以本腳本自己的位置定位 repo 內的 plugin 原始碼。
# 本檔是一般檔案而非 symlink，用 dirname + cd -P + pwd 即可（rule 17 Self-Location）。
if ! SCRIPT_DIR=$(cd -P -- "$(dirname "${BASH_SOURCE[0]}")" && pwd); then
    echo "[FAIL] 無法解析 release-full.sh 所在目錄：${BASH_SOURCE[0]}" >&2
    exit 1
fi

# SKILL_DIR 可由環境覆寫：測試用它指向空目錄，讓流程停在下方的 executable 檢查，
# 不真的走進 bump/gates。正常使用不需要設定。
SKILL_DIR="${SKILL_DIR:-${SCRIPT_DIR}/../plugins/dev-cycle/skills/bump-version/scripts}"
BUMP_SH="$SKILL_DIR/bump.sh"
CHANGELOG_SH="$SKILL_DIR/changelog.sh"
GATES_SH="$SKILL_DIR/gates.sh"
RELEASE_SH="$SKILL_DIR/release.sh"

for script in "$BUMP_SH" "$CHANGELOG_SH" "$GATES_SH" "$RELEASE_SH"; do
    if [ ! -x "$script" ]; then
        echo "[FAIL] not executable: $script" >&2
        echo "       預設位置是本 repo 的 plugins/dev-cycle/skills/bump-version/scripts；" >&2
        echo "       若設了 SKILL_DIR 請確認該目錄下的腳本存在且可執行" >&2
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

git fetch origin main
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse origin/main)
if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "[FAIL] local main ($LOCAL_SHA) differs from origin/main ($REMOTE_SHA)" >&2
    echo "       Run: git pull --rebase origin main" >&2
    exit 1
fi

rollback() {
    echo "[WARN] Release failed — reverting version files" >&2
    git checkout -- pyproject.toml CHANGELOG.md 2>/dev/null || true
    # Both globs are required: sync_plugin_versions.py writes package.json AND
    # .claude-plugin/plugin.json (they are version-locked with no CI cross-check), and Step 5
    # git-adds both. Reverting only package.json left plugin.json carrying the bumped version
    # after a failed gate -- a half-rolled-back tree that looks clean at a glance.
    git checkout -- 'plugins/*/package.json' 2>/dev/null || true
    git checkout -- 'plugins/*/.claude-plugin/plugin.json' 2>/dev/null || true
    # gates.sh 內的 uv run 會依 bump 後的 pyproject.toml 改寫 uv.lock 的版本行；Step 5 會
    # commit 它，所以 gate 失敗時也要還原，否則下一次 make release 會被 dirty tree 擋下。
    # 開跑前已確認工作樹乾淨，這裡還原的只會是本次流程造成的改動。
    git checkout -- uv.lock 2>/dev/null || true
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
git add plugins/*/.claude-plugin/plugin.json
git diff --quiet uv.lock || git add uv.lock
git commit -m "chore(release): v${TAG_VERSION}"

echo ""
echo "=== Step 6: Tag + Release ==="
"$RELEASE_SH"

echo ""
echo "=== Release v${TAG_VERSION} complete ==="

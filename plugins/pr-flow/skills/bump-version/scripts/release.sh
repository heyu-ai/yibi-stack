#!/usr/bin/env bash
# release.sh — 完整 release orchestrator
# 用法：release.sh
# 前置條件：已執行 bump.sh + changelog.sh + commit（工作目錄乾淨）
# 步驟：git tag → push tag → gh release create → dispatch platform hook

set -euo pipefail

RESULT_ENV="/tmp/bump_version_result.env"
if [ ! -f "$RESULT_ENV" ]; then
  echo "[FAIL] 找不到 $RESULT_ENV，請先執行 bump.sh" >&2
  exit 1
fi

source "$RESULT_ENV"

case "${PROJECT_TYPE:-}" in
  flutter|python|nodejs|go) ;;
  *) echo "[FAIL] 無效的 PROJECT_TYPE: ${PROJECT_TYPE:-（空）}" >&2; exit 1 ;;
esac

CURRENT_REPO=$(git rev-parse --show-toplevel)
if [ "${REPO_ROOT:-}" != "$CURRENT_REPO" ]; then
  echo "[FAIL] 版本狀態屬於不同的 repo，請在此 repo 重新執行 bump.sh" >&2
  exit 1
fi

if [ "${GATES_PASSED:-false}" != "true" ] && [ "${SKIP_GATES:-false}" != "true" ]; then
  echo "[FAIL] 尚未執行 pre-release gate，請先執行：gates.sh" >&2
  echo "      緊急略過：gates.sh --skip-gates" >&2
  exit 1
fi

SCRIPT_DIR=$(dirname "$0")

# 0. 前置驗證（在任何 git 操作前完成）
if ! command -v gh > /dev/null 2>&1; then
  echo "[FAIL] 找不到 gh CLI，請先安裝並登入：https://cli.github.com" >&2
  exit 1
fi
if ! gh auth status > /dev/null 2>&1; then
  echo "[FAIL] gh CLI 未認證，請執行：gh auth login" >&2
  exit 1
fi

# 1. 確認工作目錄乾淨（含 untracked 檔案）
UNTRACKED=$(git ls-files --others --exclude-standard)
if ! git diff --quiet HEAD 2>/dev/null || [ -n "$UNTRACKED" ]; then
  echo "[FAIL] 工作目錄有未 commit 的變更或未追蹤的檔案，請先 commit" >&2
  exit 1
fi

# 2. 推送 branch commit（確保版號 commit 已在 remote），再推 tag
CURRENT_BRANCH=$(git branch --show-current)
git fetch origin "$CURRENT_BRANCH" --quiet 2>/dev/null || true
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/${CURRENT_BRANCH}" 2>/dev/null || echo "")
if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
  echo "[OK] 推送 branch commit：${CURRENT_BRANCH}"
  git push origin "$CURRENT_BRANCH"
fi

TAG="v${TAG_VERSION}"

if git tag --list | grep -qx "$TAG"; then
  echo "[FAIL] tag $TAG 已存在，請確認版本號" >&2
  exit 1
fi

git tag "$TAG"
git push origin "$TAG"
echo "[OK] tag 已推：$TAG（GitHub Actions CI 應已觸發）"

# 3. extract release notes
NOTES_FILE="/tmp/release_notes_${TAG_VERSION}.md"
SKIP_GATES_NOTE=""
if [ "${SKIP_GATES:-false}" = "true" ]; then
  SKIP_GATES_NOTE=$(printf '\n\n> [!WARNING]\n> Pre-release gates 已略過（--skip-gates）')
fi

if bash "${SCRIPT_DIR}/extract-notes.sh" "$TAG_VERSION" > "$NOTES_FILE" 2>/dev/null; then
  if [ -n "$SKIP_GATES_NOTE" ]; then
    printf '%s' "$SKIP_GATES_NOTE" >> "$NOTES_FILE"
  fi
  echo "[OK] release notes 已擷取：$NOTES_FILE"
else
  echo "[WARN] 無法從 CHANGELOG 擷取版本 $TAG_VERSION 的 notes，改用空白說明" >&2
  printf 'Release %s\n\nSee CHANGELOG.md for details.' "$TAG" > "$NOTES_FILE"
  if [ -n "$SKIP_GATES_NOTE" ]; then
    printf '%s' "$SKIP_GATES_NOTE" >> "$NOTES_FILE"
  fi
fi

# 4. gh release create
gh release create "$TAG" --title "$TAG" --notes-file "$NOTES_FILE"
echo "[OK] GitHub Release 已建立：$TAG"

# 5. dispatch platform hook
PLATFORM_SCRIPT="${SCRIPT_DIR}/platforms/${PROJECT_TYPE}.sh"
if [ -x "$PLATFORM_SCRIPT" ]; then
  echo "[OK] 執行 platform hook：platforms/${PROJECT_TYPE}.sh"
  bash "$PLATFORM_SCRIPT" || echo "[WARN] platform hook 執行失敗，但 GitHub Release 已建立"
else
  echo "[OK] 無 platform hook（${PROJECT_TYPE}），release 完成"
fi

echo ""
echo "=== Release 完成 ==="
echo "版本：${BUMP_VERSION}"
echo "Tag：${TAG}"
echo "GitHub Release：已建立"

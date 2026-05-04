#!/usr/bin/env bash
# changelog.sh — 生成 CHANGELOG
# 優先用 git-cliff，fallback 到 conventional commits git log 格式
# 用法：changelog.sh <new_version>

set -euo pipefail

NEW_VERSION="${1:?用法：changelog.sh <new_version>}"
CHANGELOG_FILE="CHANGELOG.md"

# ---------- 工具偵測 ----------

has_git_cliff() {
  command -v git-cliff &>/dev/null
}

has_cliff_config() {
  [ -f "cliff.toml" ] || [ -f ".cliff.toml" ]
}

# ---------- git-cliff 模式 ----------

run_git_cliff() {
  echo "[OK] 使用 git-cliff 生成 CHANGELOG..."
  if has_cliff_config; then
    git-cliff --tag "v${NEW_VERSION}" -o "$CHANGELOG_FILE"
  else
    git-cliff --tag "v${NEW_VERSION}" --config keepachangelog -o "$CHANGELOG_FILE"
  fi
}

# ---------- fallback：git log 過濾 conventional commits ----------

run_git_log_fallback() {
  echo "[OK] 使用 git log fallback 生成 CHANGELOG..."

  local latest_tag
  latest_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "")

  local log_range
  if [ -n "$latest_tag" ]; then
    log_range="${latest_tag}..HEAD"
  else
    log_range="HEAD"
  fi

  local date_str
  date_str=$(date +%Y-%m-%d)

  local tmpfile
  tmpfile=$(mktemp)
  trap 'rm -f "$tmpfile"' EXIT

  {
    echo "# CHANGELOG"
    echo ""
    echo "## [${NEW_VERSION}] - ${date_str}"
    echo ""

    local feats
    feats=$(git log "$log_range" --pretty=format:"%s" | grep -E "^feat(\(.+\))?:" || true)
    if [ -n "$feats" ]; then
      echo "### Features"
      echo ""
      echo "$feats" | sed 's/^feat[^:]*: /- /'
      echo ""
    fi

    local fixes
    fixes=$(git log "$log_range" --pretty=format:"%s" | grep -E "^fix(\(.+\))?:" || true)
    if [ -n "$fixes" ]; then
      echo "### Bug Fixes"
      echo ""
      echo "$fixes" | sed 's/^fix[^:]*: /- /'
      echo ""
    fi

    local breaking
    breaking=$(git log "$log_range" --pretty=format:"%s" | grep -iE "^[a-z]+(\(.+\))?!:" || true)
    if [ -n "$breaking" ]; then
      echo "### Breaking Changes"
      echo ""
      echo "$breaking" | sed 's/^/- /'
      echo ""
    fi

    # 附加舊 CHANGELOG 內容（跳過舊的 # CHANGELOG 標題行）
    if [ -f "$CHANGELOG_FILE" ]; then
      local first_line
      first_line=$(head -1 "$CHANGELOG_FILE")
      if echo "$first_line" | grep -qE "^# "; then
        tail -n +2 "$CHANGELOG_FILE"
      else
        cat "$CHANGELOG_FILE"
      fi
    fi
  } > "$tmpfile"

  mv "$tmpfile" "$CHANGELOG_FILE"
  trap - EXIT
}

# ---------- 主流程 ----------

if has_git_cliff; then
  if ! run_git_cliff; then
    echo "[WARN] git-cliff 執行失敗，改用 git log fallback" >&2
    run_git_log_fallback
  fi
else
  run_git_log_fallback
fi

echo "[OK] CHANGELOG 已更新：$CHANGELOG_FILE"

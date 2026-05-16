#!/usr/bin/env bash
# platforms/nodejs.sh — Node.js post-release hook（placeholder）
# npm publish 需手動確認後執行

set -euo pipefail

RESULT_ENV="/tmp/bump_version_result.env"
source "$RESULT_ENV"

echo "[INFO] Node.js 專案 post-release 提示"
echo ""
echo "若要發布到 npm，請確認後手動執行："
echo "  npm publish"
echo ""
echo "注意：npm publish 在 72 小時內可 unpublish，但之後為不可逆操作。"
echo "請確認版本號 v${TAG_VERSION} 正確、.npmignore 已設定。"

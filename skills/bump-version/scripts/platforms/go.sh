#!/usr/bin/env bash
# platforms/go.sh — Go post-release hook
# Go 版本由 git tag 管理，tag 已推即完成 release

set -euo pipefail

RESULT_ENV="/tmp/bump_version_result.env"
source "$RESULT_ENV"

echo "[OK] Go 專案：版本由 git tag 管理，tag v${TAG_VERSION} 已推送"
echo "      Go module proxy 將在數分鐘內索引此版本"
echo "      使用者可執行：go get your-module@v${TAG_VERSION}"

MAJOR=$(echo "$TAG_VERSION" | cut -d. -f1)
if [ "$MAJOR" -ge 2 ]; then
  echo ""
  echo "[WARN] Major version >= 2：請確認 go.mod 的 module 行已加 /v${MAJOR} 後綴"
  echo "       例：module github.com/org/repo/v${MAJOR}"
fi

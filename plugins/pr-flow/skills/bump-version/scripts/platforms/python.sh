#!/usr/bin/env bash
# platforms/python.sh — Python post-release hook（placeholder）
# PyPI 發布需手動確認後執行

set -euo pipefail

RESULT_ENV="/tmp/bump_version_result.env"
source "$RESULT_ENV"

echo "[INFO] Python 專案 post-release 提示"
echo ""
echo "若要發布到 PyPI，請確認後手動執行："
echo "  uv build"
echo "  uv publish"
echo ""
echo "或使用 twine："
echo "  python -m build"
echo "  twine upload dist/*"
echo ""
echo "注意：PyPI 發布為不可逆操作，請確認版本號 v${TAG_VERSION} 正確。"

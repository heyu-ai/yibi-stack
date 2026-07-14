#!/usr/bin/env bash
# platforms/python.sh — Python post-release hook（placeholder）
# 僅在專案本身是可發布的 PyPI 套件（pyproject.toml 含 [build-system]）時才印 PyPI 提示。
# 純 skill/plugin 型 repo（透過 make install / plugin marketplace 發布）不含 [build-system]，略過提示。

set -euo pipefail

RESULT_ENV="/tmp/bump_version_result.env"
source "$RESULT_ENV"

# VERSION_FILE 由 bump.sh 寫入；Python 專案為 pyproject.toml。保險起見 fallback 到 ./pyproject.toml。
PYPROJECT="${VERSION_FILE:-pyproject.toml}"
if [ ! -f "$PYPROJECT" ]; then
  PYPROJECT="pyproject.toml"
fi

if [ ! -f "$PYPROJECT" ] || ! grep -q '^\[build-system\]' "$PYPROJECT"; then
  echo "[INFO] ${PYPROJECT} 無 [build-system]，此專案非 PyPI 套件，略過 PyPI 發布提示。"
  echo "       （skill/plugin 型 repo 透過 make install / plugin marketplace 發布，git tag + GitHub Release 即完成發布。）"
  exit 0
fi

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

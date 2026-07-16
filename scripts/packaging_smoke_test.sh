#!/usr/bin/env bash
# Packaging smoke test：證明 wheel 在「沒有任何 yibi-stack checkout」的環境可獨立運作。
#
# 為何需要（ADR-0004 / PR #249 mob review 三家共識）：
# Phase 1 的全部價值是「portman 能從 wheel 安裝並執行」。所有 pytest 都是
# `from tasks.<mod>.cli import cli` 直接 import——entry point 打錯、packages 寫錯、
# exclude 過寬，測試全數照綠，缺陷先在使用者的 `uv tool install` 現場爆而非 CI。
#
# 為何是 CI 步驟而非 pytest：pyproject 的 addopts = "-m 'not slow'" 連 CI 都 deselect，
# 所以 @pytest.mark.slow 的測試永遠不會執行（= 測試沒接上 CI = 半成品）。快速的
# entry-point 解析檢查另由 scripts/tests/test_packaging.py 涵蓋（每次 pytest 都跑）；
# 本腳本負責它涵蓋不到的部分：wheel 內容、依賴完整性、entry point metadata、實際執行。
set -euo pipefail

REPO_ROOT=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "=== 1. 建置 wheel ==="
uv build --wheel --out-dir "$WORK/dist" --directory "$REPO_ROOT"

shopt -s nullglob
WHEELS=( "$WORK"/dist/*.whl )
shopt -u nullglob
if [ "${#WHEELS[@]}" -ne 1 ]; then
    echo "[FAIL] 預期剛好 1 個 wheel，實得 ${#WHEELS[@]} 個" >&2
    exit 1
fi
WHEEL="${WHEELS[0]}"
echo "[OK] $(basename "$WHEEL")"

echo "=== 2. 驗證 wheel 內容範圍 ==="
python3 "$REPO_ROOT/scripts/check_wheel_contents.py" "$WHEEL"

echo "=== 3. 安裝到隔離 venv（不碰全域 ~/.local/bin）==="
uv venv "$WORK/venv" --quiet
uv pip install --quiet --python "$WORK/venv/bin/python" "$WHEEL"

echo "=== 4. 確認前提：驗證目錄不得含 checkout 痕跡 ==="
for marker in tasks pyproject.toml .git; do
    if [ -e "$WORK/$marker" ]; then
        echo "[FAIL] 驗證目錄含 $marker，「無 checkout」前提不成立" >&2
        exit 1
    fi
done
echo "[OK] $WORK 無 tasks/ / pyproject.toml / .git"

echo "=== 5. 從非 checkout 的 cwd 執行 portman ==="
PORTMAN="$WORK/venv/bin/portman"
if [ ! -x "$PORTMAN" ]; then
    echo "[FAIL] wheel 未產生可執行的 portman entry point" >&2
    exit 1
fi
( cd "$WORK" && "$PORTMAN" --version )
( cd "$WORK" && "$PORTMAN" --help > /dev/null )
echo "[OK] portman --version / --help 可執行"

echo "=== 6. 反證：tasks 必須載自 site-packages，而非某個 checkout ==="
( cd "$WORK" && "$WORK/venv/bin/python" "$REPO_ROOT/scripts/assert_import_from_site_packages.py" )

echo "[OK] packaging smoke test 通過：wheel 在無 checkout 環境可獨立運作"

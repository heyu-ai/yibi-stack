#!/usr/bin/env bash
# probe-agy-sandbox.sh — 驗證 agy sandbox 行為是否跟 pr-cycle-deep 腳本的假設一致
#
# 三項 probe：
#   1. sandbox-file-read：--sandbox + --add-dir 絕對路徑能讀檔
#   2. sandbox-command-deny：--sandbox 下 command 工具被 auto-deny（headless）
#   3. bypass-full-access：權限繞過旗標下 file read + command 都放行
#
# 用法：bash scripts/probe-agy-sandbox.sh
#       make probe-agy
#
# 需要 agy auth；無 auth 時每項 probe 印 [SKIP] 並 exit 0。
# 設計為 agy 升級時手動跑，非 CI 自動化。
#
# 退出碼：0 全 PASS 或全 SKIP；1 任一 FAIL。

set -euo pipefail

PROBE_FAIL=0

if ! command -v agy >/dev/null 2>&1; then
    echo "[SKIP] agy 未安裝" >&2
    exit 0
fi

AGY_VER=$(agy --version 2>/dev/null || echo "unknown")

ONBOARDING_FILE="$HOME/.gemini/antigravity-cli/cache/onboarding.json"
if [ ! -f "$ONBOARDING_FILE" ]; then
    echo "[SKIP] agy 未認證（${ONBOARDING_FILE} 不存在）-- 跳過所有 probe (agy ${AGY_VER})" >&2
    exit 0
fi

if ! python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('onboardingComplete') else 1)" "$ONBOARDING_FILE" 2>/dev/null; then
    echo "[SKIP] agy 未完成認證（onboardingComplete != true）-- 跳過所有 probe (agy ${AGY_VER})" >&2
    exit 0
fi

PROBE_DIR=$(mktemp -d)
trap 'rm -rf "$PROBE_DIR"' EXIT

echo "seed content for probe" > "${PROBE_DIR}/probe-file.txt"

echo "--- Probe 1: sandbox-file-read (agy ${AGY_VER}) ---"
PROBE1_OUT=$(agy -p "Read the file probe-file.txt and reply with its exact content. Nothing else." \
    --add-dir "${PROBE_DIR}" \
    --sandbox \
    --print-timeout 2m 2>/dev/null || true)
if echo "$PROBE1_OUT" | grep -q "seed content for probe"; then
    echo "[PASS] sandbox-file-read (agy ${AGY_VER})"
else
    echo "[FAIL] sandbox-file-read (agy ${AGY_VER}) -- --sandbox + --add-dir 無法讀檔" >&2
    PROBE_FAIL=1
fi

echo "--- Probe 2: sandbox-command-deny (agy ${AGY_VER}) ---"
PROBE2_OUT=$(agy -p "Run the shell command: echo PROBE_COMMAND_EXECUTED" \
    --add-dir "${PROBE_DIR}" \
    --sandbox \
    --print-timeout 2m 2>/dev/null || true)
if echo "$PROBE2_OUT" | grep -q "PROBE_COMMAND_EXECUTED"; then
    echo "[FAIL] sandbox-command-deny (agy ${AGY_VER}) -- --sandbox 下 command 未被 auto-deny（假設已失效，可考慮改回 --sandbox）" >&2
    PROBE_FAIL=1
else
    echo "[PASS] sandbox-command-deny (agy ${AGY_VER}) -- command 仍被 auto-deny（假設成立）"
fi

echo "--- Probe 3: bypass-full-access (agy ${AGY_VER}) ---"
PROBE3_OUT=$(agy -p "Read probe-file.txt and also run: echo BYPASS_COMMAND_OK" \
    --add-dir "${PROBE_DIR}" \
    --dangerously-skip-permissions \
    --print-timeout 2m 2>/dev/null || true)
if [ -n "$PROBE3_OUT" ]; then
    echo "[PASS] bypass-full-access (agy ${AGY_VER})"
else
    echo "[FAIL] bypass-full-access (agy ${AGY_VER}) -- 權限繞過旗標下輸出為空" >&2
    PROBE_FAIL=1
fi

echo "---"
if [ "$PROBE_FAIL" -eq 0 ]; then
    echo "All probes passed (agy ${AGY_VER})"
else
    echo "Some probes FAILED (agy ${AGY_VER}) -- 請檢查 agy sandbox 行為是否已改變" >&2
fi
exit "$PROBE_FAIL"

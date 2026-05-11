#!/usr/bin/env bash
# gates.sh — pre-release test gate dispatcher
# 用法：gates.sh [--skip-gates]
# 依 /tmp/bump_version_result.env 的 PROJECT_TYPE 呼叫對應 gate script
# 所有 gate script 失敗時以 exit 1 中斷 release

set -euo pipefail

SKIP_GATES=false
[[ "${1:-}" == "--skip-gates" ]] && SKIP_GATES=true

RESULT_ENV="/tmp/bump_version_result.env"

if [ "$SKIP_GATES" = "true" ]; then
  echo "[WARN] --skip-gates 已設定，跳過 pre-release 測試"
  if [ -f "$RESULT_ENV" ]; then
    printf 'SKIP_GATES=true\n' >> "$RESULT_ENV"
  fi
  exit 0
fi

if [ ! -f "$RESULT_ENV" ]; then
  echo "[FAIL] 找不到 $RESULT_ENV，請先執行 bump.sh" >&2
  exit 1
fi

source "$RESULT_ENV"

case "${PROJECT_TYPE:-}" in
  flutter|python|nodejs|go) ;;
  *) echo "[FAIL] 無效的 PROJECT_TYPE: ${PROJECT_TYPE:-（空）}" >&2; exit 1 ;;
esac

SCRIPT_DIR=$(dirname "$0")
GATE_SCRIPT="${SCRIPT_DIR}/gates/${PROJECT_TYPE}.sh"
if [ ! -x "$GATE_SCRIPT" ]; then
  echo "[WARN] 無 gate script：$GATE_SCRIPT，跳過測試"
  exit 0
fi

echo "[OK] 執行 pre-release gate：$GATE_SCRIPT"
bash "$GATE_SCRIPT"
printf 'GATES_PASSED=true\n' >> "$RESULT_ENV"
echo "[OK] pre-release gate 通過"

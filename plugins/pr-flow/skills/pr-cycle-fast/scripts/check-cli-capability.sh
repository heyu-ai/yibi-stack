#!/usr/bin/env bash
# pr-cycle-fast/scripts/check-cli-capability.sh
# 探測已安裝的 pr-orchestrator 是否具備「本 skill 實際會呼叫的介面」，而非只檢查它存在。
#
# 為什麼不比對版本號：`uv tool install git+...` 裝的是 HEAD，但版本字串取自上次 release 的
# pyproject.toml，兩次 release 之間所有 commit 回報同一字串，故 semver 比對無法區分
# 「沒有漂移」與「偵測不到漂移」（見 issue #256 / PR #249 的收斂結論）。能力探測不需要版本號。
#
# 用法：check-cli-capability.sh
# stdout: [OK] 說明
# stderr: [FAIL] 說明
# exit 0: 介面齊備
# exit 1: 找不到 pr-orchestrator（未安裝或不在 PATH）
# exit 2: 已安裝但介面過舊 / 無法執行 --help（兩者訊息不同，見下方）

set -euo pipefail

# 與 SKILL.md 中實際帶 --repo-root 的子指令一致；
# scripts/tests/test_pr_cycle_fast_capability.py 會斷言兩者不漂移。
SUBCOMMANDS=(detect resume status transition write-manifest log-view auto-fix)

INSTALL_CMD='uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"'
UPGRADE_CMD='uv tool install --force "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"'

if ! command -v pr-orchestrator >/dev/null 2>&1; then
  echo "[FAIL] 缺少 pr-orchestrator，請執行：${INSTALL_CMD}" >&2
  exit 1
fi

MISSING=()

for sub in "${SUBCOMMANDS[@]}"; do
  # 分辨「跑不起來」與「跑得起來但沒有這個 flag」——前者不可當成後者，否則
  # 一個壞掉的安裝會被誤報成「版本過舊」，把使用者導向錯誤的修法。
  if ! HELP_TEXT=$(pr-orchestrator "${sub}" --help 2>&1); then
    echo "[FAIL] pr-orchestrator ${sub} --help 無法執行，安裝可能損毀：" >&2
    echo "${HELP_TEXT}" >&2
    echo "       重裝：${UPGRADE_CMD}" >&2
    exit 2
  fi
  case "${HELP_TEXT}" in
    *--repo-root*) ;;
    *) MISSING+=("${sub}") ;;
  esac
done

if [ "${#MISSING[@]}" -gt 0 ]; then
  echo "[FAIL] 已安裝的 pr-orchestrator 缺少 --repo-root，子指令：${MISSING[*]}" >&2
  echo "       本 skill 每個步驟都以 --repo-root 指定目標 repo；缺少它會在 workflow" >&2
  echo "       跑到一半才以 exit 2 浮現（issue #333）。" >&2
  echo "       請升級：${UPGRADE_CMD}" >&2
  exit 2
fi

echo "[OK] pr-orchestrator 介面檢查通過（${#SUBCOMMANDS[@]} 個子指令皆支援 --repo-root）"

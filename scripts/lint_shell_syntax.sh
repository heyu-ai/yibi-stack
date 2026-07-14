#!/usr/bin/env bash
# 對 pre-commit 傳入的每個 shell 檔跑 `bash -n`（純語法檢查，不執行）。
#
# 為何需要：pre-commit 原本只有 lint-skill-bash，且它的 files: 只涵蓋 .md
# （markdown 內的 bash 區塊）。真正的 shell 腳本（.sh 與 scripts/lessons 這類
# 無副檔名但有 bash shebang 的檔案）從未做過語法檢查，於是「腳本壓根無法啟動」
# 這種最基本的錯誤可以一路通過 make ci 與 GitHub CI。
# 實例（PR #224）：一次批次改寫在 commands/scripts/handover-read.sh 與
# scripts/lessons 留下孤兒 `fi`，兩支腳本 100% 無法執行，CI 全綠，
# 由跨模型 mob review 才抓到。
#
# 用法：pre-commit 以 types: [shell] 挑檔並附加檔名參數。
# exit 0: 全部通過；exit 1: 至少一個檔語法錯誤（訊息在 stderr）。
set -uo pipefail

RC=0
for f in "$@"; do
  if ! ERR=$(bash -n "$f" 2>&1); then
    echo "[FAIL] shell 語法錯誤：$f" >&2
    echo "$ERR" >&2
    RC=1
  fi
done

exit "$RC"

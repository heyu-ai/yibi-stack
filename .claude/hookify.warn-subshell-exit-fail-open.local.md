---
name: warn-subshell-exit-fail-open
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: "\\.sh$"
  - field: new_text
    operator: regex_match
    pattern: "=\\$\\(_\\w+"
  - field: new_text
    operator: regex_match
    pattern: "\\n\\s+exit\\s+\\d"
action: warn
---

# `$()` 呼叫的 function 裡不要用 exit

這個檔案同時有「用 `$()` 呼叫本地 helper（`_` 開頭）」與「縮排的 `exit`」。
若那個 `exit` 落在被 `$()` 呼叫的 function 內，它**只會結束 subshell，不會結束腳本**：

```bash
_helper() {
  if [ "$bad" ]; then
    exit 1            # 只殺掉 subshell
  fi
}
if X=$(_helper); then   # if 讓 set -e 不觸發
  ...
fi
exit 0                  # <-- 實際走到這裡：靜默放行
```

呼叫端只看到非零回傳，會把「無法判定」當成「沒找到」而落到放行路徑。

**正確寫法**：function 用 return code 表達狀態，呼叫端逐一分辨。

```bash
_helper() {
  ...
  return 2              # 0=找到 / 1=沒找到 / 2=無法判定
}
RC=0
X=$(_helper) || RC=$?
if [ "$RC" -eq 2 ]; then
  echo "[FAIL] 無法判定，拒絕繼續" >&2
  exit 1
fi
```

**不是每個 `exit` 都有問題**——被直接呼叫的 function（`die "msg"`）用 `exit` 完全正常；
裸賦值 + `set -e`（`X=$(fn)`）也會被 `set -e` 接住。真正 fail-open 的是
「呼叫點被 `if` / `||` / `&&` 包住」或「腳本沒有 `set -e`」。

`scripts/lint_shell_subshell_exit.py` 會在 commit 時做精確判定（它 parse function
邊界與呼叫點，0 誤報）。本提醒只是寫 code 當下的粗略前哨，會在這個檔案已經寫對時
也出現——**確認過就繼續**。

**Source**: PR #234。三個 review voice（Claude / codex / agy）都沒抓到，是突變測試抓到的：
深度上限「保險」自己就是 fail-open，實測印出了 `[FAIL]` 卻仍 `exit 0`，
還連帶讓一條測試變成假測試（兩個 bug 互相抵銷）。詳見 `.claude/rules/11-skill-authoring.md`。

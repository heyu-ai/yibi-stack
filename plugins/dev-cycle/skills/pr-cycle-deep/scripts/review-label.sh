#!/usr/bin/env bash
# 在 review 期間替 PR 貼／撤 `review-in-progress` label（issue #587）。
#   bash review-label.sh add <pr-number>      貼 label，回讀確認
#   bash review-label.sh remove <pr-number>   撤 label，回讀確認
# Exit 0:  已回讀確認（add：label 在；remove：label 不在，含「本來就沒有」）。
# Exit 1:  用法錯誤、工具／API 不可用、gh 非零退出、label metadata 格式不符、回讀狀態不符。
# label 名稱比對不分大小寫（GitHub 的 label 名稱本來就不分），但必須整字相等。
# Exit 10: 僅 add——repo 沒有這個 label，只 [WARN]，呼叫端照常繼續（不阻擋其他專案）。
# 失效方向是 fail-closed：撤失敗會讓 merge 繼續被擋，需人工移除；這是可接受的方向。

set -euo pipefail

LABEL="review-in-progress"

fail() {
    echo "[FAIL] $*" >&2
    exit 1
}

if [ "$#" -ne 2 ]; then
    fail "Usage: bash review-label.sh <add|remove> <pr-number>"
fi
ACTION="$1"
PR_NUMBER="$2"
case "$ACTION" in
    add | remove) ;;
    *) fail "Unknown action: ${ACTION} (expected add or remove)" ;;
esac
if ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]; then
    fail "PR number must be a positive integer"
fi
for tool in gh jq; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required tool unavailable: ${tool}"
done

# 回傳 PR 目前是否掛著 label；讀取失敗或格式不符一律 [FAIL]，不當成「沒有」。
pr_has_label() {
    local json
    if ! json=$(gh pr view "$PR_NUMBER" --json labels); then
        fail "gh pr view failed for PR #${PR_NUMBER}; cannot confirm label state"
    fi
    if ! jq -e '.labels | type == "array"' <<< "$json" >/dev/null; then
        fail "PR #${PR_NUMBER} returned malformed label metadata"
    fi
    # GitHub 的 label 名稱不分大小寫，兩邊都轉小寫再比；仍是整字相等，不是 contains。
    jq -e --arg name "$LABEL" 'any(.labels[]; ((.name // "") | ascii_downcase) == ($name | ascii_downcase))' <<< "$json" >/dev/null
}

if [ "$ACTION" = add ]; then
    if ! LABELS_JSON=$(gh label list --search "$LABEL" --limit 100 --json name); then
        fail "gh label list failed; cannot tell whether this repo defines ${LABEL}"
    fi
    if ! jq -e 'type == "array"' <<< "$LABELS_JSON" >/dev/null; then
        fail "gh label list returned malformed metadata; cannot tell whether this repo defines ${LABEL}"
    fi
    if ! jq -e --arg name "$LABEL" 'any(.[]; ((.name // "") | ascii_downcase) == ($name | ascii_downcase))' <<< "$LABELS_JSON" >/dev/null; then
        echo "[WARN] repo has no '${LABEL}' label; no merge blocking for this review. State this in the Step 8 summary." >&2
        exit 10
    fi
    if ! gh pr edit "$PR_NUMBER" --add-label "$LABEL" >/dev/null; then
        fail "gh pr edit --add-label failed for PR #${PR_NUMBER}"
    fi
    if ! pr_has_label; then
        fail "'${LABEL}' not on PR #${PR_NUMBER} after add (read-back mismatch)"
    fi
    echo "[OK] PR #${PR_NUMBER} has '${LABEL}'"
    exit 0
fi

# remove：先讀；本來就沒有就不呼叫 edit（沒有此 label 的 repo 也走這條，不會誤報錯）。
if pr_has_label; then
    if ! gh pr edit "$PR_NUMBER" --remove-label "$LABEL" >/dev/null; then
        fail "gh pr edit --remove-label failed for PR #${PR_NUMBER}; remove it by hand"
    fi
    if pr_has_label; then
        fail "'${LABEL}' still on PR #${PR_NUMBER} after remove (read-back mismatch); remove it by hand"
    fi
    echo "[OK] PR #${PR_NUMBER} no longer has '${LABEL}'"
else
    echo "[OK] PR #${PR_NUMBER} does not have '${LABEL}'"
fi

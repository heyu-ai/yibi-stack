#!/bin/bash
# bash-hygiene audit functions for bash-ap1-inline-check.sh.
# Source at hook top:  source "$(dirname "$0")/_audit_log.sh"
# Then call:          audit_block "reason-slug" "rule_id"  or  audit_allow
#
# ── 只記 block，不記 allow（PR #262）──
# 每次放行都寫一筆 330 bytes，只為了記錄「什麼都沒發生」。實測 2026-07-17：
# 94.3 MB / 299,280 筆 / 39 天，其中 94.84% 是 allow。`audit_allow` 因此成為 no-op，
# 但**保留這個函式**：呼叫端（bash-ap1-inline-check.sh）不必改，且未來要恢復也只需動這裡。
#
# ── 每日輪替、保留 N 天（PR #262）──
# 檔名帶日期，寫入時順手清掉過期的。**不綁定消費端**——nightly-agent 實測可以連 4 晚
# 啟動即死無人察覺（PR #261），把生命週期綁在它身上，結果就是 39 天沒人清過這個 log。
#
# 這兩個行為必須與 _audit_log.py 一致：兩支檔案是同一個 log 的兩個寫入端，
# 改一邊沒改另一邊，log 就會半新半舊（Python hook 只記 block、bash hook 照記 allow）。

_AUDIT_CHECKED=""
_AUDIT_ENABLED="no"
_AUDIT_RETENTION_DAYS=30
_AUDIT_LOG_STEM="bash-hygiene-audit"

_audit_check() {
    [ -n "$_AUDIT_CHECKED" ] && return 0
    _AUDIT_CHECKED="yes"
    grep -q '"audit_enabled"[[:space:]]*:[[:space:]]*true' \
        "$HOME/.agents/bash-hygiene.json" 2>/dev/null && _AUDIT_ENABLED="yes"
    return 0
}

_audit_log_dir() {
    local git_common_dir root
    git_common_dir=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
    root=$(dirname "$git_common_dir")
    mkdir -p "$root/.runtime/logs" 2>/dev/null || return 1
    printf '%s' "$root/.runtime/logs"
}

_audit_log_path() {
    local dir
    dir=$(_audit_log_dir) || return 1
    printf '%s/%s-%s.jsonl' "$dir" "$_AUDIT_LOG_STEM" "$(date -u +%Y-%m-%d)"
}

# 刪掉超過保留天數的每日 log。日期從**檔名**解析，不看 mtime——mtime 會被 cp -p /
# rsync / 備份還原改掉，檔名才是這個檔案自己宣告的歸屬日。
# 解析不出日期的檔案一律不動：寧可留著也不誤刪。
_audit_prune() {
    local dir cutoff f stamp
    dir=$(_audit_log_dir) || return 0
    # BSD date（macOS）與 GNU date 的相對日期語法不同，兩個都試；都失敗就放棄清理。
    cutoff=$(date -u -v-"${_AUDIT_RETENTION_DAYS}"d +%Y-%m-%d 2>/dev/null) \
        || cutoff=$(date -u -d "${_AUDIT_RETENTION_DAYS} days ago" +%Y-%m-%d 2>/dev/null) \
        || return 0
    shopt -s nullglob
    for f in "$dir/$_AUDIT_LOG_STEM"-*.jsonl; do
        stamp=$(basename "$f" .jsonl)
        stamp=${stamp#"$_AUDIT_LOG_STEM"-}
        # 只認 YYYY-MM-DD；不符的不是我們產的，別碰
        case "$stamp" in
            [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
            *) continue ;;
        esac
        # ISO 日期可直接字串比大小
        if [[ "$stamp" < "$cutoff" ]]; then
            rm -f "$f" 2>/dev/null || true
        fi
    done
    shopt -u nullglob
    return 0
}

_audit_write() {
    # $1 = verdict (allow|block)  $2 = block_reason (empty string if allow)
    # $3 = command string (optional; defaults to $CMD from caller's scope)
    # $4 = rule_id (optional; rule file number, e.g. "13")
    _audit_check
    [ "$_AUDIT_ENABLED" = "yes" ] || return 0
    # 只記非 allow（見檔頭）。這是 audit_allow 變成 no-op 的實際所在。
    [ "$1" = "allow" ] && return 0
    command -v jq >/dev/null 2>&1 || return 0
    local log_path
    log_path=$(_audit_log_path) || return 0
    _audit_prune
    local ts cmd_src cmd_snippet cmd_hash exit_code record
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    cmd_src="${3:-${CMD:-}}"
    cmd_snippet="${cmd_src:0:200}"
    cmd_hash=$(printf '%s' "$cmd_src" | shasum -a 256 2>/dev/null | cut -c1-16) || cmd_hash=""
    if [ "$1" = "block" ]; then exit_code=2; else exit_code=0; fi
    record=$(jq -c -n \
        --arg ts "$ts" \
        --arg hook "${AUDIT_HOOK:-ap1}" \
        --arg ver "2" \
        --arg verdict "$1" \
        --argjson code "$exit_code" \
        --arg reason "${2:-}" \
        --arg cmd_snippet "$cmd_snippet" \
        --arg hash "${cmd_hash:-}" \
        --arg sid "${CLAUDE_SESSION_ID:-}" \
        --arg rid "${4:-}" \
        '{ts:$ts,hook:$hook,hook_version:$ver,exit_code:$code,verdict:$verdict,
          block_reason:(if $reason=="" then null else $reason end),
          rule_id:$rid,
          cmd_snippet:$cmd_snippet,command_hash:$hash,
          session_id:(if $sid=="" then null else $sid end)}' 2>/dev/null) || return 0
    {
        if command -v flock >/dev/null 2>&1; then
            flock -x 9
        fi
        printf '%s\n' "$record" >> "$log_path"
    } 9>>"$log_path"
    return 0
}

audit_allow() { _audit_write "allow" "" "${CMD:-}" "" || true; }
audit_block() { _audit_write "block" "${1:-}" "${CMD:-}" "${2:-}" || true; }

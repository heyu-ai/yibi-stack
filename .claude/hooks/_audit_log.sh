#!/bin/bash
# bash-hygiene audit functions for bash-ap1-inline-check.sh.
# Source at hook top:  source "$(dirname "$0")/_audit_log.sh"
# Then call:          audit_block "reason-slug"  or  audit_allow

_AUDIT_CHECKED=""
_AUDIT_ENABLED="no"

_audit_check() {
    [ -n "$_AUDIT_CHECKED" ] && return 0
    _AUDIT_CHECKED="yes"
    grep -q '"audit_enabled"[[:space:]]*:[[:space:]]*true' \
        "$HOME/.agents/bash-hygiene.json" 2>/dev/null && _AUDIT_ENABLED="yes"
    return 0
}

_audit_log_path() {
    local root
    root=$(git rev-parse --show-toplevel 2>/dev/null) || return 1
    mkdir -p "$root/.runtime/logs" 2>/dev/null || return 1
    printf '%s' "$root/.runtime/logs/bash-hygiene-audit.jsonl"
}

_audit_write() {
    # $1 = verdict (allow|block)  $2 = block_reason (empty string if allow)
    # $3 = command string (optional; defaults to $CMD from caller's scope)
    _audit_check
    [ "$_AUDIT_ENABLED" = "yes" ] || return 0
    command -v jq >/dev/null 2>&1 || return 0
    local log_path
    log_path=$(_audit_log_path) || return 0
    local ts cmd_src cmd_preview cmd_hash exit_code record
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    cmd_src="${3:-${CMD:-}}"
    cmd_preview="${cmd_src:0:200}"
    cmd_hash=$(printf '%s' "$cmd_src" | shasum -a 256 2>/dev/null | cut -c1-16) || cmd_hash=""
    if [ "$1" = "block" ]; then exit_code=2; else exit_code=0; fi
    record=$(jq -c -n \
        --arg ts "$ts" \
        --arg hook "${AUDIT_HOOK:-ap1}" \
        --arg ver "1" \
        --arg verdict "$1" \
        --argjson code "$exit_code" \
        --arg reason "${2:-}" \
        --arg preview "$cmd_preview" \
        --arg hash "${cmd_hash:-}" \
        --arg sid "${CLAUDE_SESSION_ID:-}" \
        '{ts:$ts,hook:$hook,hook_version:$ver,exit_code:$code,verdict:$verdict,
          block_reason:(if $reason=="" then null else $reason end),
          command_preview:$preview,command_hash:$hash,
          session_id:(if $sid=="" then null else $sid end)}' 2>/dev/null) || return 0
    {
        if command -v flock >/dev/null 2>&1; then
            flock -x 9
        fi
        printf '%s\n' "$record" >> "$log_path"
    } 9>>"$log_path"
    return 0
}

audit_allow() { _audit_write "allow" "" "${CMD:-}" || true; }
audit_block() { _audit_write "block" "${1:-}" "${CMD:-}" || true; }

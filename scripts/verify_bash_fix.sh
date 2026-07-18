#!/bin/bash
# verify_bash_fix.sh — 三層驗證：L1 lint / L2 hook dry-run / L3 pytest regression
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel) || { echo "[FAIL] not inside git repo" >&2; exit 1; }
AP2_HOOK="$REPO_ROOT/.claude/hooks/bash-ap2-check.py"
AP1_HOOK="$REPO_ROOT/.claude/hooks/bash-ap1-inline-check.sh"
FAIL=0

echo "=== L1: lint_skill_bash.py ==="
if python3 scripts/lint_skill_bash.py --fail; then
  echo "[OK] L1 passed -- 0 violations"
else
  echo "[FAIL] L1 failed -- lint violations remain" >&2
  FAIL=1
fi
echo ""

echo "=== L2: hook dry-run for fixed bash blocks ==="
check_cmd() {
  local cmd="$1"
  local desc="$2"
  local payload
  if ! payload=$(python3 -c 'import json,sys; cmd=sys.argv[1]; print(json.dumps({"tool_name":"Bash","tool_input":{"command":cmd}}))' "$cmd"); then
    echo "[FAIL] $desc -- payload error" >&2
    FAIL=1
    return
  fi
  local ap2_rc=0
  local ap1_rc=0
  printf '%s' "$payload" | python3 "$AP2_HOOK" >/dev/null 2>&1 || ap2_rc=$?
  printf '%s' "$payload" | bash "$AP1_HOOK" >/dev/null 2>&1 || ap1_rc=$?
  if [ "$ap2_rc" -ne 0 ] || [ "$ap1_rc" -ne 0 ]; then
    echo "[FAIL] $desc (AP2=$ap2_rc AP1=$ap1_rc)" >&2
    FAIL=1
  else
    echo "[OK] $desc"
  fi
}

# 負向測試：已知違規模式應被 hook 攔截（hook 回歸時此處報 FAIL）
check_cmd_must_block() {
  local cmd="$1"
  local desc="$2"
  local payload
  if ! payload=$(python3 -c 'import json,sys; cmd=sys.argv[1]; print(json.dumps({"tool_name":"Bash","tool_input":{"command":cmd}}))' "$cmd"); then
    echo "[FAIL] $desc -- payload error" >&2
    FAIL=1
    return
  fi
  local ap2_rc=0
  local ap1_rc=0
  printf '%s' "$payload" | python3 "$AP2_HOOK" >/dev/null 2>&1 || ap2_rc=$?
  printf '%s' "$payload" | bash "$AP1_HOOK" >/dev/null 2>&1 || ap1_rc=$?
  if [ "$ap2_rc" -ne 0 ] || [ "$ap1_rc" -ne 0 ]; then
    echo "[OK] $desc (correctly blocked)"
  else
    echo "[FAIL] $desc -- hook should have blocked but passed" >&2
    FAIL=1
  fi
}

check_cmd 'GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir)' "legacy clean-merged (removed in #239): step 1 (git rev-parse)"
check_cmd 'MAIN_REPO=$(dirname "$GIT_COMMON")' "legacy clean-merged (removed in #239): step 2 (dirname)"
check_cmd 'echo "  [OK] released port: branch/svc"' "legacy clean-merged (removed in #239): success echo"
check_cmd 'echo "  [FAIL] failed to release port: branch/svc"' "legacy clean-merged (removed in #239): failure echo"
check_cmd 'echo "  [WARN] 不在 git repo 內 -- 跳過 port cleanup for branch"' "legacy clean-merged (removed in #239): warn echo"
check_cmd 'echo "  [WARN] uv 不可用 -- 跳過 port cleanup for branch"' "legacy clean-merged (removed in #239): warn echo 2"
check_cmd '[ -d .claude/ ] && echo "[OK] .claude/ 存在" || echo "[WARN] .claude/ 不存在，Step 2 會自動建立"' "protect-push: step 1 check"
check_cmd 'echo "[OK] Skill 目錄：$SKILL_DIR"' "protect-push: skill dir ok"
check_cmd 'echo "[OK] hook 腳本已安裝：.claude/hooks/protect-push.sh"' "protect-push: hook installed"
check_cmd 'echo "[OK] settings.json 已建立"' "protect-push: settings ok"
check_cmd '[ -x ".claude/hooks/protect-push.sh" ] && echo "[OK] hook 腳本：存在且可執行" || echo "[FAIL] hook 腳本：未找到"' "protect-push: step 4 check"
check_cmd 'echo "[DONE] 安裝完成！下次 Claude 在此專案執行 git push 時將自動檢查 branch tracking。"' "protect-push: done msg"
check_cmd '# Vertex AI -- Application Default Credentials' "verify-gemini: vertex comment"
check_cmd '# Google AI Studio -- API key' "verify-gemini: ai studio comment"
check_cmd 'jq -r '"'"'select(.session_id == "abc") | "\(.timestamp) -- \(.recap_text)"'"'"' ~/.agents/recap/session-recap.jsonl | sort' "recap: jq with --"
check_cmd 'echo "[OK] $(BIN_DIR)/name"' "makefile: build-tools ok"
check_cmd 'echo "[FAIL] name build failed"' "makefile: build-tools fail"
check_cmd 'echo "[OK] name -> linked"' "makefile: install linked"
check_cmd 'echo "[OK] name removed (Claude Code)"' "makefile: uninstall ok"

# 負向測試：修復前的違規寫法，hook 必須攔截
check_cmd_must_block 'MAIN_REPO=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")' "nested subshell Case 26 variant (before fix)"
check_cmd_must_block 'echo "  ✓ released port: branch/svc"' "Unicode echo AP2 (before fix)"

echo ""
echo "=== L3: pytest regression ==="
if uv run pytest .claude/hooks/tests/ -q; then
  echo "[OK] L3 passed -- all hook tests green"
else
  echo "[FAIL] L3 failed -- hook regression detected" >&2
  FAIL=1
fi
echo ""

if [ $FAIL -eq 0 ]; then
  echo "=== ALL PASS ==="
else
  echo "=== SOME TESTS FAILED -- see [FAIL] lines above ===" >&2
  exit 1
fi

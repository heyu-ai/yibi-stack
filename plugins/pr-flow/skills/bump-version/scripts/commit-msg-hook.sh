#!/usr/bin/env bash
# commit-msg hook：驗證 commit message 格式
# 讀取 .claude/commit-convention.yaml 的設定（若存在）
# 無設定檔時使用預設 Conventional Commits 規則
#
# 安裝方式：透過 init-commit-hook.sh 自動安裝（不要手動複製）
# 此 hook 需要 .claude/hooks/commit-msg-parse.py 存在於目標專案

set -euo pipefail

COMMIT_MSG_FILE="$1"
COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")

# ---------- 找到 parse script ----------

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "[FAIL] 不在 git repo 中" >&2; exit 1
}
PARSE_SCRIPT="$GIT_ROOT/.claude/hooks/commit-msg-parse.py"
CONFIG_FILE="$GIT_ROOT/.claude/commit-convention.yaml"

# ---------- 設定讀取 helpers ----------

parse_config_value() {
  local key="$1" default="$2"
  if ! command -v python3 > /dev/null 2>&1; then
    echo "[WARN] python3 不在 PATH 中，使用預設 commit 設定" >&2
    echo "$default"
    return
  fi
  if [ ! -f "$PARSE_SCRIPT" ]; then
    echo "$default"
    return
  fi
  python3 "$PARSE_SCRIPT" value "$CONFIG_FILE" "$key" "$default" 2>/dev/null || echo "$default"
}

parse_config_list() {
  local key="$1" default="$2"
  if ! command -v python3 > /dev/null 2>&1; then
    echo "$default"
    return
  fi
  if [ ! -f "$PARSE_SCRIPT" ]; then
    echo "$default"
    return
  fi
  python3 "$PARSE_SCRIPT" list "$CONFIG_FILE" "$key" "$default" 2>/dev/null || echo "$default"
}

# ---------- 設定值 ----------

ALLOWED_TYPES_RAW=$(parse_config_list "types" "feat,fix,docs,style,refactor,perf,test,build,ci,chore,revert")
REQUIRE_SCOPE=$(parse_config_value "require_scope" "false")
MAX_SUBJECT_LENGTH=$(parse_config_value "max_subject_length" "72")
TICKET_PATTERN=$(parse_config_value "ticket_pattern" "")

# 驗證 MAX_SUBJECT_LENGTH 是數字
if ! echo "$MAX_SUBJECT_LENGTH" | grep -qE '^[0-9]+$'; then
  echo "[WARN] max_subject_length 設定值無效（$MAX_SUBJECT_LENGTH），使用預設值 72" >&2
  MAX_SUBJECT_LENGTH="72"
fi

# ---------- 略過特殊 commit ----------

SUBJECT=$(echo "$COMMIT_MSG" | head -1)
if echo "$SUBJECT" | grep -qE "^(Merge |Revert |fixup! |squash! )"; then
  exit 0
fi

# ---------- 解析 commit message ----------

PATTERN='^([a-z]+)(\([^)]+\))?(!)?: .+'
if ! echo "$SUBJECT" | grep -qE "$PATTERN"; then
  echo "[FAIL] commit message 格式錯誤"
  echo ""
  echo "      期望格式：type(scope): subject"
  echo "      實際輸入：$SUBJECT"
  echo ""
  echo "      範例："
  echo "        feat(auth): add OAuth2 login"
  echo "        fix: correct null pointer in parser"
  echo "        chore!: drop Node 14 support"
  exit 1
fi

COMMIT_TYPE=$(echo "$SUBJECT" | sed -E 's/^([a-z]+).*/\1/')

# 驗證 type
IFS=',' read -ra ALLOWED_TYPES <<< "$ALLOWED_TYPES_RAW"
TYPE_VALID=false
for t in "${ALLOWED_TYPES[@]}"; do
  if [ "$COMMIT_TYPE" = "$t" ]; then
    TYPE_VALID=true
    break
  fi
done

if [ "$TYPE_VALID" = false ]; then
  echo "[FAIL] 不允許的 commit type：$COMMIT_TYPE"
  echo ""
  echo "      允許的 types：$ALLOWED_TYPES_RAW"
  exit 1
fi

# 驗證 scope
if [ "$REQUIRE_SCOPE" = "true" ]; then
  if ! echo "$SUBJECT" | grep -qE "^[a-z]+\([^)]+\)"; then
    echo "[FAIL] 此專案要求 commit message 必須包含 scope，例如：feat(auth): ..."
    exit 1
  fi
fi

# 驗證 subject 長度
SUBJECT_LEN=${#SUBJECT}
if [ "$SUBJECT_LEN" -gt "$MAX_SUBJECT_LENGTH" ]; then
  echo "[FAIL] commit subject 超過 ${MAX_SUBJECT_LENGTH} 字元（目前 ${SUBJECT_LEN} 字元）"
  echo "      $SUBJECT"
  exit 1
fi

# 驗證 ticket pattern
if [ -n "$TICKET_PATTERN" ]; then
  if ! echo "$COMMIT_MSG" | grep -qE "$TICKET_PATTERN"; then
    echo "[FAIL] commit message 找不到必要的 ticket 編號（pattern：$TICKET_PATTERN）"
    echo "      可在 message body 加入 ticket 編號，例如："
    echo "      Refs: PROJ-123"
    exit 1
  fi
fi

exit 0

#!/usr/bin/env bash
# pr-cycle-deep Step 4.3 — agy R2：Cross-model debate（Round 2）
#
# 用法（在 worktree 目錄執行）：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r2.sh
#
# 模型以 --model 固定為 Gemini 3.8 Flash (High)，與 agy-r1-stage1.sh 相同。
# R2 是跨家 debate，若 auto-select 挑到清單裡的 Claude 模型，「跨家」前提會靜默失效。
#
# 前置條件：$WT_ROOT/.pr-review/prompt-r2.md 與 r1-aggregate.md 已存在。
#
# 副作用：
#   - gemini-r2.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r2.log；agy log 寫到 gemini-r2.agy.log
#   - print timeout 時半截輸出改名為 gemini-r2.timeout-partial.md（0600，issue #443）
#   - 暫存 gemini-r2-input.md（完成後自動刪除）
#   - agy CWD / --add-dir 為一次性 HEAD snapshot；OS sandbox 禁止原始 worktree 與 snapshot 寫入
#
# issue #153：nested worktree 下 agy 無法解析 @file，靜默進入 agentic 模式（R2 實測觀察到
# timeout 這個結局）。修法同 stage1：inline prompt、無舊 scratch 的私有 HOME、agy_validate.py。
#
# --dangerously-skip-permissions 與 subagent 權限等級的完整理由見 agy-r1-stage1.sh 開頭註解
# （<!-- verified: probe, agy 1.1.12，2026-08-13 重驗仍成立 -->）；allow-list 同樣用本 script
# 絕對路徑逐一放行。
#
# 退出碼：0 成功；124 agy print timeout（輸出不完整）；2 AGY_PRINT_TIMEOUT_SECS 不合法；
# 其他非零為其餘失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# 時間預算（issue #443）：agy 自 1.1.28 起 print timeout 到期時回傳半截輸出並 exit 0，
# 預算與偵測的完整理由與實測見 agy_print_timeout.py。預算在碰 agy 之前驗證，不合法時 exit 2。
if ! AGY_PRINT_TIMEOUT_SECS=$(python3 "$SCRIPT_DIR/agy_print_timeout.py" budget); then
    exit 2
fi

if ! WT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi
REVIEW_DIR="$WT_ROOT/.pr-review"
trap 'rm -f "$REVIEW_DIR/gemini-r2-input.md"' EXIT

for f in "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md" "$REVIEW_DIR/changed-files.txt"; do
    if [ ! -f "$f" ]; then
        echo "[FAIL] 前置檔案不存在：$f" >&2
        exit 1
    fi
done

if ! cat "$REVIEW_DIR/prompt-r2.md" "$REVIEW_DIR/r1-aggregate.md" > "$REVIEW_DIR/gemini-r2-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# cd 到 worktree root：本檔在 cd 之後的 `git status --porcelain`（越界編輯偵測）沒有帶 -C，
# 需要 cwd 落在 worktree 內才會量到正確的樹。產物路徑則不依賴它（$REVIEW_DIR 等皆為絕對）。
# agy context 由 agy_isolate.py 的獨立 HEAD snapshot 提供，不使用此 CWD。
cd "$WT_ROOT"

# OS sandbox 是寫入邊界；PRE/POST 另保留為原始 worktree 的稽核訊號。
# helper 失敗或逾時也必須執行 POST，不得因非零退出而略過。
PRE_TREE=$(git status --porcelain)

# issue #153 fix 1：inline prompt 取代 @file，移除 agentic 觸發點。
# 256000B 上限：macOS ARG_MAX 約 1 MiB（單一 arg 與 env 共用該預算），256KB 留足 headroom。
# 註：量的是 prepend REVIEW_ONLY_GUARD 前的 input；guard 為固定 ~400B，相對 headroom 可忽略。
INPUT_BYTES=$(wc -c < "$REVIEW_DIR/gemini-r2-input.md")
if [ "$INPUT_BYTES" -gt 256000 ]; then
    echo "[FAIL] R2 輸入 ${INPUT_BYTES}B 超過 256000B inline 上限" >&2
    exit 1
fi
# REVIEW-ONLY guard 是行為指示；真正寫入隔離由 agy_isolate.py 的 OS sandbox 強制。
REVIEW_ONLY_GUARD="[REVIEWER CONSTRAINT — 最高優先] 你是唯讀 code reviewer。禁止修改、建立或刪除任何檔案，禁止執行任何寫入／編輯指令。只讀取檔案與 diff，然後輸出你的 review 文字。改動工作樹是協議違規——若你發現自己正要編輯，停手，改在 review 裡用文字描述該修改建議。"
INPUT_CONTENT="$REVIEW_ONLY_GUARD

$(cat "$REVIEW_DIR/gemini-r2-input.md")"

# helper 為 agy 設定絕對 snapshot --add-dir，保留 command 探索但不給來源寫入權。
AGY_START=$SECONDS
AGY_EXIT=0
AGY_SIGNAL_EXIT=0
AGY_PID=
interrupt_agy() {
    AGY_SIGNAL_EXIT=$((128 + $1))
    if [ -n "$AGY_PID" ]; then
        kill -"$1" "$AGY_PID" 2>/dev/null || true
    fi
}
trap 'interrupt_agy 15' TERM
trap 'interrupt_agy 2' INT
python3 "$SCRIPT_DIR/agy_isolate.py" --repo-root "$WT_ROOT" -p "$INPUT_CONTENT" \
    --model 'Gemini 3.8 Flash (High)' --timeout-secs "$AGY_PRINT_TIMEOUT_SECS" \
    --agy-log "$REVIEW_DIR/gemini-r2.agy.log" \
    > "$REVIEW_DIR/gemini-r2.md" 2>"$REVIEW_DIR/gemini-r2.log" &
AGY_PID=$!
if [ "$AGY_SIGNAL_EXIT" -ne 0 ]; then
    kill -"$((AGY_SIGNAL_EXIT - 128))" "$AGY_PID" 2>/dev/null || true
fi
wait "$AGY_PID" || AGY_EXIT=$?
if [ "$AGY_SIGNAL_EXIT" -ne 0 ]; then
    trap '' TERM INT
    wait "$AGY_PID" || true
    AGY_EXIT=$AGY_SIGNAL_EXIT
fi
AGY_PID=
trap - TERM INT
AGY_ELAPSED=$((SECONDS - AGY_START))

# 偵測 agy 是否在 review 階段越界編輯工作樹（PR #194 retro：agy R2 曾自主改 6 個檔）。
# 不 hard-fail（review 文字仍有價值），但 loud [WARN] 要 lead 逐行稽核並 revert 非預期編輯。
# 放在失敗／timeout 判定之前：所有已啟動的 reviewer 都必須有 POST 稽核。
POST_TREE=$(git status --porcelain)
if [ "$PRE_TREE" != "$POST_TREE" ]; then
    echo "[WARN] agy 在 review 階段改動了工作樹（review 應唯讀）；請稽核以下變更並在採用前 revert 非預期編輯：" >&2
    git status --short >&2
fi

# issue #443：逾時判定必須在「輸出空白」檢查之前，否則卡在 429 重試而逾時的空輸出會被誤報成
# 輸出異常。逾時時 helper 已把半截輸出移出 gemini-r2.md，聚合步驟讀不到它。
TIMEOUT_CHECK_EXIT=0
python3 "$SCRIPT_DIR/agy_print_timeout.py" check \
    --raw "$REVIEW_DIR/gemini-r2.md" \
    --stderr-log "$REVIEW_DIR/gemini-r2.log" \
    --agy-log "$REVIEW_DIR/gemini-r2.agy.log" \
    --elapsed-secs "$AGY_ELAPSED" \
    --budget-secs "$AGY_PRINT_TIMEOUT_SECS" \
    --label "agy R2" || TIMEOUT_CHECK_EXIT=$?
if [ "$TIMEOUT_CHECK_EXIT" -eq 1 ]; then
    exit 124
elif [ "$TIMEOUT_CHECK_EXIT" -ne 0 ]; then
    echo "[FAIL] agy R2 的 timeout 檢查本身失敗（exit ${TIMEOUT_CHECK_EXIT}），無法確認輸出是否完整" >&2
    exit 1
fi

if [ "$AGY_EXIT" -ne 0 ]; then
    echo "[FAIL] agy R2 失敗（exit ${AGY_EXIT}），請查看 $REVIEW_DIR/gemini-r2.log" >&2
    exit "$AGY_EXIT"
fi

if [ ! -s "$REVIEW_DIR/gemini-r2.md" ]; then
    echo "[FAIL] gemini-r2.md 空白，R2 輸出異常" >&2
    exit 1
fi

# issue #153 fix 3+4：brain-artifact rescue + fail-loud 驗證。
if ! python3 "$SCRIPT_DIR/agy_validate.py" \
    --raw "$REVIEW_DIR/gemini-r2.md" \
    --changed-files "$REVIEW_DIR/changed-files.txt" \
    --repo-root "$WT_ROOT" \
    --require-verdict \
    --label "agy R2"; then
    echo "[FAIL] agy R2 輸出未通過 fail-loud 驗證（見上方 [FAIL] 訊息）" >&2
    exit 1
fi

echo "agy R2 complete"

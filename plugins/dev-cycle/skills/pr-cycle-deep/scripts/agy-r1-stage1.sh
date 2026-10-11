#!/usr/bin/env bash
# pr-cycle-deep Step 3.2 — agy R1 Stage 1：Native review
#
# 用法（在 worktree 目錄執行）：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh
#
# 模型以 --model 固定為 Gemini 3.8 Flash (High)：agy 的自動選型可能挑到其他 Gemini
# tier，且可選清單含 Claude Sonnet/Opus——auto-select 挑到 Claude 會讓「跨家 review」退化成
# 與主 session 同源，且不會有任何警告。2026-09-03 以 agy 1.1.25 在台灣實測
# gemini-3.8-flash-high 可穩定回應；High tier 保留 mob review 所需的推理深度。
# 值必須用 `agy models` 的完整 display name；無效值會 fail-loud 並列出可用清單。
#
# 副作用：
#   - gemini-r1-raw.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r1.stage1.log；agy log 寫到 gemini-r1.stage1.agy.log
#   - print timeout 時半截輸出改名為 gemini-r1-raw.timeout-partial.md（0600，issue #443）
#   - 暫存 gemini-r1-input.md（完成後自動刪除）
#   - agy CWD / --add-dir 為一次性 HEAD snapshot；OS sandbox 禁止原始 worktree 與 snapshot 寫入
#
# 注意：使用 --dangerously-skip-permissions 而非 --sandbox（--sandbox 會 auto-deny review 探索
# 周邊程式碼用的 command 工具，見下方 <!-- verified --> 機制註解；--add-dir 的檔案讀取本身在
# sandbox 下仍放行，故此處的理由不是「保留 --add-dir context」而是「保留 command 探索能力」）。
# 這是 subagent 權限等級（由 pr-cycle-deep 呼叫，非使用者直接呼叫），allow-list 用本 script
# 的絕對路徑逐一放行，不共用 agy-review/agy-consult 的允許清單。
# <!-- verified: probe, agy 1.1.12（原註記 1.1.8，2026-08-13 於真實 worktree 重跑 stage1
# 形式，結論不變）--> --sandbox 底下真正 review 時，agy 會呼叫 `command` 權限工具（跑 shell
# 指令探索周邊程式碼）；headless -p 模式沒有互動終端可核准，agy 直接 auto-deny，並在 stderr
# 印出大意為「no output produced -- a tool required the "command" permission that headless
# mode cannot prompt for」的訊息（非逐字引用），review 輸出檔（stdout）則為空
# （agy_validate.py 會抓到空輸出）。
# 機制精確化（1.1.12 重驗）：agy 的 read_file / ListDirectory 檔案存取工具在 --add-dir 範圍
# 內於 sandbox 下是放行的；被擋的專指 `command`（shell 執行）這一類，故放寬 --add-dir 無法
# 解，只有 --dangerously-skip-permissions，或在 ~/.gemini/antigravity-cli/settings.json 的
# permissions.allow 補 command(...) 唯讀項，才能讓 sandbox 下的 review 產出。升級 agy 版本
# 後仍應重新驗證這個結論。
#
# issue #153：nested worktree 下 agy 無法解析 @file，靜默進入 agentic 模式（wrong-target
# review / brain-artifact / timeout）。修法：(1) inline prompt 取代 @file，移除 agentic
# 觸發點；(2) 使用不複製舊 scratch 的私有 HOME；(3) 跑 agy_validate.py
# 做 fail-loud 驗證（timeout / agentic narration / 缺 Verdict / 沒提到 changed file）。
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
trap 'rm -f "$REVIEW_DIR/gemini-r1-input.md"' EXIT

if [ ! -f "$REVIEW_DIR/prompt-r1.md" ]; then
    echo "[FAIL] prompt-r1.md 不存在；請確認 Write tool 已寫入 review prompt（Step 3.1）" >&2
    exit 1
fi

if [ ! -f "$REVIEW_DIR/diff.patch" ]; then
    echo "[FAIL] diff.patch 不存在，請重跑 Step 2 setup" >&2
    exit 1
fi

if [ ! -f "$REVIEW_DIR/changed-files.txt" ]; then
    echo "[FAIL] changed-files.txt 不存在，請重跑 Step 2 setup（fail-loud 驗證需要）" >&2
    exit 1
fi

if ! cat "$REVIEW_DIR/prompt-r1.md" "$REVIEW_DIR/diff.patch" > "$REVIEW_DIR/gemini-r1-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# cd 到 worktree root：本檔在 cd 之後的 `git status --porcelain`（PRE_TREE／POST_TREE 越界
# 編輯偵測）沒有帶 -C，需要 cwd 落在 worktree 內才會量到正確的樹。產物路徑則不依賴它——
# $REVIEW_DIR 等全是絕對路徑。
# agy context 由 agy_isolate.py 的獨立 HEAD snapshot 提供，不使用此 CWD。
cd "$WT_ROOT"

# OS sandbox 是寫入邊界；PRE/POST 另保留為原始 worktree 的稽核訊號。
# helper 失敗或逾時也必須執行 POST，不得因非零退出而略過。
PRE_TREE=$(GIT_OPTIONAL_LOCKS=0 git status --porcelain)

# issue #153 fix 1：inline prompt 取代 @file。nested worktree 下 @file 解析失敗會讓 agy
# 進入 agentic 探索；改成把 prompt+diff 內容直接餵進 -p，agy 不需讀檔即無 agentic 觸發點。
# 256000B 上限：macOS ARG_MAX 約 1 MiB（單一 arg 與 env 共用該預算），256KB 留足 headroom；
# 實測一次 mob review 輸入約 63KB，遠低於此。調高前先確認不會逼近 getconf ARG_MAX。
# 註：此處量的是 prepend REVIEW_ONLY_GUARD 前的 input；guard 為固定字串（~400B），
# 相對 256KB→ARG_MAX 的數倍 headroom 可忽略，不改變此檢查的保護語意。
INPUT_BYTES=$(wc -c < "$REVIEW_DIR/gemini-r1-input.md")
if [ "$INPUT_BYTES" -gt 256000 ]; then
    echo "[FAIL] review 輸入 ${INPUT_BYTES}B 超過 256000B inline 上限，diff 過大不適合 agy inline 模式" >&2
    exit 1
fi
# REVIEW-ONLY guard 是行為指示；真正寫入隔離由 agy_isolate.py 的 OS sandbox 強制。
REVIEW_ONLY_GUARD="[REVIEWER CONSTRAINT — 最高優先] 你是唯讀 code reviewer。禁止修改、建立或刪除任何檔案，禁止執行任何寫入／編輯指令。只讀取檔案與 diff，然後輸出你的 review 文字。改動工作樹是協議違規——若你發現自己正要編輯，停手，改在 review 裡用文字描述該修改建議。"
INPUT_CONTENT="$REVIEW_ONLY_GUARD

$(cat "$REVIEW_DIR/gemini-r1-input.md")"

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
    --agy-log "$REVIEW_DIR/gemini-r1.stage1.agy.log" \
    > "$REVIEW_DIR/gemini-r1-raw.md" 2>"$REVIEW_DIR/gemini-r1.stage1.log" &
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

rm -f "$REVIEW_DIR/gemini-r1-input.md"

# 偵測 agy 是否在 review 階段越界編輯工作樹（PR #194 retro：agy R2 曾自主改 6 個檔）。
# 不 hard-fail（review 文字仍有價值），但 loud [WARN] 要 lead 逐行稽核並 revert 非預期編輯。
# 放在失敗／timeout 判定之前：所有已啟動的 reviewer 都必須有 POST 稽核。
POST_TREE=$(GIT_OPTIONAL_LOCKS=0 git status --porcelain)
if [ "$PRE_TREE" != "$POST_TREE" ]; then
    echo "[WARN] agy 在 review 階段改動了工作樹（review 應唯讀）；請稽核以下變更並在採用前 revert 非預期編輯：" >&2
    git status --short >&2
fi

# issue #443：逾時判定必須在「輸出空白」檢查之前，否則卡在 429 重試而逾時的空輸出會被誤報成
# 輸出異常。逾時時 helper 已把半截輸出移出 gemini-r1-raw.md，Stage 2 讀不到它。
TIMEOUT_CHECK_EXIT=0
python3 "$SCRIPT_DIR/agy_print_timeout.py" check \
    --raw "$REVIEW_DIR/gemini-r1-raw.md" \
    --stderr-log "$REVIEW_DIR/gemini-r1.stage1.log" \
    --agy-log "$REVIEW_DIR/gemini-r1.stage1.agy.log" \
    --elapsed-secs "$AGY_ELAPSED" \
    --budget-secs "$AGY_PRINT_TIMEOUT_SECS" \
    --label "agy R1 Stage 1" || TIMEOUT_CHECK_EXIT=$?
if [ "$TIMEOUT_CHECK_EXIT" -eq 1 ]; then
    exit 124
elif [ "$TIMEOUT_CHECK_EXIT" -ne 0 ]; then
    echo "[FAIL] agy R1 Stage 1 的 timeout 檢查本身失敗（exit ${TIMEOUT_CHECK_EXIT}），無法確認輸出是否完整" >&2
    exit 1
fi

if [ "$AGY_EXIT" -ne 0 ]; then
    echo "[FAIL] agy review 失敗（exit ${AGY_EXIT}），請查看 $REVIEW_DIR/gemini-r1.stage1.log" >&2
    exit "$AGY_EXIT"
fi

if [ ! -s "$REVIEW_DIR/gemini-r1-raw.md" ]; then
    echo "[FAIL] gemini-r1-raw.md 空白，Stage 1 輸出異常" >&2
    exit 1
fi

# issue #153 fix 3+4：brain-artifact rescue + fail-loud 驗證。validator 會在偵測到
# brain pointer 時就地改寫 gemini-r1-raw.md 為真正 review 內容，再驗證
# timeout / agentic narration / 缺 Verdict / changed-file content-sanity（issue #208：
# 引用 repo 中存在但不在 diff 的檔案降級為 [WARN]，不存在的才 [FAIL]）。
if ! python3 "$SCRIPT_DIR/agy_validate.py" \
    --raw "$REVIEW_DIR/gemini-r1-raw.md" \
    --changed-files "$REVIEW_DIR/changed-files.txt" \
    --repo-root "$WT_ROOT" \
    --require-verdict \
    --label "agy R1 Stage 1"; then
    echo "[FAIL] agy R1 Stage 1 輸出未通過 fail-loud 驗證（見上方 [FAIL] 訊息）" >&2
    exit 1
fi

echo "agy R1 Stage 1 complete"

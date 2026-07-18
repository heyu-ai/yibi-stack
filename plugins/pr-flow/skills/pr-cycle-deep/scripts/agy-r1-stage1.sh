#!/usr/bin/env bash
# pr-cycle-deep Step 3.2 — agy R1 Stage 1：Native review
#
# 用法（在 worktree 目錄執行）：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh
#
# 模型以 --model 固定為 Gemini 3.1 Pro (Low)：agy 的自動選型實測會挑 Gemini 3.5 Flash，
# 且可選清單含 Claude Sonnet/Opus——auto-select 挑到 Claude 會讓「跨家 review」退化成與主
# session 同源，且不會有任何警告。3.1 Pro 是清單中唯一的 Pro 等級（無 3.5 Pro）。
# 原先固定 (High)，但實測在本機一律故障；改 (Low) 可穩定產出 review，且仍為 Pro 等級，
# 推理深度足夠、跨家前提不受影響。（AGYS-DT-008 只斷言 Gemini 前綴，High↔Low 互換不影響測試。）
# 值必須用 `agy models` 的完整 display name；無效值會 fail-loud 並列出可用清單。
#
# 副作用：
#   - gemini-r1-raw.md 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r1.stage1.log
#   - 暫存 gemini-r1-input.md（完成後自動刪除）
#   - CWD 切換到 $WT_ROOT（--add-dir . 以 WT_ROOT 為 context 基準）
#
# 注意：使用 --dangerously-skip-permissions 而非 --sandbox（保留 --add-dir 周邊程式碼 context）。
#
# issue #153：nested worktree 下 agy 無法解析 @file，靜默進入 agentic 模式（wrong-target
# review / brain-artifact / timeout）。修法：(1) inline prompt 取代 @file，移除 agentic
# 觸發點；(2) 開頭清掉殘留 scratch input，消除 stale-input 污染向量；(3) 跑 agy_validate.py
# 做 fail-loud 驗證（timeout / agentic narration / 缺 Verdict / 沒提到 changed file）。
#
# 退出碼：0 成功；非零失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# issue #153 fix 2：清掉殘留的 agy scratch input，避免 agentic 檔案搜尋撈到上個 session
# 的 stale input 而 review 錯誤 target。-f 確保無檔案（含 glob 不展開）時不報錯；不吞掉
# 真實失敗（如權限錯誤）——清理失敗代表 stale-input 防線失效，必須讓使用者看到 [WARN]。
rm -f "$HOME"/.gemini/antigravity-cli/scratch/gemini-*-input.md || echo "[WARN] agy scratch cleanup failed; stale-input vector not cleared" >&2

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
    echo "[FAIL] diff.patch 不存在，請重跑 Step 3.1 setup block" >&2
    exit 1
fi

if [ ! -f "$REVIEW_DIR/changed-files.txt" ]; then
    echo "[FAIL] changed-files.txt 不存在，請重跑 Step 3.1 setup block（fail-loud 驗證需要）" >&2
    exit 1
fi

if ! cat "$REVIEW_DIR/prompt-r1.md" "$REVIEW_DIR/diff.patch" > "$REVIEW_DIR/gemini-r1-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

# cd 到 worktree root：--add-dir . 以 WT_ROOT 為周邊程式碼 context 基準。
cd "$WT_ROOT"

# 防越界編輯（PR #194 retro）：agy 以權限繞過旗標執行，具 worktree 寫入權；review 階段
# 應為唯讀。快照 agy 執行前的 git 狀態，執行後比對，若工作樹被改動則 fail-loud [WARN]。
# review 產物不誤報：.pr-review/ 全部未追蹤，git status --porcelain 把它摺疊成單行
# `?? .pr-review/`（不列個別檔），PRE/POST 相同——只有 agy 改動「已追蹤」檔才會觸發。
PRE_TREE=$(git status --porcelain)

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
# REVIEW-ONLY guard：prepend 到餵給 agy 的 prompt，顯式禁止編輯（權限繞過旗標讓 agy 能寫，
# 唯一防線是明確約束 + 下方的 tree-diff 偵測）。
REVIEW_ONLY_GUARD="[REVIEWER CONSTRAINT — 最高優先] 你是唯讀 code reviewer。禁止修改、建立或刪除任何檔案，禁止執行任何寫入／編輯指令。只讀取檔案與 diff，然後輸出你的 review 文字。改動工作樹是協議違規——若你發現自己正要編輯，停手，改在 review 裡用文字描述該修改建議。"
INPUT_CONTENT="$REVIEW_ONLY_GUARD

$(cat "$REVIEW_DIR/gemini-r1-input.md")"

if ! agy -p "$INPUT_CONTENT" --model 'Gemini 3.1 Pro (Low)' --add-dir . --dangerously-skip-permissions --print-timeout 10m \
    > "$REVIEW_DIR/gemini-r1-raw.md" \
    2>"$REVIEW_DIR/gemini-r1.stage1.log"; then
    echo "[FAIL] agy review 失敗，請查看 $REVIEW_DIR/gemini-r1.stage1.log" >&2
    rm -f "$REVIEW_DIR/gemini-r1-input.md"
    exit 1
fi

rm -f "$REVIEW_DIR/gemini-r1-input.md"

if [ ! -s "$REVIEW_DIR/gemini-r1-raw.md" ]; then
    echo "[FAIL] gemini-r1-raw.md 空白，Stage 1 輸出異常" >&2
    exit 1
fi

# 偵測 agy 是否在 review 階段越界編輯工作樹（PR #194 retro：agy R2 曾自主改 6 個檔）。
# 不 hard-fail（review 文字仍有價值），但 loud [WARN] 要 lead 逐行稽核並 revert 非預期編輯。
POST_TREE=$(git status --porcelain)
if [ "$PRE_TREE" != "$POST_TREE" ]; then
    echo "[WARN] agy 在 review 階段改動了工作樹（review 應唯讀）；請稽核以下變更並在採用前 revert 非預期編輯：" >&2
    git status --short >&2
fi

# issue #153 fix 3+4：brain-artifact rescue + fail-loud 驗證。validator 會在偵測到
# brain pointer 時就地改寫 gemini-r1-raw.md 為真正 review 內容，再驗證
# timeout / agentic narration / 缺 Verdict / 沒提到任何 changed file（wrong-target）。
if ! python3 "$SCRIPT_DIR/agy_validate.py" \
    --raw "$REVIEW_DIR/gemini-r1-raw.md" \
    --changed-files "$REVIEW_DIR/changed-files.txt" \
    --require-verdict \
    --label "agy R1 Stage 1"; then
    echo "[FAIL] agy R1 Stage 1 輸出未通過 fail-loud 驗證（見上方 [FAIL] 訊息）" >&2
    exit 1
fi

echo "agy R1 Stage 1 complete"

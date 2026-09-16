#!/usr/bin/env bash
# pr-cycle-deep Step 3.2 — agy R1 Stage 2：Extract（raw → JSON）
#
# 用法：
#   bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh
#
# 模型固定為 Gemini 3.8 Flash (High)，與 review/debate stages 使用同一模型。
#
# 副作用：
#   - gemini-r1.json 寫到 $WT_ROOT/.pr-review/
#   - stderr log 寫到 $WT_ROOT/.pr-review/gemini-r1.extract.log；agy log 寫到 gemini-r1.extract.agy.log
#   - print timeout 時半截輸出改名為 gemini-r1.json.timeout-partial.tmp（0600，issue #443）
#   - 暫存 gemini-extract-input.md（完成後自動刪除）
#
# 退出碼：0 成功；124 agy print timeout（輸出不完整）；2 AGY_PRINT_TIMEOUT_SECS 不合法；
# 其他非零為其餘失敗（每種失敗都附 [FAIL] stderr 訊息）。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
EXTRACT_PROMPT=~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md

# 時間預算（issue #443）：agy 自 1.1.28 起 print timeout 到期時回傳半截輸出並 exit 0，
# 預算與偵測的完整理由與實測見 agy_print_timeout.py。預算在碰 agy 之前驗證，不合法時 exit 2。
if ! AGY_PRINT_TIMEOUT_SECS=$(python3 "$SCRIPT_DIR/agy_print_timeout.py" budget); then
    exit 2
fi

# issue #153 fix 2：清掉殘留的 agy scratch input，避免 agentic 檔案搜尋撈到 stale input。
# 不吞掉真實失敗（如權限錯誤）——清理失敗代表 stale-input 防線失效，須讓使用者看到 [WARN]。
rm -f "$HOME"/.gemini/antigravity-cli/scratch/gemini-*-input.md || echo "[WARN] agy scratch cleanup failed; stale-input vector not cleared" >&2

# Ensure temp files are cleaned even on unexpected exit (set -e early exit, signal, etc.)
_STAGE2_CLEANUP() { rm -f "${REVIEW_DIR:-/dev/null}/gemini-extract-input.md" "${TMP_JSON:-/dev/null}"; }
trap _STAGE2_CLEANUP EXIT

if [ ! -f "$EXTRACT_PROMPT" ]; then
    echo "[FAIL] extract prompt 不存在；請執行 make install" >&2
    exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FAIL] 當前目錄不在 git repo 內（請在 worktree 目錄執行此 script）" >&2
    exit 1
fi

WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"

if [ ! -f "$REVIEW_DIR/gemini-r1-raw.md" ]; then
    echo "[FAIL] gemini-r1-raw.md 不存在；請確認 Stage 1 已成功完成" >&2
    exit 1
fi

if [ ! -f "$REVIEW_DIR/changed-files.txt" ]; then
    echo "[FAIL] changed-files.txt 不存在，請重跑 Step 3.1 setup block（fail-loud 驗證需要）" >&2
    exit 1
fi

if ! cat "$EXTRACT_PROMPT" "$REVIEW_DIR/gemini-r1-raw.md" > "$REVIEW_DIR/gemini-extract-input.md"; then
    echo "[FAIL] cat 串接失敗" >&2
    exit 1
fi

printf '\n---END RAW OUTPUT---\n' >> "$REVIEW_DIR/gemini-extract-input.md"

# cd 到 worktree root。**這個 cd 在本檔已無已知的功能依賴**，保留是保守作法而非需求：
#   - 不是為了產物路徑：本檔在 cd 之後的每一個路徑都是絕對的（$REVIEW_DIR、$TMP_JSON、
#     $SCRIPT_DIR），沒有任何相對路徑寫入。
#   - 不是為了 git：與 stage1／r2 不同，本檔在 cd 之後沒有任何 git 呼叫（僅有的兩個
#     git rev-parse 都在 cd 之前）。
#   - 不是為了 agy context：--add-dir 傳的是 "$WT_ROOT" 絕對路徑（見下方註解）。
# 保留的唯一理由是 agy 自身在 -p 模式下的 cwd 語意未經探測，移除屬未驗證的行為變更。
# 要移除請先實測 agy 在不同 cwd 下的行為，不要因為「看起來沒用到」就刪。
# （前一版註解寫「相對路徑的產物寫入以 WT_ROOT 為基準」——那是錯的，本檔沒有這種寫入；
#   它取代掉了原本正確的理由（`--add-dir .` context），讓下一個作者失去判斷依據。）
cd "$WT_ROOT"

# issue #153 fix 1：inline prompt 取代 @file。萃取任務只需 raw 文字，--sandbox 即足夠
# （extraction 不需讀周邊程式碼，sandbox 更安全）。inline 後 agy 無需讀檔即無 agentic 觸發點。
# 256000B 上限：與 stage1/r2 一致，避免 verbose R1 raw 讓 inline arg 逼近 macOS ARG_MAX。
TMP_JSON="$REVIEW_DIR/gemini-r1.json.tmp"
EXTRACT_BYTES=$(wc -c < "$REVIEW_DIR/gemini-extract-input.md")
if [ "$EXTRACT_BYTES" -gt 256000 ]; then
    echo "[FAIL] extract 輸入 ${EXTRACT_BYTES}B 超過 256000B inline 上限，R1 raw 過大不適合 inline 萃取" >&2
    exit 1
fi
EXTRACT_CONTENT=$(cat "$REVIEW_DIR/gemini-extract-input.md")
AGY_START=$SECONDS
if ! agy -p "$EXTRACT_CONTENT" \
    --model 'Gemini 3.8 Flash (High)' \
    --add-dir "$WT_ROOT" \
    --sandbox \
    --print-timeout "${AGY_PRINT_TIMEOUT_SECS}s" \
    --log-file "$REVIEW_DIR/gemini-r1.extract.agy.log" \
    > "$TMP_JSON" \
    2>"$REVIEW_DIR/gemini-r1.extract.log"; then
    echo "[FAIL] agy extract 失敗，請查看 $REVIEW_DIR/gemini-r1.extract.log" >&2
    rm -f "$REVIEW_DIR/gemini-extract-input.md" "$TMP_JSON"
    exit 1
fi
AGY_ELAPSED=$((SECONDS - AGY_START))

# issue #443：逾時判定在 fail-loud 驗證與 JSON 萃取之前，否則逾時的空輸出會被誤報成
# 「找不到有效的 JSON」。逾時時 helper 已把半截輸出改名移開，EXIT trap 只清 input 暫存檔。
TIMEOUT_CHECK_EXIT=0
python3 "$SCRIPT_DIR/agy_print_timeout.py" check \
    --raw "$TMP_JSON" \
    --stderr-log "$REVIEW_DIR/gemini-r1.extract.log" \
    --agy-log "$REVIEW_DIR/gemini-r1.extract.agy.log" \
    --elapsed-secs "$AGY_ELAPSED" \
    --budget-secs "$AGY_PRINT_TIMEOUT_SECS" \
    --label "agy R1 Stage 2" || TIMEOUT_CHECK_EXIT=$?
if [ "$TIMEOUT_CHECK_EXIT" -eq 1 ]; then
    exit 124
elif [ "$TIMEOUT_CHECK_EXIT" -ne 0 ]; then
    echo "[FAIL] agy R1 Stage 2 的 timeout 檢查本身失敗（exit ${TIMEOUT_CHECK_EXIT}），無法確認輸出是否完整" >&2
    exit 1
fi

# issue #153 fix 3+4：brain-artifact rescue + fail-loud 驗證。萃取若進入 agentic 模式，
# 真正輸出會寫到 brain artifact，TMP_JSON 只剩 narration+pointer——validator 就地還原。
# 不檢 Verdict（萃取輸出為 JSON，verdict 由下方 schema 把關），但帶 --changed-files +
# --repo-root：content-sanity 區分「引用了 repo 中存在但不在 diff 的檔案」（issue #208，
# [WARN] 放行）與「引用了不存在的檔案」（[FAIL] 擋住 agentic drift wrong-target JSON）。
if ! python3 "$SCRIPT_DIR/agy_validate.py" \
    --raw "$TMP_JSON" \
    --changed-files "$REVIEW_DIR/changed-files.txt" \
    --repo-root "$WT_ROOT" \
    --label "agy R1 Stage 2"; then
    echo "[FAIL] agy R1 Stage 2 萃取輸出未通過 fail-loud 驗證（見上方 [FAIL] 訊息）" >&2
    rm -f "$REVIEW_DIR/gemini-extract-input.md" "$TMP_JSON"
    exit 1
fi

if ! python3 -c '
import sys, json
try:
    content = open(sys.argv[1], "r", encoding="utf-8").read()
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1:
        json_str = content[start:end+1]
        data = json.loads(json_str)
        if "verdict" in data and "summary" in data and isinstance(data.get("findings"), list):
            print(json.dumps(data, indent=2, ensure_ascii=False))
            sys.exit(0)
    print("[FAIL] 找不到有效的 JSON 物件或欄位不符 schema", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] JSON 萃取或驗證失敗: {e}", file=sys.stderr)
    sys.exit(1)
' "$TMP_JSON" > "$REVIEW_DIR/gemini-r1.json"; then
    echo "[FAIL] 從 agy 輸出中萃取 JSON 失敗" >&2
    rm -f "$REVIEW_DIR/gemini-extract-input.md" "$TMP_JSON"
    exit 1
fi
rm -f "$TMP_JSON"

rm -f "$REVIEW_DIR/gemini-extract-input.md"

echo "agy R1 Stage 2 complete"

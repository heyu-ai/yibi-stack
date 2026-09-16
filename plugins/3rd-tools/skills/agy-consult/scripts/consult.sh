#!/usr/bin/env bash
# agy standalone consult runner -- no diff, just a technical question against the repo
# Usage: consult.sh (no arguments)
#
# 不吃任何參數，固定讀 $CLAUDE_JOB_DIR/agy-consult-question.txt（PR #367 mob review Critical，
# 第二輪發現）：第一輪的修法是「吃問題檔案路徑而不是問題本文」，解決了雙引號擋不住 shell
# 展開的問題，但把路徑做成參數本身就是新的漏洞——這支 script 的 allow-list entry 是
# `Bash(bash .../consult.sh:*)`（見 scripts/patch_agy_allow_list.py），`:*` 允許任意參數，
# 一旦允許清單生效，`bash consult.sh ~/.ssh/id_rsa` 一樣會通過驗證、讀出私鑰內容、包進
# prompt 傳給外部的 agy 行程——變成一個被預先核准、免確認的任意檔案讀取＋外傳原語。
# 固定死路徑 + exact-match allow-list（不帶 `:*`）才能真正關掉這個面：呼叫端沒有任何
# 參數可以塞，allow-list 也不再需要放行任何額外內容。
set -euo pipefail

if [ -z "${CLAUDE_JOB_DIR:-}" ]; then
    echo "[FAIL] CLAUDE_JOB_DIR 未設定，無法定位問題檔案。請在有 CLAUDE_JOB_DIR 的 Claude Code session 執行。" >&2
    exit 1
fi
QUESTION_FILE="$CLAUDE_JOB_DIR/agy-consult-question.txt"

if [ ! -f "$QUESTION_FILE" ]; then
    echo "[FAIL] $QUESTION_FILE 不存在。請先用 Write tool 把問題寫進這個檔案，再執行本 script。" >&2
    exit 1
fi

QUESTION=$(cat "$QUESTION_FILE")
if [ -z "$QUESTION" ]; then
    echo "[FAIL] $QUESTION_FILE is empty." >&2
    exit 1
fi

if ! command -v agy >/dev/null 2>&1; then
    echo "[FAIL] agy not found. Install with: pip install antigravity-cli" >&2
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

# 預設用 Gemini：本 skill 存在的理由是取得**跨廠商**的第二意見，預設若是 Claude，
# 在 mob review 裡會與 Claude voice 家族塌縮（兩票同源卻被當成兩家）。
# 2026-09-03 實測（agy 1.1.25，台灣）：gemini-3.8-flash-high / 3.8-flash-low /
# 3.7-flash-low / 3.6-flash-low / 3.1-pro-low 五個 model id 各發一次請求全部成功，
# 無 FAILED_PRECONDITION: User location is not supported。四個模型各自回報與請求
# 一致的名稱，排除靜默 fallback。（此前的預設 claude-sonnet-4-6 是為了規避該地區
# 限制，該前提已不成立。）
# 這是版本相依的實測，不是永久事實——agy 升版後若 Gemini 路徑再度失效，請重測後
# 再改預設，並更新這段註解的版本戳記（rule 13 probe-rot）。
# 允許透過 AGY_MODEL 環境變數覆寫（可接受值見 `agy models` 左欄）。
AGY_MODEL="${AGY_MODEL:-gemini-3.8-flash-high}"

# agy print 模式的時間預算（整數秒）。`--print-timeout`（預設 5m）自 **agy 1.1.28** 起，到期時
# 改為「回傳已產出的片段並成功退出」——changelog 1.1.28 原文：「the CLI now returns the partial
# output it has and exits successfully with a warning on stderr, instead of failing with a timeout
# error」。在那之前是非零退出。本段行為以 agy 1.2.3 實測複驗（`--output-format json` 在同情境
# 回 status=SUCCESS、response 為空字串，故 exit code 與 JSON 皆不帶判決資訊）。
# 版本戳記別再寫成 1.2.3：判斷「某個舊版 agy 是否受影響」要用 1.1.28 這條線（rule 13
# version-stamped probes expire）。
#
# 預設 480 秒刻意低於 Claude Code Bash tool 的 600 秒上限：預算 >= 600 時 harness 會先砍掉
# 整支 script，下方的 [FAIL] 診斷永遠印不出來——使用者只看到「timeout」卻不知道原因。
# 這個上限必須由程式強制：只寫在註解與 SKILL.md 的話，`AGY_PRINT_TIMEOUT_SECS=900` 會原封不動
# 送進 agy，完整重現本 PR 要消滅的那個事故形狀。下界同理：`0` 會讓耗時比較對任何回答都成立。
#
# 上界取 570 而非 599：預算計的是 **agy 內部**的時間，牆鐘還要加上 language server 啟動
# （實測 20 秒預算的真 timeout 牆鐘 22 秒）。599 + 啟動 ≈ 601 > 600，等於腳本放行了一個必然
# 被 harness 先砍掉的值——用自己宣稱合法的參數重現本 PR 要修的事故。30 秒餘裕涵蓋啟動與偶發
# 抖動（`agy --help` 本身只要 0.27 秒，可忽略）。
AGY_PRINT_TIMEOUT_MAX=570
AGY_PRINT_TIMEOUT_SECS="${AGY_PRINT_TIMEOUT_SECS:-480}"
# 不需要 `''|` 分支：上一行的 `:-` 對空字串也會套用預設值，變數到這裡永遠非空。
case "$AGY_PRINT_TIMEOUT_SECS" in
    *[!0-9]*)
        echo "[FAIL] AGY_PRINT_TIMEOUT_SECS 必須是整數秒（收到：${AGY_PRINT_TIMEOUT_SECS}），例如 480" >&2
        exit 2
        ;;
esac
# 先擋長度再做數值比較：`[ "$v" -lt 1 ]` 對超出 shell 整數範圍的值會以「integer expression
# expected」錯誤返回，而它位在 if 條件裡不受 set -e 管，於是兩個比較都失敗、條件為假——
# 超大值反而被放行（實測 999999999999999999999999 → PASSED-THROUGH）。上限 570 只有三位數，
# 所以長度就是安全的前置判準。
case "$AGY_PRINT_TIMEOUT_SECS" in
    ???|??|?) ;;
    *)
        echo "[FAIL] AGY_PRINT_TIMEOUT_SECS 必須介於 1 與 ${AGY_PRINT_TIMEOUT_MAX} 之間（收到：${AGY_PRINT_TIMEOUT_SECS}）。" >&2
        exit 2
        ;;
esac
if [ "$AGY_PRINT_TIMEOUT_SECS" -lt 1 ] || [ "$AGY_PRINT_TIMEOUT_SECS" -gt "$AGY_PRINT_TIMEOUT_MAX" ]; then
    echo "[FAIL] AGY_PRINT_TIMEOUT_SECS 必須介於 1 與 ${AGY_PRINT_TIMEOUT_MAX} 之間（收到：${AGY_PRINT_TIMEOUT_SECS}）。" >&2
    echo "       上界留了 30 秒餘裕給 agy 的啟動時間：預算是 agy 內部的計時，牆鐘還要加上 language server 啟動（實測約 2 秒）；貼著 600 設會讓 Claude Code Bash tool 先砍掉整支 script，所有診斷都印不出來。0 則會讓耗時判定對任何回答都成立。" >&2
    exit 2
fi

# 參數驗證通過後才碰 agy。順序是契約的一部分：AC-5 要求參數無效時**不呼叫 agy**，而
# `agy --help` 也是一次 agy 呼叫——把它排在驗證之前，無效參數就得先等 agy 啟動（它若卡住，
# 連錯誤都報不出來）。舊版 agy 不認得 --print-timeout / --log-file，且它對未知 flag 的退出碼
# **也是 2**（實測 `agy --definitely-not-a-flag` → 2），與上方驗證的 exit 2 撞號；不先擋下的話，
# 那個 2 會被當成「agy 執行失敗」原樣轉出，真正的原因（agy 太舊、該升級）沒有任何地方說。
# 退出碼與輸出分開判斷，不用 `AGY_HELP=$(agy --help 2>&1 || true)`：`|| true` 把狀態丟掉後，
# 「agy 在但 --help 因別的原因失敗」（runtime 壞掉、缺 node、未來版本要先認證）會讓 flag 字串
# 自然不在輸出裡，於是腳本回報「版本太舊，請升級」——正是這道 preflight 自己要消滅的那種
# 「可行動但與成因無關」的指示（rule 13「`|| exit 0` / `|| true` Turns a Real Result Into a
# Silent Skip」，該節的錯誤示範字面就是 `agy review ... || true`）。
AGY_HELP_EXIT=0
AGY_HELP=$(agy --help 2>&1) || AGY_HELP_EXIT=$?
if [ "$AGY_HELP_EXIT" -ne 0 ]; then
    echo "[FAIL] agy --help 執行失敗（exit ${AGY_HELP_EXIT}），無法確認它是否支援本腳本需要的 flag。原始輸出：" >&2
    printf '%s\n' "$AGY_HELP" >&2
    exit 2
fi
for flag in --print-timeout --log-file; do
    case "$AGY_HELP" in
        *"$flag"*) ;;
        *)
            echo "[FAIL] 這個 agy 版本不支援 ${flag}，本腳本的 timeout 防線無法運作。" >&2
            echo "       該行為自 agy 1.1.28 起提供，請升級：agy update（或 pip install -U antigravity-cli）。" >&2
            exit 2
            ;;
    esac
done

BOUNDARY="IMPORTANT: 不要讀取或執行 ~/.claude/、~/.agents/、.claude/skills/、agents/ 底下的任何檔案。這些是給另一個 AI 系統（Claude Code）用的 skill 定義，與這次諮詢無關，請完全忽略。專注在這個 repo 的程式碼本身。"

# 沿用 agy-review/scripts/run.sh 已驗證過的安全模式（issue #153 / PR #229 retro）：
# prompt 用 inline 形式當 -p 的值傳入，不用 @file（nested worktree 下 @file 解析失敗會讓 agy
# 靜默進入 agentic 模式）；也不能改用 stdin pipe（-p/--print 不是 boolean，會把下一個 flag
# 當 prompt 吃掉、完全不讀 stdin；agy 1.1.2 起沒有 stdin prompt 通道）。問題本文此時已經是
# 從檔案讀出的一般字串（而非 argv 上的原始 shell 語法），可以安全放進這裡的 $PROMPT_CONTENT。
PROMPT_CONTENT=$(
  printf '%s\n\n' "$BOUNDARY"
  printf '%s\n' "$QUESTION"
)

# 用實際位元組數而非字元數（PR #367 mob review Important：${#PROMPT_CONTENT} 在 UTF-8
# locale 下數的是字元，中文問題會低估約 3 倍，讓這道 ARG_MAX 防線對主打的中文情境失效）。
PROMPT_BYTES=$(printf '%s' "$PROMPT_CONTENT" | wc -c)
if [ "$PROMPT_BYTES" -gt 256000 ]; then
  echo "[FAIL] 問題輸入 ${PROMPT_BYTES}B 超過 256000B inline 上限" >&2
  exit 1
fi

# 空輸出偵測（PR #367 mob review Critical，agy 1.1.8 實測確認）：--sandbox 底下 agy 想
# 主動探索 --add-dir 內容時，可能因 agy 自己的權限系統（與 Claude Code 的設定完全獨立）
# 擋下探索指令；headless 模式沒有終端可以核准，agy 會直接無輸出退出。不偵測的話，這支
# script 會把空白當成「完成的回答」原樣呈現，使用者無法分辨是真的沒問題還是被靜默擋下。
# if 條件本身會豁免 set -e（`if`/`while`/`until` 條件、或 `&&`/`||` 前的指令不受 set -e 管），
# 這裡刻意用 if 包住賦值：agy 非零結束時若直接寫 `OUTPUT=$(...); AGY_EXIT=$?`，set -e 會在
# 賦值那行就中止 script，下面這行 AGY_EXIT=$? 永遠執行不到，[FAIL] 診斷訊息變死碼（實測驗證）。
# --add-dir 必須傳絕對路徑，不可傳相對的 `.`（agy 1.1.22 實測）：agy 1.1.22 不再把相對路徑
# 解析成 active workspace，即使呼叫端已經 cd 到該目錄、且該目錄就在 trustedWorkspaces 清單內。
# 失敗形狀是最惡劣的一種——agy exit 0，回一段 141B 的合理拒答（「目前沒有作用中的 workspace」），
# 或更糟：先聲明沒有 workspace 再給出一個幻覺數字。下面的 exit-code gate 與 20 字元下限都攔不住，
# 於是整份無 context 的回答會被原樣當成諮詢結果呈現。
# 實測（負向對照，agy 1.1.22）：同一個問題、同一個模型、同一組 flag，只變動 --add-dir 形式——
#   --add-dir .                 -> CANNOT_READ「沒有作用中的 workspace」（yibi-stack，在 trust 清單內）
#   --add-dir <絕對路徑>         -> 正確答出檔案行數（同一個 yibi-stack）
#   --add-dir <絕對路徑>         -> 正確答出檔案行數（openab-workspace，不在 trust 清單內）
# 故 trustedWorkspaces 與此失敗無關，唯一的鑑別變數是路徑形式。
#
# stderr 與 agy log 分別落地，失敗時才有依據講出真正原因（agy 1.2.3 實測）：
#   - print timeout 的標記只出現在 stderr：`[agy] print timeout after <N> with turn in progress`
#   - 429 RESOURCE_EXHAUSTED 的指數退避重試**只寫進 log**，stderr/stdout 完全沒有痕跡；
#     consumer 帳號額度用完（`Individual quota reached ... Resets in 89h`）時 agy 會一路重試到
#     print timeout，呼叫端看到的就只是無聲卡住。
# **agy log 一律保留**（連成功路徑也是），因為 `--log-file` 是**改道**不是複製：帶了它之後
# `~/.gemini/antigravity-cli/log/` 不會再有這次執行的紀錄（實測：27253 bytes 落在指定路徑，
# 預設目錄最新檔仍是 15 分鐘前那個）。若成功路徑把它刪掉，「agy 沒讀到檔案卻給出語意完整的
# 回答」這個最危險的形狀——它走的正是成功路徑——就完全查不到任何紀錄。故成功時也印出 log 路徑。
# stderr 暫存檔則相反：內容已經轉出到呼叫端，留著沒有診斷價值，一律由 trap 清掉。
AGY_STDERR_FILE=$(mktemp "${TMPDIR:-/tmp}/agy-consult-stderr.XXXXXX")
AGY_LOG_FILE=$(mktemp "${TMPDIR:-/tmp}/agy-consult-log.XXXXXX")

# stderr 先落地再轉出，是為了讓下方的 timeout 標記判定有東西可 grep；但「只在 agy 返回後才
# cat」會讓腳本被外部砍掉時（Bash tool timeout 是兩份 SKILL.md 自述的頭號失敗成因）agy 的訊息
# 一個字都到不了呼叫端——實測送 SIGTERM 後呼叫端只剩 [INFO] 那行。故改由 trap 補放，並以 flag
# 去重（正常路徑已放過就不重複）。
#
# 這個修法能保證到哪裡，實測後的誠實邊界（別再把它寫得更強）：
#   - **bash 會把訊號處理延後到前景子行程結束**（實測：t=3 送 SIGTERM，腳本在 agy 於 t=10
#     結束後才退出，並補送了 agy 在 t=10 才寫的那行）。所以補送發生在「agy 終於返回」的時刻，
#     不是被砍的當下；呼叫端必須還在讀才看得到。
#   - 真正做事的是 EXIT trap；INT/TERM/HUP 三個是冗餘的第二層，只在訊號於「非前景子行程期間」
#     抵達時才輪到它們（此時 bash 不會延後）。突變測試可證：拆掉 TERM trap，DT-021 仍綠。
#   - harness 若連同 agy 一起砍掉整個 process group，或送 SIGKILL，則兩者都無法補送——已知殘餘，
#     沒有純 shell 的修法。
# 刪檔只掛在 EXIT，不掛在訊號路徑：訊號 handler 若順手 rm，主線接著要讀的同一個檔案就沒了，
# 在 set -e 下腳本會以 rc=1 結束而非 143（實測踩到，SIGTERM 探針抓出來的）。
AGY_STDERR_REPLAYED=0
replay_agy_stderr() {
    if [ "$AGY_STDERR_REPLAYED" -eq 0 ] && [ -s "$AGY_STDERR_FILE" ]; then
        cat "$AGY_STDERR_FILE" >&2
        AGY_STDERR_REPLAYED=1
    fi
}
on_agy_exit() {
    replay_agy_stderr
    rm -f "$AGY_STDERR_FILE"
}
# 退出碼按訊號給（128 + signo）：一支以「講出真正原因」為目的的腳本，不該把 Ctrl-C 回報成
# SIGTERM。呼叫端據此分辨「使用者中斷」與「harness 逾時砍掉」。
on_agy_signal() {
    replay_agy_stderr
    exit "$1"
}
trap on_agy_exit EXIT
trap 'on_agy_signal 130' INT
trap 'on_agy_signal 143' TERM
trap 'on_agy_signal 129' HUP

echo "[INFO] agy 模型：${AGY_MODEL}（可用 AGY_MODEL 環境變數覆寫）" >&2
AGY_START=$SECONDS
if OUTPUT=$(agy -p "$PROMPT_CONTENT" --model "$AGY_MODEL" --add-dir "$REPO_ROOT" --sandbox \
    --print-timeout "${AGY_PRINT_TIMEOUT_SECS}s" --log-file "$AGY_LOG_FILE" 2>"$AGY_STDERR_FILE"); then
    AGY_EXIT=0
else
    AGY_EXIT=$?
fi
AGY_ELAPSED=$((SECONDS - AGY_START))
# agy 自己的訊息（例如 headless 權限自動拒絕的說明）照樣轉給呼叫端，不因落地而被吞掉。
# 此處先放一次，讓它出現在下方 [FAIL] 診斷之前；trap 的去重 flag 使其不會再放第二次。
AGY_STDERR_SNAPSHOT=$(cat "$AGY_STDERR_FILE")
replay_agy_stderr

report_quota_if_any() {
    if grep -q 'RESOURCE_EXHAUSTED' "$AGY_LOG_FILE"; then
        # 用 [INFO] 而非 [FAIL]：log 裡的 429 全是 `attempt N failed ... retrying` 這種重試行，
        # 其中一次退避後成功的重試同樣會命中。若本次失敗另有主因（例如權限被拒），把額度訊息
        # 標成 [FAIL] 會讓它看起來像主因。主因的 [FAIL] 由各分支自己印。
        echo "[INFO] agy log 另有 429 RESOURCE_EXHAUSTED 重試紀錄（可能與本次失敗無關），最後一筆：" >&2
        grep 'RESOURCE_EXHAUSTED' "$AGY_LOG_FILE" | tail -n 1 >&2
        echo "       'Individual quota reached' 是帳號額度用完（訊息內含重置時間），重試無效，請把 agy 切換到另一個登入帳號（例如 GCP 帳號）或等重置；'try again later' 是暫時性容量不足，減少同時執行的 agy 後重試。" >&2
    fi
}

if [ "$AGY_EXIT" -ne 0 ]; then
    echo "[FAIL] agy 執行失敗（exit ${AGY_EXIT}）" >&2
    report_quota_if_any
    echo "       agy log：${AGY_LOG_FILE}" >&2
    exit "$AGY_EXIT"
fi
# timeout 判定用兩個獨立訊號：stderr 標記，或實際耗時已用完預算。後者不依賴 agy 的措辭——
# 標記字串是呈現層、會隨版本改（rule 13 banner-grep），而 exit code 與 JSON status 在此情境
# 都回報成功，沒有更可靠的結構化訊號可用。任一成立就不呈現 stdout：那只是半截回答。
# 用 -gt 而非 -ge：agy 的計時從 language server 啟動後才開始，真正超時的實際耗時必然大於預算；
# -ge 會讓一個剛好在預算邊界（SECONDS 整數進位）完成的正常回答被誤判。
# 但同一個落差反向也成立：一個在 agy 內部剛好於預算尾端**完成**的回答，牆鐘會略微超過預算而
# 被這個訊號攔下。因此只有耗時單獨命中（stderr 沒有標記）時，措辭降為「疑似」，且兩種情況都
# 把被丟棄的輸出落地保存——fail loud 的代價不該是讓使用者連幾分鐘前產出的內容都拿不回來。
AGY_TIMEOUT_REASON=""
case "$AGY_STDERR_SNAPSHOT" in
    *"print timeout after"*) AGY_TIMEOUT_REASON="agy 印出 print timeout 標記" ;;
esac
if [ -z "$AGY_TIMEOUT_REASON" ] && [ "$AGY_ELAPSED" -gt "$AGY_PRINT_TIMEOUT_SECS" ]; then
    AGY_TIMEOUT_REASON="實際耗時超過預算（agy 未印出標記，故為疑似 timeout）"
fi
if [ -n "$AGY_TIMEOUT_REASON" ]; then
    # 用 mktemp 建檔而不是 `> "${AGY_LOG_FILE}.discarded-output"`：後者的權限由 umask 決定，
    # 常見的 umask 022 會產生 0644，同機其他使用者讀得到這段可能含 repo 內容的輸出；
    # mktemp 一律 0600（實測對照：mktemp 檔 -rw-------，衍生檔 -rw-r--r--）。
    AGY_DISCARDED_FILE=$(mktemp "${TMPDIR:-/tmp}/agy-consult-discarded.XXXXXX")
    printf '%s\n' "$OUTPUT" > "$AGY_DISCARDED_FILE"
    echo "[FAIL] agy 在 ${AGY_PRINT_TIMEOUT_SECS} 秒內沒有完成（實際 ${AGY_ELAPSED} 秒）：${AGY_TIMEOUT_REASON}。agy 此時仍 exit 0，其輸出可能只是半截，已不呈現。" >&2
    report_quota_if_any
    echo "       常見原因：問題需要 agy 大量探索檔案（請縮小範圍、直接點名檔案），或 API 額度不足（見上方）。可用 AGY_PRINT_TIMEOUT_SECS 調整，範圍 1-${AGY_PRINT_TIMEOUT_MAX}（再高會被 Claude Code Bash tool 先砍掉）。" >&2
    echo "       agy log：${AGY_LOG_FILE}；被丟棄的輸出：${AGY_DISCARDED_FILE}" >&2
    exit 124
fi
# 這道守門只攔得住「空輸出／極短輸出」這一種形狀，攔不住 agy 帶著完整句子的無 context 回答
# （上方註解的 141B 拒答就是實例，遠超 20 字元）。刻意不補「拒答關鍵字偵測」：那等同 rule 13
# 的 success-banner grep 反模式——措辭會隨版本改，而 exit code 在此完全不帶判決資訊，靠字串比對
# 只會生出另一個假綠。真正的防線是上方的絕對路徑修法（消除成因），這裡保留的是殘餘風險記錄：
# 若日後又看到「語意完整但明顯沒讀到檔案」的回答，先驗 --add-dir 的解析行為，不要改這個門檻。
if [ -z "$OUTPUT" ] || [ "${#OUTPUT}" -lt 20 ]; then
    echo "[FAIL] agy 回傳空白或極短輸出（${#OUTPUT} 字元）。常見原因：--sandbox 底下 agy 想探索周邊檔案時被自己的權限系統擋下（見 ~/.gemini/antigravity-cli/settings.json permissions.allow），headless 模式無法跳出確認框。請簡化問題避免需要額外讀檔，或改用 /agy-review（若有 diff 可看）。" >&2
    report_quota_if_any
    echo "       agy log：${AGY_LOG_FILE}" >&2
    exit 1
fi
# 成功路徑也印出 log 路徑：這是「agy 沒讀到檔案卻答得很完整」這個殘餘風險唯一的追查入口
# （`--log-file` 改道後預設目錄沒有副本）。log 不刪；stderr 暫存檔由 trap 清掉。
echo "[INFO] agy log：${AGY_LOG_FILE}（回答若看起來沒讀到檔案，查此檔）" >&2
printf '%s\n' "$OUTPUT"

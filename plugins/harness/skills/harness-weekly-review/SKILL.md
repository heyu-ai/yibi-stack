---
name: harness-weekly-review
type: exec
scope: global
effort: high
description: >-
  每週 harness 盤點與復盤：用執行期資料（run-hook.sh 的 hook-events 紀錄、transcript、CI failed job／step、
  rules 必載字元）量測每條 rule／hook／CI gate 的觸發率、攔截率、自身錯誤率與耗時，找出可改成機械 gate
  的 rule、少觸發但佔時間的 hook、錯誤率高需修正的 hook、長期 0 失敗或高噪的 gate，並和上週快照比對
  形成改善→檢驗→改善的閉環；可選擇把發現寫進 Mycelium lesson 與 Hindsight。觸發關鍵字：harness 週報、
  每週盤點 rule、hook 有沒有在攔、gate 還有沒有用、hook 執行率、rule 佔 context、rule 改成 gate、
  hook 退役、harness weekly review、harness 復盤。
  一次性的 11 維度靜態評分請改用 /harness-eval；單一維度深挖請改用 /harness-eval-focus；
  把 lessons 升級成 rule 請改用 /lesson-promotion。
---

# Harness Weekly Review

每週回答三個問題，並檢驗上週的建議有沒有被處理、處理後有沒有效：

1. **哪些 rule 可以改成機械 gate／hook，或縮成一行指標**，減少每次必載的 context。
2. **哪些 hook／gate 很少觸發卻佔時間，或長期 0 失敗**：該退役、改寫，還是屬於保險型要保留。
3. **哪些 hook／gate 自己在出錯或訊息沒送達**：例如 exit 2 卻把原因寫到 stdout，agent 只看到
   `No stderr output`。

`/harness-eval` 是一次性的靜態設定評分；本 skill 讀的是**執行期資料**，而且是週對週比對。

## 執行契約（排程安全）

本 skill 可被排程或 webhook 觸發，所以：

- **預設唯讀**：只量測與寫報告。報告與快照寫在目標 repo **主 checkout** 的 `.runtime/harness-review/`
  （gitignored；在 worktree 內執行也寫到主 repo，避免 worktree 刪除後快照鏈斷掉）。
- **寫入需明確要求**：只有呼叫參數含 `--write-lessons` 才寫 Mycelium；含 `--write-hindsight` 才寫 Hindsight。
- **不使用 AskUserQuestion**，不自動修改任何 rule、hook、gate 或 settings。所有「改／退役」都是給人裁決的建議。
- 需要 owner 裁決的項目（同一建議連續 3 週未處理）列在報告最上方，不自行決定。
- **量不到不等於沒問題**：CI 讀取不完整、`--no-ci`、hook-events 未涵蓋觀察期、transcript 觀察期內沒有事件或
  有檔案讀不到、workflow／rule 檔讀不到、gate 失敗無法歸因或上線日期讀不到、rule 候選排名在上限之外時，
  受影響的建議本週不判定；上週的同類建議在報告中列為「本週量不到」，不算已解除。週數在相鄰週原樣保留（不累加）；
  與上次快照之間有缺週時重設為 1（連續週數已中斷）。

## 前置條件

- 目標 repo 的 hook 經 `run-hook.sh` launcher 執行，且 launcher 會寫 `~/.claude/hook-events/<repo>-YYYY-MM.jsonl`
  （yibi-mvp PR #2078 引入）。沒有這份紀錄時仍可執行，但執行率與耗時會標為「量測不完整」，只剩
  transcript（約 30 天保留期）與 CI 資料。
- `gh` 已登入目標 repo；未登入時加 `--no-ci`，報告會註明 CI 未量測，gate-silent／gate-noisy 本週不判定。
- hook 清單只讀 repo 的 `.claude/settings.json` 與 `.claude/settings.local.json`；使用者層
  `~/.claude/settings.json` 註冊的 hook 不在清單內（報告的說明欄會註明）。

## 步驟

### Step 1 — 解析參數與路徑

從載入 skill 時顯示的 base directory 取得 `{{skill_root}}`。`ARG_REPO` 取自呼叫參數 `--repo <path>`；
參數含 `--write-lessons`、`--write-hindsight`、`--no-ci` 時記下，後面步驟使用。

```bash
TARGET_REPO="${ARG_REPO:-$PWD}"
if ! REPO_TOP=$(git -C "$TARGET_REPO" rev-parse --show-toplevel); then echo "[FAIL] ${TARGET_REPO} 不是 git repo" >&2; exit 1; fi
```

快照與報告的位置取**主 repo**（`--git-common-dir` 的上一層），不可用 `--show-toplevel`——在 worktree 內
它回傳的是 worktree 本身：

```bash
if ! GIT_COMMON=$(git -C "$TARGET_REPO" rev-parse --path-format=absolute --git-common-dir); then echo "[FAIL] 無法取得 ${TARGET_REPO} 的 git common dir" >&2; exit 1; fi
```

```bash
MAIN_REPO=$(dirname "$GIT_COMMON")
```

```bash
OUT_DIR="$MAIN_REPO/.runtime/harness-review"
```

```bash
WEEK=$(date -u +%G-W%V)
```

快照與報告寫在 `$MAIN_REPO/.runtime/harness-review/`。本 repo 的 `.gitignore` 已排除 `.runtime/`；
其他 repo 未必如此，先確認會被忽略（不會被忽略時照樣執行，但要在 Step 7 回報提醒使用者加進 `.gitignore`）：

```bash
if ! git -C "$MAIN_REPO" check-ignore -q .runtime/harness-review/snapshot.json; then echo '[WARN] .runtime/harness-review/ 未被 .gitignore 排除，快照會出現在 git status' >&2; fi
```

### Step 2 — 量測

```bash
python3 "{{skill_root}}/scripts/harness_review.py" collect --repo "$REPO_TOP" --days 7 --gate-days 90 --ci-cache "$OUT_DIR/ci-jobs-cache.json" --out "$OUT_DIR/snapshot-$WEEK.json"
```

呼叫參數含 `--no-ci` 時，在上面指令尾端加 `--no-ci`。stdout 是一行 JSON，含 `ci_measured`、`warnings`、`notes`。

| Exit | 意義 | 動作 |
|------|------|------|
| `0` | 沒有 warnings。`notes` 只是說明、不影響 exit code，但可能伴隨本週不判定的類型（例如 `--no-ci` 時 gate-silent／gate-noisy 不判定、gate 無法歸因、舊版 CI 快取已忽略重抓）；判定範圍以快照的 `evaluation` 為準 | 繼續 Step 3；`notes` 列進最終回報 |
| `3` | 快照已寫出，但有資料源讀取失敗、缺漏或未涵蓋觀察期；受影響的建議類型本週不判定 | 繼續 Step 3；`warnings` 原樣列進最終回報，不可省略 |
| `2` | 參數或環境錯誤（非 git repo、`--now` 格式錯） | 原樣回報 stderr，`[FAIL]` 停止 |
| 其他 | script 本身崩潰 | 原樣回報 stderr，`[FAIL]` 停止，不可用舊快照冒充本週結果 |

第一次跑 CI 量測會抓 90 天內所有 failed run 的 jobs（約數百次唯讀 API 呼叫，8 路平行）；
之後的週只抓快取裡沒有的新 run。任何一頁或任何一個 run 讀不完整，`ci_measured` 就是 `false`。

### Step 3 — 產出報告與週對週比對

上週快照由 script 在 `$OUT_DIR` 找（`--prev auto`：檔名排序在本週之前的最後一份 `snapshot-YYYY-Www.json`），
不要自己用 `ls` 找——空目錄與讀取錯誤在 shell 裡分不出來。

```bash
python3 "{{skill_root}}/scripts/harness_review.py" report --snapshot "$OUT_DIR/snapshot-$WEEK.json" --prev auto --out "$OUT_DIR/report-$WEEK.md" --lessons-out "$OUT_DIR/lessons-$WEEK.jsonl"
```

| Exit | 動作 |
|------|------|
| `0` 且 stdout `prev_status` 為 `found` | 繼續 Step 4；`prev` 是這次比對的上週快照路徑 |
| `0` 且 stdout `prev_status` 為 `none` | 第一次執行（`$OUT_DIR` 沒有更早的快照），所有建議都標「新」；繼續 Step 4 並在回報註明 |
| `0` 且 stdout `prev_status` 為 `found_after_skip` | 較新的舊快照版本不符（`skipped_incompatible` 列出路徑），改用更早的一份比對；繼續 Step 4，回報列出略過的快照與實際比對的 `prev` |
| `0` 且 stdout `prev_status` 為 `none_after_skip` | 更早的快照全都版本不符，本週視同第一次執行；繼續 Step 4，回報列出 `skipped_incompatible` |
| `2` | 本週快照不存在、格式或版本不符，或 `$OUT_DIR` 無法讀取：原樣回報 stderr，`[FAIL]` 停止 |
| 其他 | 原樣回報 stderr，`[FAIL]` 停止 |

`report` 會把累計週數與 `carried`（本週量不到而保留的建議）寫回 `snapshot-$WEEK.json`，下週的比對才能接續；
不要在 report 之後再手動改這份快照。

報告把建議分成四桶：**修正**、**減量**、**退役或改寫**、**保留**，每條標「新」或「第 N 週」。
上週有、本週消失的建議分兩種：本週**量得到**才列在「上週建議的處理結果」（已解除，這就是閉環的檢驗結果）；
本週**量不到**的列在「本週量不到的上週建議」，相鄰週時週數原樣保留（不累加）。週數只在上週快照正好是前一個
ISO 週時累加；同一週重跑不累加；中間缺週則所有週數（含量不到而保留的建議）從 1 重新起算，報告會標
「週次不相鄰」（stdout 的 `week_gap`）。

### Step 4 — LLM 判讀（腳本只量測，語意判斷在這裡）

腳本的 rule 候選只是啟發式排序（祈使句數 × min(反引號字面值數, 10)，以及段落是否點名既有 hook／gate），
**不代表能機械化**。逐條讀報告中「減量」與「退役或改寫」桶的前 10 條，打開報告「對象」欄的 `file:line`
讀原文後，依下表**恰好選一格**（真值表，不用「依序比對、取第一個符合」的散文分支）：

| 段落能否被程式判定對錯 | repo 是否已有涵蓋它的 hook／gate | repo 是否已明文裁決「不要做成 gate」 | 判定 |
|---|---|---|---|
| 能 | 有，且涵蓋段落所述 | — | **縮成指標**：段落只留一句規則＋指向 gate 的連結 |
| 能 | 有，但只涵蓋一部分 | — | **擴充既有 gate**：寫出缺的形狀 |
| 能 | 沒有 | 否 | **建議新 gate**：寫出類型（PreToolUse／pre-commit／CI）、判定邏輯一句話、誤判率高低與理由 |
| 能 | 沒有 | 是 | **維持**：引用該裁決原文，不重提 |
| 不能（需語意判斷） | — | — | **維持或搬移**：事故敘事可搬到 docs，規則本身保留 |

`gate-noisy` 另外判斷：失敗是「抓到真問題」（保留）還是「忘了跑某個產生指令」（建議改成 pre-commit
自動產生或 CI 自動修正，並把人工步驟從 rule 移除）。判斷依據是 failed step 名稱與該 gate 的腳本內容，
不是次數本身。

`hook-low-signal`／`gate-silent` 判斷該 hook／gate 守的失效**現在還可能發生嗎**：不可能就建議退役；
可能就保留，並確認有一個會轉紅的 canary 證明它還活著。0 次觸發不等於沒用。

把判讀結果以 `## LLM 判讀` 一節附加到 `$OUT_DIR/report-$WEEK.md` 末尾，每條寫：對象、判定、理由（引原文）、
建議落點（具體檔案與段落，不寫「考慮」「之後再決定」）。判為「維持」的條目記下它在 `lessons-$WEEK.jsonl`
的 `key`，Step 5 排除。

### Step 5 — 寫入 Mycelium（僅 `--write-lessons`）

沒有 `--write-lessons` 時跳過本步驟，Step 7 註明「未寫入 Mycelium」。

`lessons-$WEEK.jsonl` 每行是一筆候選，欄位有 `key`、`type`、`project`、`bucket`、`weeks`、`insight`。
由 script 逐行**序列**呼叫 `mycelium lessons add --skip-if-exists`（list args、不經 shell，insight 裡的
反引號與 `$()` 都是字面值；每筆 60 秒逾時）。Step 4 判為「維持」的條目，每個 key 加一個
`--exclude <key>`（key 必須逐字取自 lesson 檔；對不到的 key 會讓整批一筆都不寫）：

```bash
python3 "{{skill_root}}/scripts/harness_review.py" write-lessons --lessons "$OUT_DIR/lessons-$WEEK.jsonl"
```

| Exit | 意義 | 動作 |
|------|------|------|
| `0` | 全部處理完：新寫入，或依 `--skip-if-exists` 略過已存在的 key | 記下 stdout JSON 的 `written`（新寫入）、`skipped_existing`（已存在而略過）、`excluded`，分開列進 Step 7，不可把略過算成寫入；繼續 Step 6 |
| `1` 且 stderr 有「`--exclude` 的 key 不在 lesson 檔內」 | 一筆都沒寫；Step 4 記下的 key 與 lesson 檔不一致 | 對照 `lessons-$WEEK.jsonl` 修正 key 後重跑本步驟一次；仍失敗就把 `[FAIL]` 列進 Step 7，繼續 Step 6 |
| `1`（其他） | 至少一筆失敗（mycelium 非零 exit、逾時、找不到 `mycelium`、輸出無法確認是否寫入、該行格式錯） | stderr 的 `[FAIL]` 行原樣列進 Step 7 的失敗清單；其餘已寫入的不重寫，繼續 Step 6 |
| `2` | lesson 檔不存在或無法讀取 | 原樣回報 stderr，`[FAIL]` 停止 |
| 其他 | script 本身崩潰 | 原樣回報 stderr，`[FAIL]` 停止 |

`--skip-if-exists` 讓同一條建議不會每週重複寫入；持續幾週由快照的 `weeks` 追蹤，不靠 lessons。
這些 lesson 之後由 distill 聚合，**由人**決定要不要落地成 PR。

### Step 6 — 寫入 Hindsight（僅 `--write-hindsight`）

沒有 `--write-hindsight` 時跳過本步驟，Step 7 註明「未寫入 Hindsight」。

呼叫 MCP `hindsight_ingest_document`：

- `title`：`Harness weekly review <repo> <WEEK>`
- `content`：關鍵指標變化、需 owner 裁決的項目、已解除的建議、本週量不到的建議、Step 4 的判定摘要
  （每條一句、附 `file:line`）

Hindsight 的 bank 以 repo 區分，下週盤點時可以查「上週為什麼決定保留這支 hook」。

| 結果 | 動作 |
|------|------|
| 呼叫成功 | 記下文件 id，列進 Step 7 |
| MCP 工具不存在（未安裝／未連線） | 記 `[FAIL] Hindsight MCP 不可用，本週未寫入 Hindsight`，列進 Step 7；不影響已完成的報告 |
| 呼叫回傳錯誤 | 記 `[FAIL] Hindsight 寫入失敗：<錯誤原文>`，列進 Step 7；不重試、不改寫成 `[SKIP]` |

呼叫參數明確要求了寫入，所以任何沒寫進去的情況都是 `[FAIL]`，不是 `[SKIP]`。

### Step 7 — 回報

回報內容：

- 報告路徑 `$OUT_DIR/report-$WEEK.md`；上週快照路徑，或「第一次執行」
- 需要 owner 裁決的項目（連續 3 週以上）
- 本週新出現的「修正」桶項目
- 上週建議中已解除的項目；本週量不到的項目（週數保留，缺週時重設為 1）
- 週次不相鄰時的 `week_gap`；`--prev auto` 略過的版本不符快照（`skipped_incompatible`）
- Step 1 若印出 `.gitignore` 的 `[WARN]`，提醒使用者把 `.runtime/` 加進 `.gitignore`
- Step 2 的 `warnings`（量測不完整的部分）與 `notes`；`ci_measured` 為 `false` 時明寫「CI 未量測」
- Step 5／6 實際寫入的筆數與所有 `[FAIL]` 清單；沒帶寫入參數時註明「未寫入」

## 門檻（可用 collect 參數調整）

| 參數 | 預設 | 用途 |
|------|------|------|
| `--min-calls` | 20 | 低訊號判定的最少呼叫次數 |
| `--error-rate` | 0.05 | hook 自身錯誤率門檻 |
| `--slow-p95-ms` | 1000 | 慢 hook 門檻（秒級計時時自動提高到 2000） |
| `--slow-total-ms` | 60000 | 觀察期總耗時門檻 |
| `--noisy-failures` | 20 | 單一 CI step 的高噪失敗次數 |
| `--heavy-rule-chars` | 8000 | 每次必載 rule 檔的篇幅門檻 |
| `--min-rule-score` | 12 | rule 段落列為機械化候選的最低分數 |
| `--max-rule-candidates` | 10 | 每週最多列出幾個 rule 段落候選；排名在外的候選本週不判定（不算已解除） |
| `--ignore-jobs` | `/ CI Status$\|ci-status` | 不計入高噪的 rollup job（regex） |

`report`／`diff` 另有 `--escalate-weeks`（預設 3）：同一建議連續幾週未處理就升級為 owner 裁決。

## FAQ

| 問題 | 處理 |
|------|------|
| 報告說 hook-events 找不到 | 目標 repo 的 `run-hook.sh` 還沒有執行紀錄功能；先合併該功能，或接受只有 transcript 與 CI 的報告 |
| 所有 hook 都沒有「低訊號」建議 | 紀錄尚未涵蓋整個觀察期（warnings 會寫最早／最新日期與原因）；最早一筆要早於觀察期起點、最新一筆要在 2 天內 |
| 耗時全是 1000 的倍數 | macOS 系統 bash 3.2 沒有 `EPOCHREALTIME`，只有秒級；慢 hook 門檻已自動提高（列在 notes，不影響 exit code） |
| CI 量測很慢 | 第一次要抓 90 天的 failed run；之後靠 `ci-jobs-cache.json` 只抓新 run（不完整的結果不會進快取） |
| `gh repo view` 失敗 | 在目標 repo 跑 `gh auth status`；暫時加 `--no-ci` |
| gate 一直沒有 gate-silent 判定 | notes 若寫「無法歸因」，看原因：沒有以 `run:` 直接呼叫該 script 的 step（例如包在 `make` 裡）、step 名稱含 `${{ }}` 或是看不懂的 YAML 形狀、或同名 step 也出現在沒有呼叫它的地方；讓呼叫它的 step 有獨一無二的純文字名稱，或接受這支 gate 不做 0 失敗判定 |
| report 的 `prev_status` 是 `found_after_skip`／`none_after_skip` | `$OUT_DIR` 裡有舊版格式的快照（通常是 skill 升級前留下的），`--prev auto` 已略過並往前找；不需處理，確認 `skipped_incompatible` 列的檔案可以刪除後自行清掉即可。`--prev <path>` 明確指定舊版快照仍會 exit 2 |
| notes 寫「CI 快取是舊版或未標版本的格式」 | skill 升級後的第一次執行會忽略舊快取、全部重抓並改寫成新格式；之後的週會恢復只抓新 run |
| 想強制重跑同一週 | 直接重跑 Step 2 與 Step 3，`snapshot-$WEEK.json` 會被覆寫；週數以上週快照為基準，同一週重跑不會累加 |

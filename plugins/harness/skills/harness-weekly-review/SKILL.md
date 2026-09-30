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
- **量不到不等於沒問題**：CI 讀取不完整、`--no-ci`、hook-events 未涵蓋觀察期時，受影響的建議類型本週不判定；
  上週的同類建議在報告中列為「本週量不到」，週數原樣保留，不算已解除。

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

### Step 2 — 量測

```bash
python3 "{{skill_root}}/scripts/harness_review.py" collect --repo "$REPO_TOP" --days 7 --gate-days 90 --ci-cache "$OUT_DIR/ci-jobs-cache.json" --out "$OUT_DIR/snapshot-$WEEK.json"
```

呼叫參數含 `--no-ci` 時，在上面指令尾端加 `--no-ci`。stdout 是一行 JSON，含 `ci_measured`、`warnings`、`notes`。

| Exit | 意義 | 動作 |
|------|------|------|
| `0` | 資料源都讀到；`notes` 可能有資訊性說明（秒級計時、`--no-ci`、gate 無法歸因） | 繼續 Step 3；`notes` 列進最終回報 |
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
| `2` | 快照不存在、格式或版本不符，或 `$OUT_DIR` 無法讀取：原樣回報 stderr，`[FAIL]` 停止 |
| 其他 | 原樣回報 stderr，`[FAIL]` 停止 |

報告把建議分成四桶：**修正**、**減量**、**退役或改寫**、**保留**，每條標「新」或「第 N 週」。
上週有、本週消失的建議分兩種：本週**量得到**才列在「上週建議的處理結果」（已解除，這就是閉環的檢驗結果）；
本週**量不到**的列在「本週量不到的上週建議」，週數原樣保留。週數只在上週快照正好是前一個 ISO 週時累加；
同一週重跑不累加；中間缺週則從 1 重新起算，報告會標「週次不相鄰」（stdout 的 `week_gap`）。

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
`--exclude <key>`：

```bash
python3 "{{skill_root}}/scripts/harness_review.py" write-lessons --lessons "$OUT_DIR/lessons-$WEEK.jsonl"
```

| Exit | 意義 | 動作 |
|------|------|------|
| `0` | 全部寫入，或依 `--skip-if-exists` 略過已存在的 key | 記下 stdout JSON 的 `written`／`excluded`，繼續 Step 6 |
| `1` | 至少一筆失敗（mycelium 非零 exit、逾時、找不到 `mycelium`、該行格式錯） | stderr 的 `[FAIL]` 行原樣列進 Step 7 的失敗清單；其餘已寫入的不重寫，繼續 Step 6 |
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
- 上週建議中已解除的項目；本週量不到的項目（週數保留）
- 週次不相鄰時的 `week_gap`
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
| `--max-rule-candidates` | 10 | 每週最多列出幾個 rule 段落候選 |
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
| gate 一直沒有 gate-silent 判定 | notes 若寫「無法歸因」，代表 workflow 裡沒有以 `run:` 直接呼叫該 script 的 step（例如包在 `make` 裡）；讓 step 直接呼叫 script，或接受這支 gate 不做 0 失敗判定 |
| 想強制重跑同一週 | 直接重跑 Step 2 與 Step 3，`snapshot-$WEEK.json` 會被覆寫；週數以上週快照為基準，同一週重跑不會累加 |

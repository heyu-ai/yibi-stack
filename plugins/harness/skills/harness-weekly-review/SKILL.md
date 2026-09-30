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

- **預設唯讀**：只量測與寫報告。報告與快照寫在目標 repo 的 `.runtime/harness-review/`（gitignored）。
- **寫入需明確要求**：只有呼叫參數含 `--write-lessons` 才寫 Mycelium；含 `--write-hindsight` 才寫 Hindsight。
- **不使用 AskUserQuestion**，不自動修改任何 rule、hook、gate 或 settings。所有「改／退役」都是給人裁決的建議。
- 需要 owner 裁決的項目（同一建議連續 3 週未處理）列在報告最上方，不自行決定。

## 前置條件

- 目標 repo 的 hook 經 `run-hook.sh` launcher 執行，且 launcher 會寫 `~/.claude/hook-events/<repo>-YYYY-MM.jsonl`
  （yibi-mvp PR #2078 引入）。沒有這份紀錄時仍可執行，但執行率與耗時會標為「量測不完整」，只剩
  transcript（約 30 天保留期）與 CI 資料。
- `gh` 已登入目標 repo；未登入時加 `--no-ci`，報告會註明 CI 未量測。

## 步驟

### Step 1 — 解析參數與路徑

從載入 skill 時顯示的 base directory 取得 `{{skill_root}}`。

```bash
TARGET_REPO="${ARG_REPO:-$PWD}"
if ! git -C "$TARGET_REPO" rev-parse --show-toplevel > /dev/null; then echo "[FAIL] $TARGET_REPO 不是 git repo" >&2; exit 1; fi
```

```bash
REPO_TOP=$(git -C "$TARGET_REPO" rev-parse --show-toplevel)
```

```bash
OUT_DIR="$REPO_TOP/.runtime/harness-review"
```

```bash
WEEK=$(date -u +%G-W%V)
```

`ARG_REPO` 取自呼叫參數 `--repo <path>`；參數含 `--write-lessons`、`--write-hindsight`、`--no-ci` 時記下，後面步驟使用。

### Step 2 — 找上週快照

```bash
ls -1 "$OUT_DIR"/snapshot-*.json
```

取檔名排序最後、且不是本週 `snapshot-$WEEK.json` 的那一份當 `PREV`。沒有任何快照代表第一次執行，`PREV` 留空。

### Step 3 — 量測

```bash
python3 "{{skill_root}}/scripts/harness_review.py" collect --repo "$REPO_TOP" --days 7 --gate-days 90 --ci-cache "$OUT_DIR/ci-jobs-cache.json" --out "$OUT_DIR/snapshot-$WEEK.json"
```

呼叫參數含 `--no-ci` 時，在上面指令尾端加 `--no-ci`。

| Exit | 意義 | 動作 |
|------|------|------|
| `0` | 所有資料源都讀到 | 繼續 Step 4 |
| `3` | 快照已寫出，但有資料源讀取失敗 | 繼續 Step 4；stdout JSON 的 `warnings` 原樣列進最終回報，不可省略 |
| `2` | 參數或環境錯誤（非 git repo 等） | 原樣回報 stderr 並停止 |
| 其他 | script 本身崩潰 | 原樣回報 stderr 並停止，不可用舊快照冒充本週結果 |

第一次跑 CI 量測會抓 90 天內所有 failed run 的 jobs（約數百次唯讀 API 呼叫，8 路平行）；
之後的週只抓快取裡沒有的新 run。

### Step 4 — 產出報告與週對週比對

`PREV` 為空字串時腳本視為第一次執行，所以一律帶上：

```bash
python3 "{{skill_root}}/scripts/harness_review.py" report --snapshot "$OUT_DIR/snapshot-$WEEK.json" --prev "$PREV" --out "$OUT_DIR/report-$WEEK.md" --lessons-out "$OUT_DIR/lessons-$WEEK.jsonl"
```

| Exit | 動作 |
|------|------|
| `0` | 繼續 Step 5 |
| `2` | 快照不存在或版本不符：原樣回報並停止 |

報告把建議分成四桶：**修正**、**減量**、**退役或改寫**、**保留**，每條標「新」或「第 N 週」。
上週有、本週消失的建議列在「上週建議的處理結果」，這就是閉環的檢驗結果。

### Step 5 — LLM 判讀（腳本只量測，語意判斷在這裡）

腳本的 rule 候選只是啟發式排序（祈使句數 × 反引號字面值數，以及段落是否點名既有 hook／gate），
**不代表能機械化**。逐條讀報告中「減量」與「退役或改寫」桶的前 10 條，打開 `file:line` 讀原文後，
依下表**恰好選一格**（真值表，不用「依序比對、取第一個符合」的散文分支）：

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
建議落點（具體檔案與段落，不寫「考慮」「之後再決定」）。

### Step 6 — 寫入 Mycelium（僅 `--write-lessons`）

`lessons-$WEEK.jsonl` 每行是一筆候選，欄位有 `key`、`type`、`insight`、`weeks`。逐行**序列**執行
（不要平行寫入）；Step 5 判為「維持」的條目不寫：

```bash
mycelium lessons add --type operational --key "<key>" --insight "<insight>" --confidence 6 --source observed --skill harness-weekly-review --skip-if-exists
```

`--skip-if-exists` 讓同一條建議不會每週重複寫入；持續幾週由快照的 `weeks` 追蹤，不靠 lessons。
非零 exit 時記下 key 與 stderr，繼續下一筆，最後在回報中列出失敗清單。這些 lesson 之後由 distill 聚合，
**由人**決定要不要落地成 PR。

### Step 7 — 寫入 Hindsight（僅 `--write-hindsight`）

呼叫 MCP `hindsight_ingest_document`：

- `title`：`Harness weekly review <repo> <WEEK>`
- `content`：關鍵指標變化、需 owner 裁決的項目、已解除的建議、Step 5 的判定摘要（每條一句、附 `file:line`）

Hindsight 的 bank 以 repo 區分，下週盤點時可以查「上週為什麼決定保留這支 hook」。MCP 不可用時記
`[SKIP] Hindsight MCP 不可用`，不影響其他步驟。

### Step 8 — 回報

回報內容：

- 報告路徑 `$OUT_DIR/report-$WEEK.md`
- 需要 owner 裁決的項目（連續 3 週以上）
- 本週新出現的「修正」桶項目
- 上週建議中已解除的項目
- Step 3 的 warnings（量測不完整的部分）
- Step 6／7 實際寫入的筆數與失敗清單；沒帶寫入參數時註明「未寫入」

## 門檻（可用 collect 參數調整）

| 參數 | 預設 | 用途 |
|------|------|------|
| `--min-calls` | 20 | 低訊號判定的最少呼叫次數 |
| `--error-rate` | 0.05 | hook 自身錯誤率門檻 |
| `--slow-p95-ms` | 1000 | 慢 hook 門檻（秒級計時時自動提高到 2000） |
| `--slow-total-ms` | 60000 | 觀察期總耗時門檻 |
| `--noisy-failures` | 20 | 單一 CI step 的高噪失敗次數 |
| `--heavy-rule-chars` | 8000 | 每次必載 rule 檔的篇幅門檻 |
| `--ignore-jobs` | `/ CI Status$` | 不計入高噪的 rollup job（regex） |

## FAQ

| 問題 | 處理 |
|------|------|
| 報告說 hook-events 找不到 | 目標 repo 的 `run-hook.sh` 還沒有執行紀錄功能；先合併該功能，或接受只有 transcript 與 CI 的報告 |
| 所有 hook 都沒有「低訊號」建議 | 紀錄尚未涵蓋整個觀察期（warnings 會寫最早日期）；累積一週後再看 |
| 耗時全是 1000 的倍數 | macOS 系統 bash 3.2 沒有 `EPOCHREALTIME`，只有秒級；慢 hook 門檻已自動提高 |
| CI 量測很慢 | 第一次要抓 90 天的 failed run；之後靠 `ci-jobs-cache.json` 只抓新 run |
| `gh repo view` 失敗 | 在目標 repo 跑 `gh auth status`；暫時加 `--no-ci` |
| 想強制重跑同一週 | 刪掉 `snapshot-$WEEK.json` 後重跑；persisting 週數以上週快照為基準，不受影響 |

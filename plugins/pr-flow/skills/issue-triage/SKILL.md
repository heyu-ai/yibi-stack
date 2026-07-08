---
name: issue-triage
type: know
scope: global
effort: high
description: >
  GitHub Issue 定期盤點治理（read-only by default）：逐一研判每個 open issue 是否應該
  關閉 / 更新範圍 / 整併 / 更新 label，並產出優先處理排序。核心規則:不看「有沒有相關 PR
  合併」就判定完成，而是把 issue body 拆成獨立症狀逐一對照現有程式碼；綁 openspec/spectra
  change 的以 tasks.md checkbox 為 ground truth；issue 留言明確要求 keep-open 的要尊重。
  預設只產報告，寫入動作（close / comment / relabel）需使用者確認後才執行。
  觸發情境：「盤點 github issue」「檢查 issue 狀態」「哪些 issue 該關閉」「issue triage」
  「清理 issue」「整併 issue」「更新 issue label」「issue 優先排序」「該關掉哪些 issue」。
  這是 **Issue** 盤點治理，不是 PR review——單一 PR 的 review/lifecycle 請改用
  /pr-review-cycle、/pr-cycle-fast、/pr-cycle-deep；單一 PR 收尾回顧請改用 /pr-retro。
---

# Issue Triage — GitHub Issue 定期盤點治理

對一個 repo 的所有 open issue 做系統化盤點：研判每個 issue 該 **關閉 / 更新範圍 /
整併 / 更新 label**，並給出**優先處理排序**。設計目標是把「這次人工盤點 17 個 issue」
的判斷紀律固化成可重複執行的 runbook。

## Usage

```text
/issue-triage              ← 盤點目前 repo 全部 open issue，產出唯讀報告
/issue-triage #<n>         ← 只研判單一 issue
/issue-triage --apply      ← 產報告後，經逐項確認才執行寫入動作
```

---

## Core Contract — Read-only by Default（務必先讀）

本 skill 可能被排程或 webhook 觸發，因此遵守 `.claude/rules/11-skill-authoring.md`
「Scheduled Skills Must Be Zero-Interaction and Read-Only by Default」：

1. **預設唯讀**：不帶 `--apply` 時，只讀 issue + 讀 code + 產出建議報告，**不**執行任何
   `gh issue close / comment / edit`。
2. **寫入需明示 opt-in**：任何 close / relabel / 貼留言 / 整併，只有在使用者明確要求
   （`--apply` 或口頭同意某幾筆）後才執行，且**逐項確認**——不做「全自動一鍵關閉」。
3. **無互動確認步驟**：排程情境下無人回答，此時一律停在報告，不進 Step 8。
4. **判斷不可逆才停**：關閉 issue 本身可 re-open，屬低風險；但「誤關一個其實沒做完的
   issue」會讓工作被遺忘，成本高於留著。存疑一律傾向 KEEP + 留言，而非 CLOSE。

---

## 判斷三原則（本 skill 的核心，來自實戰教訓）

這三條是研判每個 issue 的骨架，Step 3 逐一套用：

| 原則 | 說明 | 反面案例 |
|------|------|----------|
| **P1 逐症狀核對** | issue 標題／內文常打包多個獨立症狀，必須把每個症狀對照**現有程式碼**逐一驗證，不能只看「有沒有相關 PR 合併」 | 某 issue 列了 A、B 兩個 bug，PR 只修了 A 就整個關掉 → B 被遺忘 |
| **P2 tasks.md 為準** | 綁 openspec/spectra change 的 issue，看該 change `tasks.md` 的 checkbox（`[x]`/`[~]`/`[ ]`）比看「某 PR 合併」更準——一個 PR 常同時碰多個 sibling change，只完整實作其一 | PR 同時碰兩個 change，一個全勾完（可關）、一個只建骨架（未完成） |
| **P3 尊重 keep-open** | issue 自身留言若明確標為 backlog / deferred / 「現行行為已足夠可關閉」，要以留言意圖為準，不因部分程式碼有進度就自動關 | 留言說「保留為低優先 backlog」卻被當成「有進度 → 關閉」 |

---

## Step 1 — Environment Check

確認 `gh` 可用且已登入、且目前在有 GitHub remote 的 git repo：

```bash
gh auth status
```

若 `gh auth status` 非零退出（未登入）→ `[FAIL] gh 未登入，請先 gh auth login` 並停止。

```bash
gh repo view --json nameWithOwner
```

若非零退出（非 git repo 或無 GitHub remote）→ `[FAIL] 目前目錄不是 GitHub repo` 並停止。
從回傳 JSON 的 `nameWithOwner` 欄位取 repo slug 供報告使用。

（不用 `-q .nameWithOwner`：inline bash 的 leading-dot jq token `.nameWithOwner` 會被 Claude Code
內建 parser 當成不可解析的 string node 而彈確認框——見 rule 11；欄位少直接讀 JSON 即可。）

---

## Step 2 — Gather Open Issues

一次撈齊所有 open issue 的判斷所需欄位（含 body 與 comments，供 P1/P3 使用）：

```bash
gh issue list --state open --limit 300 --json number,title,labels,body,createdAt,updatedAt,comments,url,assignees,milestone
```

失敗處理：

- 非零退出 → `[FAIL] gh issue list 失敗`，回報錯誤並停止。
- 空清單（`[]`）→ 回報「目前無 open issue」並結束（正常結果，非錯誤）。

> **欄位驗證**：使用任何 `--json` 欄位前先確認存在——`gh issue list --json` 不帶欄位會列出
> 可用 key。打錯欄位名時 `gh issue list --json <bad>` 會印 `Unknown JSON field` 並 **exit 1**
> （fails loud，不是靜默回空），因此上面的「非零退出 → `[FAIL]`」gate 會擋下。
> （CLAUDE.md「gh CLI --json 欄位」gotcha 講的是 `gh pr checks`——該命令對某些欄位回空值；
> 兩者行為不同，勿混用。本命令用到的 `comments` 等欄位皆已驗證為有效、會回完整內容。）

---

## Step 3 — Per-issue Verdict（核心）

對每個 issue 產出一個 verdict，套用上面的三原則。

### 3a. 拆解症狀（P1）

把 issue body 拆成離散的「可驗證主張」清單：

- 每個 bug 症狀 / 每個 checklist 項目 / 每條 AC = 一個獨立主張。
- 標題若含 `+` 或「與」「及」串接多件事，視為多個主張。

### 3b. 蒐集程式碼證據（平行探索）

issue 數量多時，**平行 dispatch 一個唯讀探索 subagent**（不寫檔），一個 agent 批次驗證數個
issue 的症狀是否已在現有程式碼解決——當前 Claude Code 的內建 `Explore` agent 即適用（唯讀、
內建、非本 repo 自有 plugin agent，故不違反 rule 11「global skill 不得 dispatch 本 repo 自有
plugin agent」）。**若當前 harness 沒有可用的內建探索 agent**（agent 名稱因版本而異），改為
lead 就地用 Read/Grep/Glob 驗證即可，不要 dispatch 本 repo 自有的 plugin agent（會破壞 global
可攜性）。

探索 prompt 要求：

- 對每個主張回傳 `DONE / NOT DONE / UNCLEAR` + 一行證據（檔案路徑、函式名、或其不存在）。
- 用 Read/Grep/Glob，**不要**用 bash for-loop 遍歷（見 rule 13 Codebase Research SOP）。
- 只回結論，不要貼大量檔案內容。

### 3c. 檢查 openspec 綁定（P2）

若 issue body 或標題提到某 openspec/spectra change（`openspec/changes/<name>/`）：

用 **Read tool** 讀 `openspec/changes/<name>/tasks.md`（單檔內容讀取用 Read tool，不用 `cat`——
見 rule 13「Prefer Claude Built-in Tools」）。

以 checkbox 狀態為完成度 ground truth：全 `[x]` → 該 change 完成；有 `[ ]`/`[~]` → 未完成。
找不到檔案時可能已 archive，改查 `openspec/changes/archive/` 或 `docs/openspec/changes/`；
**若本體與 archive 皆讀不到 tasks.md，視該綁定 change 為「未完成」，不得 CLOSE**（寧可 KEEP）。

### 3d. 檢查留言意圖訊號（P3）

掃該 issue 的 comments，把留言意圖分成**兩類互斥訊號**（別混為一談）——以留言意圖決定
verdict，不被部分程式碼進度誤導：

- **keep-open 訊號**（傾向不關）：「backlog」「deferred」「低優先」「保留」等 → 導向 KEEP。
- **close-authorization 訊號**（授權關閉）：「現行行為已足夠（可關閉）」「可直接關閉」等
  明確授權 → 且無未解症狀時導向 CLOSE。

3e 決策表分別對應這兩類（keep-open → KEEP 列；close-authorization → 3e 第 3 列的 CLOSE 列）。

### 3e. Verdict 決策表（self-contained）

**先判斷 guard，再依主狀態選唯一一列。** 主狀態（CLOSE / UPDATE-SCOPE / KEEP / MERGE）互斥、
每個 issue 只落一列；**RELABEL 是正交的附加建議**，可疊加在任何主狀態上（例如 UPDATE-SCOPE
的 issue 同時建議補 type label），不佔主狀態列。多主狀態同時成立時的優先序：
**MERGE > CLOSE > UPDATE-SCOPE > KEEP**（先看是否該整併，再看能否關閉，再看是否收斂範圍）。

| # | 條件 | Verdict | 行動 |
|---|------|---------|------|
| **guard** | **任一前置 gh 呼叫失敗** | **STOP** | **先判斷**：回報錯誤並停止，不繼續產出任何 verdict |
| **guard** | **任一症狀 = UNCLEAR（無法從 repo 確認）** | **視同 NOT DONE** | 該 issue 不得 CLOSE；落 KEEP 或 UPDATE-SCOPE，並在留言標明待人工確認的主張 |
| 1 | 與另一 open issue 覆蓋同一主題（見 Step 4） | **MERGE** | 建議合併方向：留一主 issue，另一 `--reason "not planned"` 關閉並在留言指向主 issue |
| 2 | 所有症狀 DONE，且（若綁 change）tasks.md 全 `[x]`，且無 keep-open 反對 | **CLOSE** | 建議 `gh issue comment`（列完成證據）+ `gh issue close --reason completed` |
| 3 | issue 留言有 close-authorization 訊號（「可直接關閉 / 現行行為已足夠」）且無未解症狀 | **CLOSE** | 同上，留言引用該 close-authorization 授權 |
| 4 | 部分症狀 DONE、部分 NOT DONE（打包多件事） | **UPDATE-SCOPE** | 留言標明「哪半做了、哪半沒做」，並收斂標題到剩餘範圍（`gh issue edit --title`），**保持開啟** |
| 5 | 全部症狀 NOT DONE | **KEEP** | 不動作（或僅補一行現況確認留言） |
| 6 | 症狀無法從 repo 內部驗證（需外部環境 / 他人操作 / 純研究） | **KEEP (external)** | 留言說明程式碼面已就緒但驗證在 repo 外，維持開啟 |
| +附加 | 缺 type label / label 過期 / 狀態不符（見 Step 5） | **RELABEL**（正交） | 疊加建議 `gh issue edit --add-label / --remove-label`，不改主狀態 |

> UPDATE-SCOPE 與 KEEP 的差別是**存疑傾向**：只要有任一症狀 NOT DONE 或 UNCLEAR 就**不能**
> CLOSE 整個 issue（P1）。CLOSE 只保留給「全數 DONE」的乾淨情況。

---

## Step 4 — Dedup / Merge Detection

找出覆蓋同一主題、應整併的 issue：

- **交叉引用**：issue body/comments 提到另一 issue 號（`#\d+`），且兩者主題重疊。
- **關鍵詞重疊**：標題／標籤高度重疊（同一模組 + 同一動作）。

輸出建議：保留哪個為主 issue、哪個關閉指向主 issue。**不自動合併**——列入報告待確認。

---

## Step 5 — Label Hygiene

對每個 issue 檢查 label 衛生：

- **缺 type label**：無 `bug`/`enhancement`/`docs` 等分類 → 依 body 建議補。
- **狀態 label 過期**：如標了 `in-progress` 但無近期活動、或已完成卻仍掛 `blocked`。
- **優先級 label**：若 repo 有 `P0`~`P3` 之類 label，對照 Step 6 排序建議校正。

先用 `gh label list --limit 300` 確認該 repo **實際存在**的 label 名稱，再建議——避免建議加一個
不存在的 label（`gh issue edit --add-label` 對不存在 label 會失敗）。**務必加 `--limit`**：
`gh label list` 預設只回 30 個，label 多的 repo 會截斷，害你把存在的 label 誤判成不存在。
`gh label list` 非零退出 → `[WARN] gh label list 失敗，略過所有 RELABEL 建議`（無法確認 label
是否存在，不要盲猜）。

---

## Step 6 — Priority Ranking（heuristic，需校準）

對所有「KEEP / UPDATE-SCOPE」的 issue 給出建議處理順序。用以下訊號綜合排序，**不是硬公式**：

| 訊號 | 高優先 | 低優先 |
|------|--------|--------|
| **嚴重度** | bug / security / 阻塞正常流程 | enhancement / docs / chore |
| **影響範圍（blast radius）** | 被其他 open issue 引用 / 阻塞他人 | 孤立、無下游依賴 |
| **就緒度** | 有清楚 repro / AC，現在就能動手 | 卡在待決策 / 外部依賴 |
| **CP 值** | 低成本、修法明確的 quick win | 高成本、範圍模糊 |
| **時效** | 近期活躍 / 有 deadline | 長期無活動（另評估是否 close-as-stale） |

輸出 3 檔：**P0 立即**、**P1 本週**、**P2 有空再做**（或 repo 既有的優先級語彙）。

> **首次執行請與使用者校準權重**：這五個訊號的相對權重因 repo 而異，第一次跑完先把排序
> 邏輯攤開給使用者對一次，之後再固定。不要一開始就把權重寫死當成客觀事實。

---

## Step 7 — Report（唯讀輸出，預設終點）

**先解析輸出目錄 `$OUT`**（報告與 Step 8 的 body-file 都寫這裡）。`$CLAUDE_JOB_DIR` 只在
background job session 有值；互動式 `/issue-triage` 通常 **unset**，直接用會讓 `--body-file`
路徑展開成 `/close-<n>.md`（絕對路徑打頭）而 file-not-found。因此一律 fallback：

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo（Step 1 應已擋下）" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
mkdir -p "$OUT"
echo "OUT=$OUT"
```

`tmp/issue-triage/`（fallback）是本 skill 的暫存報告目錄——`tmp/` 已在 `.gitignore`，不會被誤
commit（勿改成 repo 根的 `.issue-triage/`，那不是 ignored path）。`git rev-parse` 拆成獨立賦值
（不塞進 `"${...:-$(...)}"` 的雙引號內），避免 rule 13 Quoting Rule 2 的 parser 確認框。
**shell state 不跨 bash call**，Step 7/8 每個用到 `$OUT` 的 bash block 都要重新跑上面三行解析
（與 `REVIEW_DIR` 慣例同）。

用 **Write tool** 把報告寫到 `$OUT/issue-triage-report.md`（多行內容用 Write，不用 heredoc），
結構如下，再於對話中摘要重點：

```text
# Issue Triage — <repo slug> (<date>)

## 建議關閉（CLOSE）
- #<n> <title> — <一行完成證據>

## 建議更新範圍（UPDATE-SCOPE）
- #<n> <title> — 已做：<...>；未做：<...>；建議新標題：<...>

## 建議整併（MERGE）
- #<a> ← #<b>：<兩者為何重疊、保留哪個>

## 建議改 label（RELABEL）
- #<n>：+<label> / -<label>，理由：<...>

## 維持開啟（KEEP）
- #<n> <title> — <為何不動：全未做 / 外部驗證 / backlog>

## 優先處理排序
- P0：#<n>, #<n>
- P1：#<n>, #<n>
- P2：#<n>, ...
```

若 `$OUT` 落在 `$CLAUDE_JOB_DIR`（background job dir），使用者的 shell 讀不到——回報時把重點
**貼進對話**，不要只丟一個 `$CLAUDE_JOB_DIR/...` 路徑給使用者。

**不帶 `--apply` 時，到此為止。**

---

## Step 8 — Execute Writes（opt-in，逐項確認後）

僅在使用者帶 `--apply` 或明確同意某幾筆時執行。**逐一 issue 執行並回報結果**。

**無互動確認者（排程 / webhook）即使帶 `--apply` 也不執行寫入**——停在 Step 7 報告並註明
`--apply` 已忽略（rule 11 scheduled skill 唯讀契約：排程 turn 無人回答確認）。

**失敗 gate（適用 8a–8d 每一個 `gh` 寫入呼叫）**：任一 `gh` 呼叫非零退出 →
`[FAIL] issue #<n> <動作> 失敗`，回報並**跳過該筆**（不影響其他 issue），最後彙總失敗清單。
一個失敗的 title-edit / relabel / close 是**靜默 no-op 的寫入**，必須顯式擋下，不可回報成功。

body-file 路徑用 Step 7 解析的 `$OUT`。**shell state 不跨 bash call**：每個含 `--body-file`
的 bash block 都要在同一個 block 內先重跑 Step 7 的三行 `$OUT` 解析（下方 8a 為範本，8b/8d 同）。

### 8a. 關閉 issue（附完成說明）

`gh issue close` **沒有** `--comment-file` / `--body-file`（誤用會 `exit 1: unknown flag`）。
必拆兩步：先貼留言（用 Write tool 把完成說明寫到 `$OUT/close-<n>.md`），再關閉。`$OUT` 解析與
`gh issue comment` 放**同一個** bash block（否則 `$OUT` 為空、`--body-file` 展開成 `/close-<n>.md`）：

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
gh issue comment <n> --body-file "$OUT/close-<n>.md"
```

```bash
# completed = 真的做完；not planned = 整併/不做了
gh issue close <n> --reason completed
```

### 8b. 更新範圍（UPDATE-SCOPE）

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
gh issue comment <n> --body-file "$OUT/update-<n>.md"
```

```bash
gh issue edit <n> --title "<收斂後標題>"
```

### 8c. 改 label（RELABEL）

```bash
gh issue edit <n> --add-label "<label>" --remove-label "<label>"
```

（`--add-label` 的 label 必須是 Step 5 用 `gh label list` 確認過存在的。）

### 8d. 整併（MERGE）

在被整併 issue 貼留言指向主 issue，再以 `not planned` 關閉：

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
gh issue comment <b> --body-file "$OUT/merge-<b>.md"
```

```bash
gh issue close <b> --reason "not planned"
```

執行完回報：關閉幾筆、更新幾筆、改 label 幾筆、失敗幾筆（附 issue 號）。

---

## FAQ

| 問題 | 處理 |
|------|------|
| `gh issue close --comment-file` 報 `unknown flag` | `gh issue close` 只有 `-c/--comment <string>`，沒有 file flag；產生式多行報告用 `--body-file` 才不必處理 shell 引號／多行跳脫，故拆兩步：先 `gh issue comment --body-file`，再 `gh issue close --reason` |
| `gh issue edit --add-label` 失敗 | 該 label 不存在；先 `gh label list` 確認名稱，或先 `gh label create` |
| `gh issue list --json` 欄位名打錯 | 會印 `Unknown JSON field` 並 **exit 1**（fails loud，非靜默回空），被 Step 2 的非零退出 gate 擋下；使用前先 `gh issue list --json`（不帶欄位）看可用 key。（CLAUDE.md 那條「靜默回空」gotcha 是講 `gh pr checks`，不同命令，別套用） |
| issue 很多、逐一讀 code 很慢 | Step 3b 平行 dispatch 一個唯讀探索 subagent（當前 harness 的內建 `Explore` 即適用；若無則 lead 就地用 Read/Grep/Glob），批次驗證數個 issue 的症狀 |
| 綁的 openspec change 找不到 tasks.md | 可能已 archive → 查 `openspec/changes/archive/` 或 `docs/openspec/changes/` |
| 該不該 close-as-stale | 長期無活動但症狀仍成立 → KEEP 並降優先，不要純因「舊」就關；close-as-stale 需使用者確認 |
| 排程情境無人確認 | 停在 Step 7 報告，不進 Step 8（rule 11 scheduled skill 唯讀契約） |
| 這跟 /pr-retro、/pr-review-cycle 有何不同 | 那些針對**單一 PR** 的 review/lifecycle/回顧；本 skill 針對 repo **全部 open issue** 的盤點治理 |

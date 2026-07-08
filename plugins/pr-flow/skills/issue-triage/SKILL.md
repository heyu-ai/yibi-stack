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
gh repo view --json nameWithOwner -q .nameWithOwner
```

若非零退出（非 git repo 或無 GitHub remote）→ `[FAIL] 目前目錄不是 GitHub repo` 並停止。
記下 repo slug 供報告使用。

---

## Step 2 — Gather Open Issues

一次撈齊所有 open issue 的判斷所需欄位（含 body 與 comments，供 P1/P3 使用）：

```bash
gh issue list --state open --limit 300 --json number,title,labels,body,createdAt,updatedAt,comments,url,assignees,milestone
```

失敗處理：

- 非零退出 → `[FAIL] gh issue list 失敗`，回報錯誤並停止。
- 空清單（`[]`）→ 回報「目前無 open issue」並結束（正常結果，非錯誤）。

> **欄位驗證**：使用任何 `--json` 欄位前先確認存在（`gh issue list --json` 不帶欄位會列出
> 可用 key）。傳不存在的欄位會**靜默回空值**，不報錯——見 CLAUDE.md「gh CLI --json 欄位」gotcha。

---

## Step 3 — Per-issue Verdict（核心）

對每個 issue 產出一個 verdict，套用上面的三原則。

### 3a. 拆解症狀（P1）

把 issue body 拆成離散的「可驗證主張」清單：

- 每個 bug 症狀 / 每個 checklist 項目 / 每條 AC = 一個獨立主張。
- 標題若含 `+` 或「與」「及」串接多件事，視為多個主張。

### 3b. 蒐集程式碼證據（平行 Explore）

issue 數量多時，**平行 dispatch 內建 `Explore` subagent**（唯讀，不寫檔），一個 agent
批次驗證數個 issue 的症狀是否已在現有程式碼解決。這是內建 agent，global skill 可用
（不違反 rule 11「global skill 不得 dispatch 本 repo 自有 plugin agent」）。

Explore agent prompt 要求：

- 對每個主張回傳 `DONE / NOT DONE / UNCLEAR` + 一行證據（檔案路徑、函式名、或其不存在）。
- 用 Read/Grep/Glob，**不要**用 bash for-loop 遍歷（見 rule 13 Codebase Research SOP）。
- 只回結論，不要貼大量檔案內容。

### 3c. 檢查 openspec 綁定（P2）

若 issue body 或標題提到某 openspec/spectra change（`openspec/changes/<name>/`）：

```bash
cat openspec/changes/<name>/tasks.md
```

以 checkbox 狀態為完成度 ground truth：全 `[x]` → 該 change 完成；有 `[ ]`/`[~]` → 未完成。
（找不到檔案時可能已 archive，改查 `openspec/changes/archive/` 或 `docs/openspec/changes/`。）

### 3d. 檢查 keep-open 訊號（P3）

掃該 issue 的 comments：有「backlog」「deferred」「低優先」「保留」「現行行為已足夠」
「可直接關閉」等語意時，以留言意圖決定 verdict，不被部分程式碼進度誤導。

### 3e. Verdict 決策表（self-contained）

依 3a–3d 結果，每個 issue 落到**唯一**一列：

| 條件 | Verdict | 行動 |
|------|---------|------|
| 所有症狀 DONE，且（若綁 change）tasks.md 全 `[x]`，且無 keep-open 反對 | **CLOSE** | 建議 `gh issue comment`（列完成證據）+ `gh issue close --reason completed` |
| issue 留言明確說「現行行為已足夠 / 可關閉」且無未解症狀 | **CLOSE** | 同上，留言引用該 keep-open→close 授權 |
| 部分症狀 DONE、部分 NOT DONE（打包多件事） | **UPDATE-SCOPE** | 留言標明「哪半做了、哪半沒做」，並收斂標題到剩餘範圍（`gh issue edit --title`），**保持開啟** |
| 全部症狀 NOT DONE | **KEEP** | 不動作（或僅補一行現況確認留言） |
| 與另一 open issue 覆蓋同一主題（見 Step 4） | **MERGE** | 建議合併方向：留一主 issue，另一 `--reason "not planned"` 關閉並在留言指向主 issue |
| 缺 type label / label 過期 / 狀態不符（見 Step 5） | **RELABEL** | 建議 `gh issue edit --add-label / --remove-label` |
| 症狀無法從 repo 內部驗證（需外部環境 / 他人操作 / 純研究） | **KEEP (external)** | 留言說明程式碼面已就緒但驗證在 repo 外，維持開啟 |
| 任一 gh 呼叫失敗 | **STOP** | 先回報錯誤，不進 count 判斷 |

> UPDATE-SCOPE 與 KEEP 的差別是**存疑傾向**：只要有任一症狀 NOT DONE 就**不能** CLOSE
> 整個 issue（P1）。CLOSE 只保留給「全數 DONE」的乾淨情況。

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

先用 `gh label list` 確認該 repo **實際存在**的 label 名稱，再建議——避免建議加一個不存在的 label
（`gh issue edit --add-label` 對不存在 label 會失敗）。

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

用 **Write tool** 把報告寫到 `$CLAUDE_JOB_DIR/issue-triage-report.md`（多行內容用 Write，
不用 heredoc），結構如下，再於對話中摘要重點：

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

`$CLAUDE_JOB_DIR` 是 agent job dir，使用者的 shell 讀不到——回報時把重點**貼進對話**，
不要只丟一個 `$CLAUDE_JOB_DIR/...` 路徑給使用者。

**不帶 `--apply` 時，到此為止。**

---

## Step 8 — Execute Writes（opt-in，逐項確認後）

僅在使用者帶 `--apply` 或明確同意某幾筆時執行。**逐一 issue 執行並回報結果**。

### 8a. 關閉 issue（附完成說明）

`gh issue close` **沒有** `--comment-file` / `--body-file`（誤用會 `exit 1: unknown flag`）。
必拆兩步：先貼留言，再關閉。

```bash
# 1) 用 Write tool 把完成說明寫到 $CLAUDE_JOB_DIR/close-<n>.md，再貼留言
gh issue comment <n> --body-file "$CLAUDE_JOB_DIR/close-<n>.md"
```

```bash
# 2) 關閉（completed = 真的做完；not planned = 整併/不做了）
gh issue close <n> --reason completed
```

每步非零退出 → `[FAIL] issue #<n> <動作> 失敗`，回報並跳過該 issue（不影響其他筆）。

### 8b. 更新範圍（UPDATE-SCOPE）

```bash
gh issue comment <n> --body-file "$CLAUDE_JOB_DIR/update-<n>.md"
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
gh issue comment <b> --body-file "$CLAUDE_JOB_DIR/merge-<b>.md"
```

```bash
gh issue close <b> --reason "not planned"
```

執行完回報：關閉幾筆、更新幾筆、改 label 幾筆、失敗幾筆（附 issue 號）。

---

## FAQ

| 問題 | 處理 |
|------|------|
| `gh issue close --comment-file` 報 `unknown flag` | `gh issue close` 只有 `-c/--comment <string>`；要貼多行說明拆兩步：先 `gh issue comment --body-file`，再 `gh issue close --reason` |
| `gh issue edit --add-label` 失敗 | 該 label 不存在；先 `gh label list` 確認名稱，或先 `gh label create` |
| `--json` 欄位回空值不報錯 | 欄位名打錯會靜默回空；先 `gh issue list --json`（不帶欄位）看可用 key |
| issue 很多、逐一讀 code 很慢 | Step 3b 平行 dispatch 內建 `Explore` agent，一個 agent 批次驗證數個 issue 的症狀 |
| 綁的 openspec change 找不到 tasks.md | 可能已 archive → 查 `openspec/changes/archive/` 或 `docs/openspec/changes/` |
| 該不該 close-as-stale | 長期無活動但症狀仍成立 → KEEP 並降優先，不要純因「舊」就關；close-as-stale 需使用者確認 |
| 排程情境無人確認 | 停在 Step 7 報告，不進 Step 8（rule 11 scheduled skill 唯讀契約） |
| 這跟 /pr-retro、/pr-review-cycle 有何不同 | 那些針對**單一 PR** 的 review/lifecycle/回顧；本 skill 針對 repo **全部 open issue** 的盤點治理 |

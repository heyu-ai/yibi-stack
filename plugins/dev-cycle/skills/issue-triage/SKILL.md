---
name: issue-triage
type: know
scope: global
effort: high
description: >
  GitHub Issue + Jira Bug 定期盤點治理（read-only by default）：逐一研判每個 open
  issue / bug 是否應該關閉 / 更新範圍 / 整併 / 更新 label，並產出優先處理排序。
  核心規則:不看「有沒有相關 PR 合併」就判定完成，而是把 issue body 拆成獨立症狀逐一
  對照現有程式碼；綁 openspec/spectra change 的以 tasks.md checkbox 為 ground truth；
  issue 留言明確要求 keep-open 的要尊重。
  預設只產報告，寫入動作（close / comment / relabel / transition）需使用者確認後才執行。
  觸發情境：「盤點 github issue」「檢查 issue 狀態」「哪些 issue 該關閉」「issue triage」
  「清理 issue」「整併 issue」「更新 issue label」「issue 優先排序」「該關掉哪些 issue」
  「盤點 jira bug」「jira bug triage」「哪些 jira bug 該關」。
  這是 **Issue** 盤點治理，不是 PR review——單一 PR 的 review/lifecycle 請改用
  /pr-review-cycle、/pr-cycle-fast、/pr-cycle-deep；單一 PR 收尾回顧請改用 /pr-retro。
---

# Issue Triage — GitHub Issue + Jira Bug 定期盤點治理

對一個 repo 的所有 open GitHub issue **加上** 指定 Jira 專案的 open Bug 做系統化盤點：
研判每個 issue / bug 該 **關閉 / 更新範圍 / 整併 / 更新 label**，
並給出**優先處理排序**。設計目標是把「這次人工盤點 17 個 issue + 5 個 Jira bug」
的判斷紀律固化成可重複執行的 runbook。

## Usage

```text
/issue-triage                       <- 盤點目前 repo 全部 open GitHub issue，產出唯讀報告
/issue-triage --jira <PROJECT>      <- 同上，加上指定 Jira 專案的 open Bug
/issue-triage --jira YB             <- 範例：盤點 GitHub issue + YB 專案 Jira Bug
/issue-triage #<n>                  <- 只研判單一 GitHub issue
/issue-triage --jira YB YB-<n>     <- 只研判單一 Jira bug
/issue-triage --apply               <- 產報告後，經逐項確認才執行寫入動作
/issue-triage --jira YB --apply    <- GitHub + Jira 都盤點，且經確認後執行寫入
```

---

## Core Contract — Read-only by Default

本 skill 可能被排程或 webhook 觸發，因此遵守 `.claude/rules/11-skill-authoring.md`
「Scheduled Skills Must Be Zero-Interaction and Read-Only by Default」：

1. **預設唯讀**：不帶 `--apply` 時，只讀 issue/bug + 讀 code + 產出建議報告，**不**執行
   任何 `gh issue close / comment / edit` 或 Jira transition / comment。
2. **寫入需明示 opt-in**：任何 close / relabel / 貼留言 / 整併 / Jira transition，
   只有在使用者明確要求（`--apply` 或口頭同意某幾筆）後才執行，且**逐項確認**。
3. **無互動確認步驟**：排程情境下無人回答，此時一律停在報告，不進 Step 8。
4. **判斷不可逆才停**：關閉 issue 本身可 re-open，屬低風險；但「誤關一個其實沒做完的
   issue」會讓工作被遺忘，成本高於留著。存疑一律傾向 KEEP + 留言，而非 CLOSE。
5. **Jira 寫入受 hook 保護**：若 repo 有 `pre-jira-write.sh` hook（如 yibi-mvp），
   Atlassian MCP 的寫入呼叫會被 hook 機械攔截——本 skill 不繞過該 hook。

---

## 判斷三原則（核心，GitHub issue 與 Jira bug 同樣適用）

| 原則 | 說明 | 反面案例 |
|------|------|----------|
| **P1 逐症狀核對** | issue 標題/內文常打包多個獨立症狀，必須把每個症狀對照**現有程式碼**逐一驗證，不能只看「有沒有相關 PR 合併」 | 某 issue 列了 A、B 兩個 bug，PR 只修了 A 就整個關掉 -> B 被遺忘 |
| **P2 tasks.md 為準** | 綁 openspec/spectra change 的 issue，看該 change `tasks.md` 的 checkbox（`[x]`/`[~]`/`[ ]`）比看「某 PR 合併」更準 | PR 同時碰兩個 change，一個全勾完（可關）、一個只建骨架 |
| **P3 尊重 keep-open** | issue 自身留言若明確標為 backlog / deferred / keep-open，要以留言意圖為準 | 留言說「保留為低優先 backlog」卻被當成「有進度 -> 關閉」 |

> **Jira bug 的 P2 調整**：Jira bug 通常不直接綁 openspec change。若 Jira bug
> description 或 comment 引用了某 GitHub issue 或 openspec change，則以該 GitHub
> issue / change 的 tasks.md 為 ground truth。否則以 Jira bug 自身的 AC / description
> 為逐症狀核對依據。

---

## Step 1 — Environment Check

### 1a. GitHub（必要）

確認 `gh` 可用且已登入、且目前在有 GitHub remote 的 git repo：

```bash
gh auth status
```

若非零退出（未登入）-> `[FAIL] gh 未登入，請先 gh auth login` 並停止。

```bash
gh repo view --json nameWithOwner
```

若非零退出 -> `[FAIL] 目前目錄不是 GitHub repo` 並停止。
從回傳 JSON 的 `nameWithOwner` 欄位取 repo slug 供報告使用。

### 1b. Jira（僅在 `--jira` 時）

使用 Atlassian MCP 查詢 Jira bug。先用 ToolSearch 載入所需工具：

```text
ToolSearch "select:mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql,mcp__claude_ai_Atlassian__getJiraIssue,mcp__claude_ai_Atlassian__addCommentToJiraIssue,mcp__claude_ai_Atlassian__transitionJiraIssue,mcp__claude_ai_Atlassian__getTransitionsForJiraIssue,mcp__claude_ai_Atlassian__editJiraIssue,mcp__claude_ai_Atlassian__getAccessibleAtlassianResources"
```

然後用 `getAccessibleAtlassianResources` 取得 `cloudId`：

```text
getAccessibleAtlassianResources()
```

若 MCP 工具無法載入（ToolSearch 回 no match、或 MCP server 未連線）->
`[WARN] Atlassian MCP 不可用，略過 Jira bug 盤點` 並繼續只做 GitHub issue 盤點。

從 `getAccessibleAtlassianResources` 回傳中找到對應站台的 `id`（即 `cloudId`），
記下供後續 Jira API 呼叫使用。

---

## Step 2 — Gather Open Issues / Bugs

### 2a. GitHub Issues

一次撈齊所有 open issue 的判斷所需欄位（含 body 與 comments，供 P1/P3 使用）：

```bash
gh issue list --state open --limit 300 --json number,title,labels,body,createdAt,updatedAt,comments,url,assignees,milestone
```

失敗處理：

- 非零退出 -> `[FAIL] gh issue list 失敗`，回報錯誤並停止。
- 空清單（`[]`）-> 回報「目前無 open GitHub issue」，繼續 Jira 盤點（若有）。

> **欄位驗證**：使用任何 `--json` 欄位前先確認存在——打錯欄位名時 `gh issue list --json <bad>`
> 會印 `Unknown JSON field` 並 **exit 1**（fails loud）。

### 2b. Jira Bugs（僅在 `--jira` 時）

用 `searchJiraIssuesUsingJql` 查詢指定專案的 open Bug：

```text
searchJiraIssuesUsingJql({
  cloudId: "<cloudId from Step 1b>",
  jql: "project = <PROJECT> AND type = Bug AND statusCategory != Done ORDER BY updated DESC",
  fields: ["summary", "status", "priority", "assignee", "created", "updated", "description", "comment", "labels", "components", "resolution"],
  responseContentFormat: "markdown"
})
```

> **JQL 限制**：某些 Jira 站台（如 heyuai.atlassian.net）安裝了 JQL 限制 app，
> 純 `ORDER BY` 或 `updated >= -30d` 會被擋「無限制查詢」。必須帶 `project=` 子句。
>
> **Token 成本提醒**：Atlassian MCP 回傳完整 JSON（含 self/webUrl/statusCategory 物件等
> 膨脹欄位），15 筆 Jira issue 約 74K 字元。若 bug 數量多，考慮分批查詢或限制筆數。

失敗處理：

- MCP 呼叫失敗 -> `[WARN] Jira bug 查詢失敗`，回報錯誤，繼續 GitHub 盤點。
- 空結果 -> 回報「Jira `PROJECT` 無 open Bug」，繼續。

若需要查看單一 Jira bug 的詳細資訊（description 被截斷時），用 `getJiraIssue`：

```text
getJiraIssue({
  cloudId: "<cloudId>",
  issueIdOrKey: "YB-123",
  responseContentFormat: "markdown"
})
```

---

## Step 3 — Per-issue Verdict（核心）

對每個 GitHub issue **與** Jira bug 產出一個 verdict，套用上面的三原則。
**GitHub issue 與 Jira bug 使用同一套 verdict 決策表（3e）**，差異僅在蒐證方式。

### 3a. 拆解症狀（P1）

把 issue/bug body 拆成離散的「可驗證主張」清單：

- 每個 bug 症狀 / 每個 checklist 項目 / 每條 AC = 一個獨立主張。
- 標題若含 `+` 或「與」「及」串接多件事，視為多個主張。
- **Jira bug**：description + acceptance criteria 欄位都要掃。

### 3b. 蒐集程式碼證據（平行探索）

issue/bug 數量多時，**平行 dispatch 一個唯讀探索 subagent**（不寫檔），
批次驗證數個 issue/bug 的症狀是否已在現有程式碼解決。

探索 prompt 要求：

- 對每個主張回傳 `DONE / NOT DONE / UNCLEAR` + 一行證據。
- 用 Read/Grep/Glob，**不要**用 bash for-loop 遍歷。
- 只回結論，不要貼大量檔案內容。

### 3c. 檢查 openspec 綁定（P2）

若 issue body、Jira bug description 或 comment 提到某 openspec/spectra change：

用 **Read tool** 讀 `openspec/changes/<name>/tasks.md`。
以 checkbox 狀態為完成度 ground truth。找不到時查 archive。
**若本體與 archive 皆讀不到 tasks.md，視為「未完成」，不得 CLOSE**。

### 3d. 檢查留言意圖訊號（P3）

掃該 issue 的 comments（GitHub）或 Jira bug 的 comment（MCP 回傳），
把留言意圖分成**兩類互斥訊號**：

- **keep-open 訊號**：「backlog」「deferred」「低優先」「保留」等 -> 導向 KEEP。
- **close-authorization 訊號**：「可直接關閉」「已修復可關」等 -> 且無未解症狀時導向 CLOSE。

### 3e. Verdict 決策表（GitHub issue 與 Jira bug 共用）

**先判斷 guard，再依主狀態選唯一一列。** 主狀態互斥、每個 issue/bug 只落一列；
**RELABEL 是正交的附加建議**，可疊加在任何主狀態上。
多主狀態同時成立時的優先序：**MERGE > CLOSE > UPDATE-SCOPE > KEEP**。

| # | 條件 | Verdict | 行動 |
|---|------|---------|------|
| **guard** | **任一前置呼叫失敗** | **STOP** | 回報錯誤並停止 |
| **guard** | **任一症狀 = UNCLEAR** | **視同 NOT DONE** | 不得 CLOSE；落 KEEP 或 UPDATE-SCOPE |
| 1 | 與另一 open issue/bug 覆蓋同一主題（含跨系統） | **MERGE** | 建議合併方向 |
| 2 | 所有症狀 DONE，且（若綁 change）tasks.md 全 `[x]`，且無 keep-open | **CLOSE** | GitHub: comment + close；Jira: comment + transition to Done |
| 3 | 留言有 close-authorization 且無未解症狀 | **CLOSE** | 同上 |
| 4 | 部分症狀 DONE、部分 NOT DONE | **UPDATE-SCOPE** | 留言標明已做/未做，收斂標題到剩餘範圍 |
| 5 | 全部症狀 NOT DONE | **KEEP** | 不動作 |
| 6 | 症狀無法從 repo 內部驗證 | **KEEP (external)** | 留言說明程式碼面已就緒但驗證在 repo 外 |
| +附加 | 缺 type label / label 過期 / 狀態不符 | **RELABEL**（正交） | 疊加建議改 label/component |

---

## Step 4 — Dedup / Merge Detection

找出覆蓋同一主題、應整併的 issue/bug：

- **同系統交叉引用**：GitHub issue body/comments 提到另一 issue 號；Jira bug 引用另一 Jira key。
- **跨系統交叉引用**：GitHub issue 提到 Jira key（如 `YB-123`）；Jira bug description 含
  GitHub issue URL 或 `#<n>` 引用。
- **關鍵詞重疊**：標題/標籤高度重疊（同一模組 + 同一動作）。

輸出建議：保留哪個為主 issue、哪個關閉指向主 issue。
**跨系統整併建議保留有較完整 AC / 留言討論的那一邊為主**。不自動合併——列入報告待確認。

---

## Step 5 — Label / Component Hygiene

### 5a. GitHub Label

對每個 GitHub issue 檢查 label 衛生：

- **缺 type label**：無 `bug`/`enhancement`/`docs` 等分類 -> 依 body 建議補。
- **狀態 label 過期**：如標了 `in-progress` 但無近期活動。
- **優先級 label**：若 repo 有 `P0`~`P3` 之類 label，對照 Step 6 排序建議校正。

先用 `gh label list --limit 300` 確認該 repo **實際存在**的 label 名稱，再建議。
`gh label list` 非零退出 -> `[WARN] gh label list 失敗，略過所有 RELABEL 建議`。

### 5b. Jira Bug Label / Component / Priority

對每個 Jira bug 檢查：

- **缺 component**：Jira bug 沒有指定 component -> 依 description 建議補。
- **priority 不符**：priority 與實際影響不符（如 P3 標了 Blocker）-> 建議調整。
- **label 衛生**：有無過期或矛盾的 label。

> 不建議修改 Jira 的 `fixVersion`——版本管理歸 PM/PO 裁決。

---

## Step 6 — Priority Ranking

對所有「KEEP / UPDATE-SCOPE」的 issue/bug 給出建議處理順序（GitHub + Jira 合併排序）：

| 訊號 | 高優先 | 低優先 |
|------|--------|--------|
| **嚴重度** | bug / security / 阻塞正常流程 | enhancement / docs / chore |
| **影響範圍** | 被其他 open issue 引用 / 阻塞他人 | 孤立、無下游依賴 |
| **就緒度** | 有清楚 repro / AC，現在就能動手 | 卡在待決策 / 外部依賴 |
| **CP 值** | 低成本、修法明確的 quick win | 高成本、範圍模糊 |
| **時效** | 近期活躍 / 有 deadline | 長期無活動 |

輸出 3 檔：**P0 立即**、**P1 本週**、**P2 有空再做**。
**GitHub issue 與 Jira bug 混合排序**——不分開排。

> **首次執行請與使用者校準權重**：五個訊號的相對權重因 repo 而異。

---

## Step 7 — Report

**先解析輸出目錄 `$OUT`**：

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
mkdir -p "$OUT"
echo "OUT=$OUT"
```

用 **Write tool** 把報告寫到 `$OUT/issue-triage-report.md`，結構如下：

```text
# Issue Triage -- <repo slug> (<date>)

## 來源
- GitHub: <repo slug>, <N> open issues
- Jira: <PROJECT>, <M> open bugs（若有）

## 建議關閉（CLOSE）

### GitHub Issues
- #<n> <title> -- <一行完成證據>

### Jira Bugs
- <KEY> <summary> -- <一行完成證據>；建議 transition: <target status>

## 建議更新範圍（UPDATE-SCOPE）

### GitHub Issues
- #<n> <title> -- 已做：<...>；未做：<...>；建議新標題：<...>

### Jira Bugs
- <KEY> <summary> -- 已做：<...>；未做：<...>

## 建議整併（MERGE）
- #<a> <- #<b>：<兩者為何重疊、保留哪個>
- #<a> <- <KEY>：<跨系統重疊，建議保留哪邊>

## 建議改 label（RELABEL）

### GitHub Issues
- #<n>：+<label> / -<label>，理由：<...>

### Jira Bugs
- <KEY>：建議改 priority / component / label：<...>

## 維持開啟（KEEP）

### GitHub Issues
- #<n> <title> -- <為何不動>

### Jira Bugs
- <KEY> <summary> -- <為何不動>

## 優先處理排序（GitHub + Jira 混合）
- P0：#<n>, <KEY>, ...
- P1：#<n>, <KEY>, ...
- P2：#<n>, ...
```

若 `$OUT` 落在 `$CLAUDE_JOB_DIR`（background job dir），回報時把重點**貼進對話**。

**不帶 `--apply` 時，到此為止。**
**不帶 `--jira` 時，報告省略所有 Jira Bugs 段落。**

---

## Step 8 — Execute Writes（opt-in，逐項確認後）

僅在使用者帶 `--apply` 或明確同意某幾筆時執行。**逐一 issue/bug 執行並回報結果**。

**無互動確認者（排程 / webhook）即使帶 `--apply` 也不執行寫入**——停在 Step 7。

**失敗 gate**：任一寫入呼叫失敗 -> `[FAIL] <issue/bug> <動作> 失敗`，
回報並**跳過該筆**，最後彙總失敗清單。

body-file 路徑用 Step 7 解析的 `$OUT`。**shell state 不跨 bash call**：
每個含 `--body-file` 的 bash block 都要在同一個 block 內先重跑 `$OUT` 解析。

### 8a. 關閉 GitHub issue（附完成說明）

先貼留言（用 Write tool 把完成說明寫到 `$OUT/close-<n>.md`），再關閉。
`$OUT` 解析與 `gh issue comment` 放**同一個** bash block：

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
mkdir -p "$OUT"
gh issue comment <n> --body-file "$OUT/close-<n>.md"
```

```bash
gh issue close <n> --reason completed
```

### 8b. 更新範圍（GitHub UPDATE-SCOPE）

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
mkdir -p "$OUT"
gh issue comment <n> --body-file "$OUT/update-<n>.md"
```

```bash
gh issue edit <n> --title "<收斂後標題>"
```

### 8c. 改 GitHub label（RELABEL）

```bash
gh issue edit <n> --add-label "<label>" --remove-label "<label>"
```

### 8d. 整併 GitHub issue（MERGE）

```bash
if ! TOP=$(git rev-parse --show-toplevel); then echo "[FAIL] 不在 git repo" >&2; exit 1; fi
OUT="${CLAUDE_JOB_DIR:-$TOP/tmp/issue-triage}"
mkdir -p "$OUT"
gh issue comment <b> --body-file "$OUT/merge-<b>.md"
```

```bash
gh issue close <b> --reason "not planned"
```

### 8e. 關閉 Jira bug（transition to Done + 留言）

先貼留言說明完成證據，再 transition。

**Step 1**：用 `getTransitionsForJiraIssue` 取得可用 transition：

```text
getTransitionsForJiraIssue({
  cloudId: "<cloudId>",
  issueIdOrKey: "<KEY>"
})
```

從回傳中找到目標 transition（如 "Done"、"Closed"、"Resolved"）的 `id`。
若找不到合適的 transition -> `[WARN] <KEY> 無可用的關閉 transition，略過`。

**Step 2**：貼留言：

```text
addCommentToJiraIssue({
  cloudId: "<cloudId>",
  issueIdOrKey: "<KEY>",
  commentBody: "<完成證據摘要>",
  contentFormat: "markdown"
})
```

**Step 3**：執行 transition：

```text
transitionJiraIssue({
  cloudId: "<cloudId>",
  issueIdOrKey: "<KEY>",
  transition: { "id": "<transition id from Step 1>" }
})
```

### 8f. 更新 Jira bug（UPDATE-SCOPE / RELABEL）

```text
addCommentToJiraIssue({
  cloudId: "<cloudId>",
  issueIdOrKey: "<KEY>",
  commentBody: "<已做/未做摘要，或 label/priority 調整說明>",
  contentFormat: "markdown"
})
```

若需調整 priority / component / label：

```text
editJiraIssue({
  cloudId: "<cloudId>",
  issueIdOrKey: "<KEY>",
  fields: { "priority": {"name": "<new priority>"} }
})
```

### 8g. 跨系統整併

在被整併方（Jira 或 GitHub）貼留言指向主方，再關閉。
留言內容需包含另一系統的連結（GitHub issue URL 或 Jira issue key/URL）。

執行完回報：關閉幾筆、更新幾筆、改 label 幾筆、失敗幾筆（附 issue/bug 號）。

---

## FAQ

| 問題 | 處理 |
|------|------|
| `gh issue close --comment-file` 報 `unknown flag` | `gh issue close` 只有 `-c/--comment <string>`；多行報告拆兩步：先 `gh issue comment --body-file`，再 `gh issue close --reason` |
| `gh issue edit --add-label` 失敗 | 該 label 不存在；先 `gh label list` 確認名稱 |
| `gh issue list --json` 欄位名打錯 | 會 exit 1 且印 `Unknown JSON field`，被 Step 2 gate 擋下 |
| issue/bug 很多、逐一讀 code 很慢 | Step 3b 平行 dispatch 唯讀探索 subagent 批次驗證 |
| 綁的 openspec change 找不到 tasks.md | 可能已 archive -> 查 `openspec/changes/archive/` |
| 該不該 close-as-stale | 長期無活動但症狀仍成立 -> KEEP 並降優先 |
| 排程情境無人確認 | 停在 Step 7 報告，不進 Step 8 |
| 這跟 /pr-retro、/pr-review-cycle 有何不同 | 那些針對**單一 PR**；本 skill 針對 repo 全部 open issue + Jira bug 的盤點治理 |
| Atlassian MCP 連不上 | `[WARN]` 略過 Jira 盤點，只跑 GitHub issue |
| Jira MCP 回傳太大、token 爆 | MCP 回傳約 74K 字元/15 筆（含膨脹欄位）；bug 數量多時限制 JQL `AND updated >= -90d` 或分批 |
| Jira 站台的 JQL 限制 | 某些站台禁止無條件查詢；本 skill 的 JQL 帶 `project=` 子句，不受影響 |
| Jira bug transition 失敗 | 用 `getTransitionsForJiraIssue` 先查可用 transition；無可用者 `[WARN]` 略過 |
| Jira 寫入被 hook 擋 | 本 repo 的 `pre-jira-write.sh` hook 機械攔截特定條件的 Jira 寫入；不繞過，照 hook 回報的限制處理 |
| JQL `type = Bug` 查不到東西 | 某些 Jira 專案的 issue type 叫 `Defect` 而非 `Bug`。確認專案的 issue type 名稱，必要時改 JQL 為 `type = Defect` |
| 不帶 `--jira` 時會查 Jira 嗎 | 不會。Jira 盤點需明確帶 `--jira <PROJECT>` |

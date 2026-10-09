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
  issue 留言明確要求 keep-open 的要尊重。驗證程式碼症狀前先確認基準是剛 fetch 的 origin/main；
  久未更新的 GitHub issue 依天數分層加重檢視前提是否已消失（OBSOLETE / STALE-CANDIDATE），絕不僅憑天數關閉。
  預設只產報告，寫入動作（close / comment / relabel / transition）需使用者確認後才執行。
  觸發情境：「盤點 github issue」「檢查 issue 狀態」「哪些 issue 該關閉」「issue triage」
  「清理 issue」「整併 issue」「更新 issue label」「issue 優先排序」「該關掉哪些 issue」
  「久未更新的 issue」「過期 issue」「stale issue」
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
/issue-triage                       <- 盤點目前 repo 全部 open GitHub issue（預設 --depth deep）
/issue-triage --depth fast          <- 快速模式：只查 code 症狀，不交叉比對 openspec/ADR
/issue-triage --depth deep          <- 深度模式（預設）：交叉比對 openspec archive / ADR / 流程改制
/issue-triage --jira <PROJECT>      <- 同上，加上指定 Jira 專案的 open Bug
/issue-triage --jira YB             <- 範例：盤點 GitHub issue + YB 專案 Jira Bug
/issue-triage #<n>                  <- 只研判單一 GitHub issue
/issue-triage --jira YB YB-<n>     <- 只研判單一 Jira bug
/issue-triage --apply               <- 產報告後，經逐項確認才執行寫入動作
/issue-triage --jira YB --apply    <- GitHub + Jira 都盤點，且經確認後執行寫入
```

### `--depth` 模式差異

| | `fast` | `deep`（預設） |
|---|--------|--------------|
| 查 code 症狀（Step 3b） | Yes | Yes |
| 查 openspec change 綁定（Step 3c） | Yes | Yes |
| **交叉比對 openspec archive / ADR（Step 3c′）** | **No** | **Yes** |
| **查流程改制是否讓 issue 失效（Step 3c′）** | **No** | **Yes** |
| 適用情境 | 快速掃描、issue 數量少 | 定期盤點（月/季）、issue 積壓多 |

`fast` 模式的風險：`waiting-pm` / `spec-gap` / `harness` 類 issue 可能 label 過時——PM
已裁決但沒人回頭關票、spec gap 已由 archived change 補齊、harness 工具已改版讓原 issue
失效。這些只有 `deep` 模式會抓到。

---

## Core Contract — Read-only by Default

本 skill 可能被排程或 webhook 觸發，因此遵守 `.claude/rules/11-skill-authoring.md`
「Scheduled Skills Must Be Zero-Interaction and Read-Only by Default」：

1. **預設唯讀**：不帶 `--apply` 時，只讀 issue/bug + 讀 code + 產出建議報告，**不**執行
   任何 `gh issue close / comment / edit` 或 Jira transition / comment。
2. **寫入需明示 opt-in**：任何 close / relabel / 貼留言 / 整併 / Jira transition，
   只有在使用者明確要求（`--apply` 或口頭同意某幾筆）後才執行，且**逐項確認**。
3. **無互動確認步驟**：排程情境下無人回答，此時一律停在報告，不進 Step 8；OBSOLETE 與 STALE-CANDIDATE
   的寫入動作（關閉、stale notice）也不例外。
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

### 1c. 證據基準（必要，在任何程式碼驗證之前）

Step 3b 之後的每一個 DONE / NOT DONE 都是拿「目前的程式碼」判斷的。本機 main 落後、或 checkout
停在別的 feature 分支時，兩種判斷都會反過來。所以驗證之前先 fetch origin main，並確認被檢視的就是
origin/main 的內容。**只要這次執行會對照程式碼驗證症狀就必須先過這一步**，包含只盤點 Jira bug
（`--jira`）與只研判單一項目（`#<n>`）的執行。

在要盤點的 repo 目錄內執行（不要 `cd`；腳本只吃目前目錄）：

```bash
bash ~/.agents/skills/issue-triage/scripts/check-baseline.sh
```

成功時 stdout 只有一行 `BASELINE_SHA=<40 字元 SHA> FETCHED_AT=<ISO 8601>`，把兩個值記下，
Step 7 報告頂端要寫出來。失敗時 stdout 為空、stderr 以 `[FAIL]` 開頭。**每個 exit code 是獨立分支，
不要合併成單一失敗**：

| exit | 意義 | 處理 |
|------|------|------|
| 0 | 基準通過 | 記下 `BASELINE_SHA` 與 `FETCHED_AT`，繼續 Step 2 |
| 1 | 腳本自身的未預期錯誤 | `[FAIL] check-baseline.sh 自身錯誤，請回報 stderr 內容` 並停止；不要當成基準通過 |
| 2 | 不在可讀取的 git repo | `[FAIL] 目前目錄不是可讀取的 git repo` 並停止，請切到要盤點的 repo |
| 3 | fetch origin main 失敗 | `[FAIL] 無法 fetch origin main，無法確認證據基準` 並停止；不要回退到本機的 origin/main |
| 4 | checkout 與 origin/main 不一致 | `[FAIL] checkout 與 origin/main 不一致`，轉述 stderr 的 ahead／behind 數並停止；補救是從 origin/main 開乾淨的 worktree，或先更新主 checkout |
| 5 | tracked 檔案有未提交的修改 | `[FAIL] tracked 檔案有未提交的修改`，轉述 stderr 的檔案數與清單並停止；補救是提交、還原，或改在乾淨的 worktree 執行 |

殘餘風險：untracked 檔案不算失敗，但 Grep 工具會搜到它們，可能造成假的 DONE。主 checkout 的
untracked 暫存目錄極為常見，列為失敗會讓檢查幾乎永遠紅，所以刻意放行；懷疑時改在乾淨的 worktree 執行。

> 已知限制：基準固定為 `origin/main`。fork 的 `origin` 可能落後 `upstream`，這種情境尚未處理。

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

### 3c′. 深度交叉比對（僅 `--depth deep`，預設啟用）

**目的**：label 是最不會被更新的東西——PM 做了裁決、spec 補齊了 gap、harness 工具改版了，
但原本開的追蹤 issue 不會自動關閉。本步驟交叉查 openspec archive / ADR / 流程狀態，
找出 label 過時、實質上已解決或已失效的 issue。**越舊的 issue 越要查**——「多久算舊、要多查什麼」
由 3d′ 的過期分層表決定，不是憑感覺。

對以下三類 issue，**不能只靠 label 判 KEEP**：

路徑依目標 repo 解析：openspec 根目錄預設 `openspec/`（repo 用 `docs/openspec/` 則改用之）；程式碼與 gate script 目錄依該 repo 實際結構填入。grep 零命中前先確認目錄存在，不存在不可當成「未實作」。

#### (a) `waiting-pm` / `spec: waiting-pm` / `wait-PM` 類

逐一交叉查：

1. **openspec archive**：issue 提到的 change 是否已 archive？archive 代表 delta 已套進
   stable spec，PM 裁決可能已在 archive 過程中落地。
   查法：`ls docs/openspec/changes/archive/ | grep '<change-number>'`
2. **ADR**：是否已有 ADR 承接該裁決？
   查法：`grep -rl '<關鍵詞>' docs/adr/`
3. **stable spec 內容**：PM 裁決的具體答案是否已寫進 spec normative 句？
   查法：`grep -n '<裁決內容關鍵詞>' docs/openspec/specs/<cap>/spec.md`

**判準**：issue 問的「待裁決問題」本身已有答案（寫進 spec / ADR / code）→ CLOSE 或
UPDATE-SCOPE。change 已 archive **不等於**裁決已完成——archive 是 delta 套進 stable spec，
OQ 可能仍開放。

#### (b) `spec-gap` 類

逐一交叉查：

1. **有無 active 或 archived change 補齊**：
   查法：`ls docs/openspec/changes/ docs/openspec/changes/archive/ | grep '<相關 Epic 或 capability>'`
2. **ADR 是否裁決該 gap 為 non-goal 或由其他方案解決**：
   查法：`grep -rl '<gap 關鍵詞>' docs/adr/`
3. **code 是否已實作**（即使 spec 未更新，code 端可能已補齊）：
   查法：`grep -rn '<功能關鍵詞>' backend/src/ mobile/lib/`

**判準**：gap 已被 change 補齊（查 archive 的 tasks.md 全 `[x]`）→ CLOSE。
有 active change 承接但未完成 → UPDATE-SCOPE（改為追蹤該 change）。
有 ADR 承接（`status: proposed`）→ UPDATE-SCOPE（改為追蹤 ADR 裁決）。

#### (c) `harness` 類

逐一判斷是否仍有效：

1. **流程改制**：該 repo 若已退場某個追蹤佇列（例如改走 Mycelium typed lesson），從該佇列遷出、只剩「寫一段散文」的 issue 可 CLOSE。
2. **工具改版**：issue 追蹤的 bug 是否已被 CLI / plugin 新版修復？
   查法：`spectra --version` 比對 issue 建立時的版本
3. **gate 是否已建**：issue 要求的 gate script 是否已存在？
   查法：`ls scripts/harness/ | grep '<gate-name>'`
4. **過時副本**：`.claude/hooks/` 的檔案是否為 plugin 的過時殘留（settings.json 未註冊）？

**判準**：觸發路徑已不存在 / 工具已修復 / 流程已改制讓原 issue 無意義 → CLOSE。
issue 是「gate script 不存在」但仍有效 → KEEP。
scope 已縮小（部分完成）→ UPDATE-SCOPE。

#### 平行 dispatch

issue 數量多時（>10），按上述三類各 dispatch 一個 fork subagent 平行交叉比對，
與 Step 3b 的 code 驗證 subagent 並行。prompt 需附：

- archived change 清單（`ls archive/`）
- active change 清單（`ls docs/openspec/changes/`）
- ADR 清單（`ls docs/adr/`）

### 3d. 檢查留言意圖訊號（P3）

掃該 issue 的 comments（GitHub）或 Jira bug 的 comment（MCP 回傳），
把留言意圖分成**兩類互斥訊號**：

- **keep-open 訊號**：「backlog」「deferred」「低優先」「保留」等 -> 導向 KEEP。
- **close-authorization 訊號**：「可直接關閉」「已修復可關」等 -> 且無未解症狀時導向 CLOSE。

### 3d′. 過期檢視輸入（僅 GitHub issue）

久未更新的 issue 不是低優先，而是「前提可能已消失」的嫌疑對象。本節蒐集四項輸入——最後一次實質人為活動、
過期分層、程式碼漂移、豁免——決定**要多查什麼**。**天數只決定檢視深度與證據門檻，從不單獨決定關閉**：
真實的 bug 會因為沒人處理而久未更新，僅憑天數關閉會把它們關掉，違反本 skill「誤關成本高於留著」的原則。
Jira bug 不適用本節（Jira 的 updated 欄位、留言者與自動化帳號語意與 GitHub 不同，另案處理）。

#### 最後一次實質人為活動

定義：issue 建立時間，與所有「非 bot 且非 skill 自己」的留言時間之中最晚的一個。label、assignee、reaction
的變動不計入；issue body 的編輯也不計入（gh 的 JSON 沒有穩定的編輯時間欄位，這個低估活躍度的方向是安全的）。
無人為活動的天數 = 今天（UTC）減去這個時間。

- **bot 只看帳號型別**（REST 回報的 user.type 為 Bot），**不看 login 文字**：`gh issue list` 的 JSON 會把
  `github-actions[bot]` 顯示成 `github-actions`，`Copilot` 這類 bot 本來就沒有 `[bot]` 後綴。
  已刪除的帳號與沒見過的帳號型別一律視為人為活動（往「看起來比較活躍」的安全方向失敗）。
- **skill 自己的留言** = 內文含 triage 標記（見本節最後一段）**且**作者是目前登入的帳號。標記單獨出現
  不夠：任何人都能貼上標記，只看標記會讓他的留言從度量中隱形。另一個帳號貼出的標記一律算人為活動。

先用 Step 2a 的 JSON 粗算「全部留言都計入」的最後活動日（`naive`）。**只有符合下列任一條件才呼叫腳本**取得
精確值（腳本對每個 issue 做一次 REST 呼叫）：

- `naive` 距今小於 180 天：排除 bot 後只會更久，需要精確值才知道落在哪一層。
- 任一留言內文含 `issue-triage:stale-notice`：需要找回 stale notice 的時間來判斷寬限期；notice 可能早於 180 天。

`naive` 已達 180 天且沒有 stale notice 標記者，直接落在 tier 3，報告寫「≥ {{naive_days}} 天」，不必呼叫腳本。

```bash
bash ~/.agents/skills/issue-triage/scripts/last-human-activity.sh {{issue_number}}
```

成功時 stdout 一行、以 tab 分隔：**最後人為活動時間**、**stale notice 留言的時間**（沒有則為空）。
失敗時 stdout 為空、stderr 以 `[FAIL]` 開頭。每個 exit code 是獨立分支：

| exit | 意義 | 處理 |
|------|------|------|
| 0 | 成功 | 取兩個欄位繼續 |
| 1 | 腳本自身的未預期錯誤 | 該 issue 標「過期檢視不可用」，不得升為 STALE-CANDIDATE 或 OBSOLETE；最後彙總列出，不要當成「有人為活動」 |
| 2 | 參數錯誤（issue 編號不合法） | 這是 skill 自己的 bug：`[FAIL] last-human-activity.sh 參數錯誤` 並停止 |
| 3 | gh API 呼叫失敗（目前帳號、issue、留言任一個） | 同 exit 1 處理；連續失敗代表認證或網路問題，`[FAIL]` 並停止過期檢視 |
| 4 | 缺 jq，或 API 回應無法解析 | 缺 jq：`[WARN] 缺 jq，略過過期檢視` 並繼續其餘 verdict；無法解析：同 exit 1 處理 |

#### 過期分層（初始值，首次執行請與使用者校準）

| Tier | 無人為活動天數 | 額外要求 |
|------|----------------|----------|
| 0 | 少於 30 天 | 無，走標準流程 |
| 1 | 30 到 89 天 | 蒐集並在報告列出程式碼漂移訊號 |
| 2 | 90 到 179 天 | 蒐集漂移訊號；**KEEP 必須引用「前提仍成立」的正向證據**，不能是預設 KEEP |
| 3 | 180 天以上 | tier 2 的全部要求，且具備 STALE-CANDIDATE 資格 |

邊界以天數整數判定：29 天是 tier 0、30 天是 tier 1、89 天是 tier 1、90 天是 tier 2、179 天是 tier 2、180 天是 tier 3。
分層在 `--depth fast` 與 `--depth deep` **都生效**（它只是便宜的存在性檢查）；與 openspec archive、ADR 的
交叉比對（3c′）仍然只在 deep。tier 2 以上的 KEEP 若找不到正向證據，仍然維持 KEEP，但在報告標
`premise-unverified`，不得因此關閉。

#### 程式碼漂移訊號

tier 1 以上的 issue，從 issue body 抽出 repo 相對路徑（含 `/` 與副檔名的 token，例如
`plugins/dev-cycle/skills/issue-triage/SKILL.md`；排除 URL、去掉結尾標點、去重）。有路徑時，每個 issue
呼叫一次（單一 bash 呼叫，路徑逐一帶入，不要用迴圈）：

```bash
bash ~/.agents/skills/issue-triage/scripts/staleness-signals.sh {{issue_created_at}} {{path_1}} {{path_2}}
```

每個路徑輸出一行 tab 分隔的「路徑、狀態、細節」：

| 狀態 | 意義 | 怎麼用 |
|------|------|--------|
| unchanged | 仍存在，自 issue 建立後沒人動過 | 前提仍成立的證據之一 |
| changed | 仍存在，細節為自建立後的 commit 數 | 只是訊號；仍要回 3b 驗證症狀是否被順手修掉 |
| deleted | 已被刪除，細節為刪除它的 commit | 前提疑似消失；回 3b 確認，並作為 OBSOLETE 的候選證據 |
| renamed | 細節為新路徑 | 追到新路徑繼續驗證症狀，不算消失 |
| never-existed | origin/main 歷史上從未有過 | 多半是 issue 寫錯路徑；列為 UNCLEAR，**不是**消失的證據 |

沒有任何路徑時輸出 `NOT_APPLICABLE`。**「沒有漂移訊號」與「不適用」都不是前提仍成立的證據**：這類 issue
只能靠 3b 的症狀驗證。腳本的 exit code：0 成功；1 腳本自身錯誤（`[FAIL]` 並停止漂移蒐集，不要當成「沒有漂移」）；
2 參數錯誤（skill 自己的 bug，`[FAIL]` 並停止）；3 找不到 origin/main（`[FAIL]`，請回 1c 重跑）。

#### 豁免

下列任一條件成立的 issue，**不得**成為 STALE-CANDIDATE、也**不得**成為 OBSOLETE，報告要逐筆列出豁免原因：

1. 有 security 相關 label（label 名稱含 `security`，不分大小寫）。
2. `assignees` 非空（已有人認領）。
3. `milestone` 非空，且其 `dueOn` 非 null 並晚於今天。`dueOn` 為 null 的 milestone 沒有期限，不豁免。
4. 綁定進行中的 openspec change（3c 找到的 change 位於 `openspec/changes/` 而不在 archive）。
5. 有 keep-open 訊號（3d）的留言，其 `authorAssociation` 為 OWNER、MEMBER 或 COLLABORATOR。
   路人（NONE、CONTRIBUTOR 等）的 keep-open 留言不構成豁免，但仍依 P3 在決策時納入考量。

#### triage 標記

skill 貼到 issue 上的**每一則**留言（見 Step 8）都必須在內文帶一行 HTML 註解標記：

```text
<!-- issue-triage:<kind> <YYYY-MM-DD> -->
```

`<kind>` 為 `close`、`update-scope`、`merge`、`stale-notice` 其中之一。標記讓下一次盤點能（一）排除自己的
留言、不重置過期時鐘，（二）找回 stale notice 的時間以判斷寬限期。skill 本身維持無狀態：跨次狀態記在
issue 上，不記在本機檔案，也不新增 label。

### 3e. Verdict 決策表（GitHub issue 與 Jira bug 共用）

**先判斷 guard，再依主狀態選唯一一列。** 主狀態互斥、每個 issue/bug 只落一列；
**RELABEL 是正交的附加建議**，可疊加在任何主狀態上。
多主狀態同時成立時的優先序：**MERGE > CLOSE > OBSOLETE > UPDATE-SCOPE > STALE-CANDIDATE > KEEP**。

| # | 條件 | Verdict | 行動 |
|---|------|---------|------|
| **guard** | **任一前置呼叫失敗** | **STOP** | 回報錯誤並停止 |
| **guard** | **任一症狀 = UNCLEAR** | **視同 NOT DONE** | 不得 CLOSE，也不得 OBSOLETE；落 KEEP 或 UPDATE-SCOPE |
| 1 | 與另一 open issue/bug 覆蓋同一主題（含跨系統） | **MERGE** | 建議合併方向 |
| 2 | 所有症狀 DONE，且（若綁 change）tasks.md 全 `[x]`，且無 keep-open | **CLOSE** | GitHub: comment + close；Jira: comment + transition to Done |
| 3 | 留言有 close-authorization 且無未解症狀 | **CLOSE** | 同上 |
| 4 | 所有未解症狀的前提皆已證實不存在於基準（見下方「OBSOLETE 的證據標準」），且無豁免（僅 GitHub issue） | **OBSOLETE** | 留言說明前提消失與證據，以 `not planned` 關閉（不是 `completed`） |
| 5 | 部分症狀 DONE、部分 NOT DONE，或只有部分症狀失去前提 | **UPDATE-SCOPE** | 留言標明已做/未做，收斂標題到剩餘範圍 |
| 6 | 原本會落在第 7 或第 8 列、tier 3（無人為活動 180 天以上）、前提未被證實消失、無豁免（僅 GitHub issue） | **STALE-CANDIDATE** | 依下方「寬限期」：先提議 stale notice；寬限期滿且無人為活動才提議以 `not planned` 關閉 |
| 7 | 全部症狀 NOT DONE | **KEEP** | 不動作 |
| 8 | 症狀無法從 repo 內部驗證 | **KEEP (external)** | 留言說明程式碼面已就緒但驗證在 repo 外 |
| +附加 | 缺 type label / label 過期 / 狀態不符 | **RELABEL**（正交） | 疊加建議改 label/component |

**OBSOLETE 的證據標準**（零命中的搜尋沒有資訊量：搜尋目錄不存在、路徑拼錯、工具出錯都會得到零命中）：

- 對每個未解症狀，它所依賴的前提構件（檔案、符號、功能、change）必須在 `origin/main` 基準上被**證明不存在**。
- 必須有**正向對照**：同一種搜尋方法、在同一個位置，找得到一個已知存在的對象（例如在同一個父目錄搜尋一個
  確定存在的模組）。對照失敗或搜尋目錄不存在，該症狀的結論是 UNCLEAR，**不構成 OBSOLETE**。
- 3d′ 漂移訊號的 `deleted` 只是候選證據，仍要回 3b 確認症狀；`renamed` 要追到新路徑；`never-existed`
  不是證據。
- 只有**部分**未解症狀失去前提時，verdict 是 UPDATE-SCOPE（第 5 列），不是 OBSOLETE。
- 建議關閉原因一律是 `not planned`：工作並沒有被完成。

**STALE-CANDIDATE 與寬限期**（狀態記在 issue 的 stale notice 標記上，見 3d′；「已辨識的 stale notice」指
標記為 `stale-notice` 且作者是目前登入帳號的留言，另一個帳號貼出的標記不算）：

| 狀況 | 建議行動 |
|------|----------|
| 沒有已辨識的 stale notice | 提議貼 stale notice：詢問是否仍需要，說明寬限期 **14 天**，無回應將以 `not planned` 關閉 |
| 有已辨識的 stale notice，距今不滿 14 天 | 不動作（寬限期內），報告列為「寬限期中」 |
| 有已辨識的 stale notice，距今 14 天以上，且 notice 之後沒有實質人為活動（最後人為活動時間不晚於 notice 時間） | 提議以 `not planned` 關閉 |
| notice 之後有實質人為活動 | 當作沒有 notice 重新評估，無人為活動天數從該活動起算 |

**絕不**：僅憑天數建議關閉、在沒有先前 stale notice 的情況下建議關閉、在 notice 未滿 14 天時建議關閉。
STALE-CANDIDATE 與 OBSOLETE 的寫入動作同樣遵守 Core Contract：只有 `--apply` 並逐項確認後才執行，
排程情境一律停在報告。

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

對所有「KEEP / UPDATE-SCOPE / STALE-CANDIDATE」的 issue/bug 給出建議處理順序（GitHub + Jira 合併排序）：

| 訊號 | 高優先 | 低優先 |
|------|--------|--------|
| **嚴重度** | bug / security / 阻塞正常流程 | enhancement / docs / chore |
| **影響範圍** | 被其他 open issue 引用 / 阻塞他人 | 孤立、無下游依賴 |
| **就緒度** | 有清楚 repro / AC，現在就能動手 | 卡在待決策 / 外部依賴 |
| **CP 值** | 低成本、修法明確的 quick win | 高成本、範圍模糊 |
| **時效** | 有 deadline（milestone 的 `dueOn` 即將到來或已逾期） | 沒有 deadline |

輸出 3 檔：**P0 立即**、**P1 本週**、**P2 有空再做**。
**GitHub issue 與 Jira bug 混合排序**——不分開排。

> **久未更新不降低優先級。** 無人為活動的天數不是低優先的理由：同等條件下，久未處理的嚴重且未解的 issue
> 不得排在較新的 issue 之後（它很可能只是一直沒人處理，而不是不重要）。久未更新改以
> `review-urgency: <N> 天無人為活動` 註記在該筆旁邊，意思是「這筆很久沒人驗證過前提」：它影響
> 「要不要重新檢視前提」（3d′），不影響「做這件事有多急」。
>
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

## 證據基準
- origin/main@<BASELINE_SHA 完整 40 字元>（fetch 完成：<FETCHED_AT>）

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

## 前提已消失（OBSOLETE，建議以 not planned 關閉；僅 GitHub issue）
- #<n> <title> -- 消失的前提：<檔案/符號/功能>；證據：<漂移訊號與 3b 驗證>；正向對照：<找得到哪個已知對象>

## 過期候選（STALE-CANDIDATE；僅 GitHub issue）
- #<n> <title> -- 無人為活動 <N> 天；狀態：<尚無 stale notice，建議貼 notice / 寬限期中，剩 <d> 天 /
  寬限期滿且無人為活動，建議以 not planned 關閉>

## 豁免（不會成為 OBSOLETE 或 STALE-CANDIDATE）
- #<n> <title> -- 豁免原因：<security label / 已認領 / milestone 未到期 / 綁定進行中的 change / 維護者 keep-open>

## 過期檢視不可用
- #<n> <title> -- <last-human-activity.sh 或 staleness-signals.sh 的 exit code 與原因>；本次不得升為
  STALE-CANDIDATE 或 OBSOLETE

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
- #<n> <title> -- <為何不動>；tier 2 以上者附「前提仍成立」的正向證據，找不到則標 premise-unverified

### Jira Bugs
- <KEY> <summary> -- <為何不動>

## 優先處理排序（GitHub + Jira 混合）
- P0：#<n>, <KEY>, ...
- P1：#<n>, <KEY>, ...
- P2：#<n>, ...
- 久未更新者在該筆後面註記 review-urgency: <N> 天無人為活動（不影響所在的檔位）
```

若 `$OUT` 落在 `$CLAUDE_JOB_DIR`（background job dir），回報時把重點**貼進對話**。

**不帶 `--apply` 時，到此為止。**
**不帶 `--jira` 時，報告省略所有 Jira Bugs 段落。**

---

## Step 8 — Execute Writes（opt-in，逐項確認後）

僅在使用者帶 `--apply` 或明確同意某幾筆時執行。**逐一 issue/bug 執行並回報結果**。

**無互動確認者（排程 / webhook）即使帶 `--apply` 也不執行寫入**——停在 Step 7。
OBSOLETE 的關閉、stale notice、寬限期滿的關閉（8h、8i、8j）同樣只在 `--apply` 且逐項確認後才執行，
排程與 webhook 情境即使看到 STALE-CANDIDATE 也只進報告、不貼任何留言。

**失敗 gate**：任一寫入呼叫失敗 -> `[FAIL] <issue/bug> <動作> 失敗`，
回報並**跳過該筆**，最後彙總失敗清單。

**每一則貼到 GitHub issue 的留言（8a、8b、8d、8h、8i、8j）內文最後一行都必須帶 triage 標記**
（格式與 `<kind>` 見 3d′ 的「triage 標記」；日期用今天，UTC）。沒有標記的留言，下一次盤點會把它當成
人為活動、重置過期時鐘，stale notice 也無法被找回。例如 `close-<n>.md` 的最後一行：

```text
<!-- issue-triage:close 2026-10-09 -->
```

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

`close-<n>.md` 最後一行必須是 `<!-- issue-triage:close <今天日期> -->`。

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

`update-<n>.md` 最後一行必須是 `<!-- issue-triage:update-scope <今天日期> -->`。

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

`merge-<b>.md` 最後一行必須是 `<!-- issue-triage:merge <今天日期> -->`。

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

### 8h. 關閉前提已消失的 GitHub issue（OBSOLETE）

留言（用 Write tool 寫到 `$OUT/close-<n>.md`，kind 為 `close`）要寫明：哪個前提已不存在、證據是什麼
（含基準 commit `origin/main@<BASELINE_SHA 前 12 碼>`）、若判斷有誤歡迎重新開啟。`$OUT` 解析與
`gh issue comment` 放同一個 bash block（寫法同 8a），再以 **`not planned`** 關閉——不是 `completed`，
因為工作並沒有被完成：

```bash
gh issue close <n> --reason "not planned"
```

### 8i. 貼 stale notice（STALE-CANDIDATE，尚無已辨識的 notice）

留言（寫到 `$OUT/stale-<n>.md`，kind 為 `stale-notice`）要寫明：這個 issue 已 {{inactive_days}} 天沒有人為活動；
詢問是否仍需要；**寬限期 14 天**，到 <到期日> 前沒有回應，將以 `not planned` 關閉；任何回覆（哪怕只是
「仍需要」）都會取消關閉。`$OUT` 解析與 `gh issue comment` 放同一個 bash block（寫法同 8a）。
`stale-<n>.md` 最後一行必須是 `<!-- issue-triage:stale-notice <今天日期> -->`，下一次盤點靠它找回 notice 的時間。
貼完不關閉、不改 label。

### 8j. 寬限期滿後關閉（STALE-CANDIDATE，已有已辨識的 notice）

**寫入前必須重新呼叫** `last-human-activity.sh {{issue_number}}`（見 3d′），確認 notice 之後仍然沒有實質
人為活動；從 3e 判定到使用者逐項確認之間可能有人回覆了。有新活動就放棄這筆，列入「已取消」。確認無誤後，
留言（寫到 `$OUT/close-<n>.md`，kind 為 `close`）說明「stale notice 已於 <日期> 貼出，寬限期 14 天內
沒有回應」，再以 `not planned` 關閉（指令同 8h）。

執行完回報：關閉幾筆、更新幾筆、改 label 幾筆、貼 stale notice 幾筆、因新活動而取消幾筆、失敗幾筆（附 issue/bug 號）。

---

## FAQ

| 問題 | 處理 |
|------|------|
| `gh issue close --comment-file` 報 `unknown flag` | `gh issue close` 只有 `-c/--comment <string>`；多行報告拆兩步：先 `gh issue comment --body-file`，再 `gh issue close --reason` |
| `gh issue edit --add-label` 失敗 | 該 label 不存在；先 `gh label list` 確認名稱 |
| `gh issue list --json` 欄位名打錯 | 會 exit 1 且印 `Unknown JSON field`，被 Step 2 gate 擋下 |
| issue/bug 很多、逐一讀 code 很慢 | Step 3b 平行 dispatch 唯讀探索 subagent 批次驗證 |
| 綁的 openspec change 找不到 tasks.md | 可能已 archive -> 查 `openspec/changes/archive/` |
| 該不該 close-as-stale | **不憑天數關閉。** 前提已消失 -> OBSOLETE（附證據與正向對照，以 `not planned` 關閉）；tier 3（無人為活動 180 天以上）且前提未被證實消失 -> STALE-CANDIDATE，先貼 stale notice、寬限期 14 天、無回應才建議以 `not planned` 關閉；其餘一律 KEEP。優先級**不因久未更新而降低**，改標 `review-urgency` |
| `check-baseline.sh` 回報 exit 4 或 5 | checkout 不是乾淨的 origin/main：從 origin/main 開乾淨的 worktree 再跑，或先更新主 checkout；不要為了讓它過而 stash 或硬重設別人的改動 |
| 為什麼判斷 bot 要多一次 REST 呼叫 | `gh issue list --json comments` 會把 `github-actions[bot]` 顯示成 `github-actions`，`Copilot` 本來就沒有 `[bot]` 後綴，只看 login 文字會把 bot 留言全當成人為活動，過期檢視等於失效；REST 的 user.type 為 Bot 才可靠 |
| 為什麼 skill 自己的留言要「標記加作者」才排除 | 只看標記，任何人貼上標記就能讓自己的留言從活動度量中隱形；另一個帳號貼出的標記一律算人為活動，失敗方向是「看起來比較活躍」，不會導致誤關 |
| 不同人執行 skill 時，前一個人貼的 stale notice 還算數嗎 | 不算：標記必須搭配「作者是目前登入帳號」，換帳號後舊的 notice 會被當成人為活動，issue 看起來較活躍而被 KEEP。這是安全方向，代價是要重新貼一次 notice |
| 排程情境無人確認 | 停在 Step 7 報告，不進 Step 8 |
| 這跟 /pr-retro、/pr-review-cycle 有何不同 | 那些針對**單一 PR**；本 skill 針對 repo 全部 open issue + Jira bug 的盤點治理 |
| Atlassian MCP 連不上 | `[WARN]` 略過 Jira 盤點，只跑 GitHub issue |
| Jira MCP 回傳太大、token 爆 | MCP 回傳約 74K 字元/15 筆（含膨脹欄位）；bug 數量多時限制 JQL `AND updated >= -90d` 或分批 |
| Jira 站台的 JQL 限制 | 某些站台禁止無條件查詢；本 skill 的 JQL 帶 `project=` 子句，不受影響 |
| Jira bug transition 失敗 | 用 `getTransitionsForJiraIssue` 先查可用 transition；無可用者 `[WARN]` 略過 |
| Jira 寫入被 hook 擋 | 目標 repo 若有 `pre-jira-write.sh` 之類 hook（如 yibi-mvp），不繞過，照 hook 回報的限制處理 |
| JQL `type = Bug` 查不到東西 | 某些 Jira 專案的 issue type 叫 `Defect` 而非 `Bug`。確認專案的 issue type 名稱，必要時改 JQL 為 `type = Defect` |
| 不帶 `--jira` 時會查 Jira 嗎 | 不會。Jira 盤點需明確帶 `--jira <PROJECT>` |
| `--depth fast` 和 `deep` 差在哪 | `fast` 只查 code 症狀（Step 3b/3c）；`deep`（預設）額外交叉比對 openspec archive / ADR / 流程改制（Step 3c′），能抓到 label 過時的 waiting-pm / spec-gap / harness issue |
| 為什麼 `deep` 是預設 | label 是最不會被更新的東西——PM 裁決落地、spec gap 補齊、harness 流程改制後，原 issue 不會自動關閉。只靠 label 判 KEEP 等於信任 label 的新鮮度，而那正是 triage 要驗證的對象（事故：yibi-mvp 2026-09-06 盤點，第一輪 fast 漏了 10 個可 CLOSE/UPDATE-SCOPE 的 issue） |

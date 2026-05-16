# Spectra Archive + Jira Sync — 收尾步驟

PR merge 完成後，同步 spec 狀態與 Jira ticket，結束此開發循環。兩個小節均為**選用**——無 spectra change 或無 Jira issue 時直接跳過。

---

## Step A — Spectra Archive

若本次開發循環確定未建立 spectra change，直接跳過此步驟。

否則，列出進行中的 change，確認是否有對應此 PR 的項目（change 名稱通常與 feature branch 名稱相近）：

```bash
spectra list
```

若指令失敗，停止並回報錯誤給使用者，不要繼續。

若有對應 change，**在執行前回報將要 archive 的 change 名稱，等待使用者確認**（archive 是不可逆操作）：

> 找到疑似對應的 spectra change：`{{change_name}}`。確認執行 archive？

確認後執行：

```bash
spectra archive {{change_name}} --yes
```

若指令以非零退出碼結束，停止並回報錯誤給使用者。
若 validation 有 Critical 錯誤，以 `spectra analyze {{change_name}}` 確認問題，修正後再 archive；或由使用者明確指示才加 `--no-validate` 略過（agent 不可自行決定略過）。

---

## Step B — Jira Sync

**偵測 Jira Issue Key**：

merge 後 branch 已被 `--delete-branch` 刪除，改從 PR title / body 提取：

```bash
gh pr view {{pr_number}} --json title,body -q '.title + " " + (.body // "")'
```

若指令本身以非零退出碼失敗，停止並回報錯誤，詢問使用者手動提供 key。
若指令成功但輸出中無符合 `[A-Z]{2,}-[0-9]+` 格式的字串（如 `ABC-123`），詢問使用者提供 key，或跳過此步驟。

**取得 transitions，再並行執行 transition + comment**：

先呼叫 `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`（`issueId`：`{{jira_issue_key}}`）取得 transition 清單。若呼叫失敗，停止並回報錯誤給使用者。

選擇語意最接近「已完成開發並合併」的選項（常見：`Done`、`Merged`、`Released`、`Closed`）。若不確定，詢問使用者確認後再執行。

確認 transition 後，以下兩個 MCP 呼叫**可同時送出**（無相依性）；任一失敗均須回報，不得靜默繼續：

- `mcp__claude_ai_Atlassian__transitionJiraIssue`：將 `{{jira_issue_key}}` 移至選定狀態
- `mcp__claude_ai_Atlassian__addCommentToJiraIssue`：新增以下格式 comment：

```text
PR #{{pr_number}} 已 squash merge 至 main。
Merge commit：{{merge_commit_sha}}
```

若 Step A 有 archive spectra change，comment 一併附上：

```text
Spectra change `{{change_name}}` 已 archive，spec 狀態已更新為完成。
```

---

## 收尾回報格式

完成後，向使用者回報：

- Spectra archive 狀態：已 archive `{{change_name}}` / 已跳過（無對應 change）/ 失敗原因
- Jira ticket 狀態：已 transition 至 `{{selected_state}}` + comment 已寫入 / 已跳過（無 Jira key）/ 失敗原因

---

## 常見問題

| 問題 | 處理方式 |
|------|----------|
| spectra archive validation 失敗 | `spectra analyze {{change_name}}` 查看 Critical 錯誤，修正後再 archive；`--no-validate` 需使用者明確指示才使用 |
| Jira key 無法從 PR 偵測 | 詢問使用者提供 key（格式：`PROJECT-123`），或確認此 PR 無對應 Jira issue 後跳過 |
| Jira transition 選項不確定 | 呼叫 `getTransitionsForJiraIssue` 列出所有選項後詢問使用者確認 |
| Jira MCP 需認證 | Atlassian MCP 需要 OAuth；若工具回傳 auth 錯誤，提示使用者在 claude.ai 完成授權 |

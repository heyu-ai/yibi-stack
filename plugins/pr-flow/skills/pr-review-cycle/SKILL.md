---
name: pr-review-cycle
type: know
scope: global
description: >
  完整 PR 生命週期：從建立 PR 到 code-review → parallel review → fix → re-review → CI → merge → spectra archive + Jira sync。
  觸發情境：「跑 PR cycle」「review 這個 PR」「pr-review-cycle」「完整 PR 流程」「jira sync」「spectra archive」
---

# PR Review Cycle

從建立 PR 到合併的完整流程，適用任何技術棧（Python / JS / Go / 其他）的 git 專案。

## 使用方式

```text
/pr-review-cycle
/pr-review-cycle #<PR number>   ← 已有 PR 時直接跳 Step 2
```

---

## Workflow

### Step 1 — 建立 PR

若尚未建立 PR，依序執行：

```bash
# 確認在 feature branch，不在 main
git branch --show-current

# commit 所有未提交的變更
git add <files>
git commit -m "..."

# push 並建立 PR
git push -u origin HEAD
# 用 Write tool 把 PR body 寫到 /tmp/pr-body.md，再傳入（避免 hook 攔截 markdown headers）
gh pr create --title "..." --body-file /tmp/pr-body.md
rm -f /tmp/pr-body.md
```

若專案有安裝 `/commit-commands:commit-push-pr`，可直接執行（自動 commit + push + PR）。

記下 PR number，後續步驟使用。

---

### Step 1.5 — Scope Drift Detection（Informational，不阻擋）

PR 建立後，先檢查「做了該做的事嗎？沒多做、沒少做？」

```bash
git diff main...HEAD --stat
```

同時讀取 PR description（stated intent）：

```bash
gh pr view --json title,body -q '"\(.title)\n\(.body)"'
```

比對 diff 與 stated intent，輸出：

```text
Scope Check: [CLEAN / DRIFT DETECTED / REQUIREMENTS MISSING]
Intent:    <1 句話：PR 聲稱要做什麼>
Delivered: <1 句話：diff 實際改了什麼>
[如有 DRIFT：列出每個不在計畫內的改動]
[如有 MISSING：列出 PR description 提到但 diff 沒有的需求]
```

此步驟為 **informational**，不阻擋後續流程。若 DRIFT DETECTED，在 Step 3 的 code review 結果中一併標注。

---

### Step 2 — Code Review（缺陷偵測）

執行 `/code-review`，掃描 PR 全部變更的正確性 bug：

```text
/code-review
```

若需更嚴格審查，可指定 effort：

```text
/code-review high
```

選用：加 `--comment` 把 finding 直接貼成 GitHub PR inline comment：

```text
/code-review --comment
```

- **無 finding** → 直接進 Step 3。
- **有 finding** → 帶入 Step 4（Fix）與 parallel review 結果一併處理。
  `/code-review` **不修改程式碼**，finding 屬 review 意見，不需獨立 commit。

> **Fallback（Claude Code < 2.1.146）**：若 `/code-review` 報 `Unknown skill: code-review`，
> 改用 `pr-review-toolkit:code-reviewer` agent 替代（行為相同，純回報不修改程式碼）：
>
> ```text
> Agent(subagent_type=pr-review-toolkit:code-reviewer,
>       prompt="對本 PR 的所有 diff 做 code review，回報 bug / 規範合規 / 邏輯錯誤")
> ```

---

### Step 3 — Parallel Review（平行啟動 4 個 agent）

在**同一則訊息**中平行啟動所有 review agents（`pr-review-toolkit` 各 subagent）：

| Agent | 聚焦面向 |
|-------|---------|
| `code-reviewer` | 專案規範合規、潛在 bug、邏輯錯誤 |
| `silent-failure-hunter` | 靜默失敗、exception 吞噬、不當 fallback |
| `pr-test-analyzer` | 測試覆蓋缺口、critical path 未測試 |
| `comment-analyzer` | 文件準確性、comment rot、誤導說明 |

彙整結果，分級：

- **Critical**（阻擋 merge）
- **Important**（應修）
- **Minor**（選修）

---

### Step 4 — Fix

依序處理 **Critical** → **Important**：

1. 修改程式碼

2. 每修完一批就跑本地 CI。先讀取專案根目錄找出實際的 CI 指令：

   ```bash
   # 找 CI 入口（依序確認）
   cat Makefile 2>/dev/null | grep -E "^ci:|^test:|^check:" | head -5
   cat package.json 2>/dev/null | python3 -c "import json,sys; s=json.load(sys.stdin).get('scripts',{}); [print(k,':',v) for k,v in s.items() if k in ('test','ci','check')]"
   cat pyproject.toml 2>/dev/null | grep -A2 "\[tool.pytest\|testpaths"
   ```

   常見 CI 指令對照：

   | 技術棧 | 典型本地 CI 指令 |
   |--------|----------------|
   | Python (make) | `make ci` |
   | Python (bare) | `uv run pytest` / `pytest` |
   | Node.js | `npm test` / `npm run ci` |
   | Go | `go test ./...` |
   | Rust | `cargo test` |

   若失敗，**先修好再繼續**，不跳過。

3. commit（訊息描述修了什麼，不要 "fix review comments"）：

   ```bash
   git commit -m "fix(...): ..."
   git push
   ```

---

### Step 5 — Re-review

對**本次修改的檔案**重跑 Step 3 的 agents：

```bash
git diff main...HEAD --name-only   # 確認範圍
```

確認所有 Critical / Important 問題已解決。若有新問題，回到 Step 4。

---

### Step 6 — CI Check

等待 GitHub Actions 全部通過：

```bash
gh pr checks {{pr_number}} --watch
```

若 CI 失敗：

1. 先在本地重現（使用 Step 4 找到的本地 CI 指令）
2. 修好，commit，push
3. 重新等待 CI

本地 CI 是權威：CI 與本地結果不一致時，以本地工具輸出為準，檢查 CI 環境差異（Python 版本、環境變數、快取等）。

---

### Step 7 — Merge

### Pre-merge 確認：版本 bump

執行 `gh pr merge` 之前，先暫停並向使用者確認：

> 此次變更是否需要 bump 版本？
>
> - **需要** → 請先執行 [`/bump-version`](../bump-version/SKILL.md)（會在 feature branch 上 commit 版本檔 + CHANGELOG + git tag + push）。
>   完成後**回到上一步等待 CI 全綠**（新 commit 觸發新一輪 CI），再回到本步驟繼續 merge。
>   注意：`--squash` merge 後 git tag 指向 feature branch HEAD 而非 main 的 merge commit；如需 tag 指向 main，merge 後在 main 上重新 tag。
> - **不需要** → 確認後繼續 merge。
> - **不確定** → 簡述本次變更性質，由 agent 依下方準則建議 bump 類型，**等使用者確認後**再執行 `/bump-version` 或繼續 merge。

判斷準則（agent 提交使用者裁決前可先評估）：

| 變更性質 | 建議 |
|---------|------|
| 純內部重構、測試、CI 設定 | 通常不需要 bump |
| Bug fix、文件修正、效能調整、相容性修正 | patch |
| 新功能、新 API（向後相容）| minor |
| Breaking change（API 不相容）| major |

（判斷準則僅供快速評估，完整定義見 [`/bump-version`](../bump-version/SKILL.md) Step 1）

使用者明確回應「不需要」或「已執行 `/bump-version`」後，才執行下一步 `gh pr merge`。
若使用者回應「已執行 `/bump-version`」，先確認 bump commit 已推送至遠端：

```bash
git fetch
```

```bash
git log --oneline -3 '@{upstream}'
```

確認近 3 筆 commit 中有一筆訊息符合 `chore(release): v*` 格式後再繼續；若未找到，提示使用者完成 `/bump-version` Step 4（push）後再回來。
從該 commit message 提取版本號（如 `v1.2.3`），再精確確認該版本 tag 已推送至遠端（commit push 與 tag push 是獨立操作，tag 可能靜默未推）：

```bash
git ls-remote --tags origin 'refs/tags/v<TAG_VERSION>'
```

（例：`git ls-remote --tags origin 'refs/tags/v1.2.3'`）
確認輸出包含精確版本 tag，而非僅有舊版 tag；若輸出為空，提示使用者執行 `git push --tags`。

> **若目標 repo 有 tag-triggered CI/CD**（如 GitHub Release 自動發布）：git tag 在 merge 之前就已推送，可能觸發生產部署流程。評估風險後再決定是否繼續；或改為 merge 後在 main 上重新 tag。

---

CI 全綠後 squash merge，並取得 merge commit SHA（供 Step 8b Jira comment 使用）：

```bash
gh pr merge {{pr_number}} --squash --delete-branch
```

```bash
gh pr view {{pr_number}} --json mergeCommit -q .mergeCommit.oid
```

記下輸出的 SHA 作為 `{{merge_commit_sha}}`，回報給使用者。

---

### Step 8 — Spectra Archive + Jira Sync（收尾）

PR merge 完成後，同步 spec 狀態與 Jira ticket，結束此開發循環。兩個小節均為**選用**——無 spectra change 或無 Jira issue 時直接跳過。

#### 8a — Spectra Archive

若本次開發循環確定未建立 spectra change，直接跳過 Step 8a。

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

#### 8b — Jira Sync

**偵測 Jira Issue Key**：

merge 後 branch 已被 `--delete-branch` 刪除，改從 PR title / body 提取：

```bash
gh pr view {{pr_number}} --json title,body -q '.title + " " + (.body // "")'
```

若指令本身以非零退出碼失敗，停止並回報錯誤，詢問使用者手動提供 key。
若指令成功但輸出中無符合 `[A-Z]{2,}-[0-9]+` 格式的字串（如 `ABC-123`），詢問使用者提供 key，或跳過 Step 8b。

**取得 transitions（序列），再並行執行 transition + comment**：

先呼叫 `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`（`issueId`：`{{jira_issue_key}}`）取得 transition 清單。若呼叫失敗，停止並回報錯誤給使用者。

選擇語意最接近「已完成開發並合併」的選項（常見：`Done`、`Merged`、`Released`、`Closed`）。若不確定，詢問使用者確認後再執行。

確認 transition 後，以下兩個 MCP 呼叫**可同時送出**（無相依性）；任一失敗均須回報，不得靜默繼續：

- `mcp__claude_ai_Atlassian__transitionJiraIssue`：將 `{{jira_issue_key}}` 移至選定狀態
- `mcp__claude_ai_Atlassian__addCommentToJiraIssue`：新增以下格式 comment：

```text
PR #{{pr_number}} 已 squash merge 至 main。
Merge commit：{{merge_commit_sha}}
```

若 Step 8a 有 archive spectra change，comment 一併附上：

```text
Spectra change `{{change_name}}` 已 archive，spec 狀態已更新為完成。
```

完成後，向使用者回報：Spectra archive 狀態（已 archive / 已跳過）、Jira ticket 狀態（已 transition 至 `{{selected_state}}` + comment 已寫入 / 已跳過 / 失敗原因）。

---

## 常見問題處理

<!-- KEEP IN SYNC WITH ../pr-review-cycle-mob/SKILL.md (same FAQ row for pr-test-analyzer anti-patterns). If you update one, update both. -->

| 問題 | 處理方式 |
|------|----------|
| pr-test-analyzer 怎麼避開「假測試 / presence-only / no-CI」三種陷阱？ | 三個 anti-pattern 必檢：(1) **Fake test**（mutation-testing 視角的反向版）— test case 邏輯本身有 silent bug，所有 case PASS 但其中某 case 的測試動作根本沒生效（例：環境變數覆寫測試走了 unset 分支、empty 值沒實際 export，結果跟另一個 case 跑同樣 path）；「all green」掩護從未被測到的情境。修法：mutation testing intuition — 故意把 production code 改錯一行、看該 test case 是否**真的** fail；不 fail 就是 fake test。(2) **Presence test ≠ contract test** — `grep function_name` 確認函式被叫只是最弱形式；若 invariant 是「函式必須**用正確 args** 呼叫」（例：deploy script 必須以**正確的 default-context** 呼叫對應 guard helper），test 必須驗完整 contract（`function_name <expected_arg>` 配對），不能只測 function name presence。(3) **Test 沒進 CI = 半成品 test** — 提交 test file 但沒 CI / pre-commit / git-hook / `make test` target 任一觸發機制，regression 只在 operator 手跑時暴露；operator 通常不會自發跑 test。修法：是否進 CI 應跟「測什麼」「怎麼測」並列為 test 設計三要素。機制依專案技術棧選：Python repo 常用 pre-commit local hook + `files:` regex；TS/JS repo 用 husky / lefthook；Go / Rust repo 用 `make test` + CI workflow `step: run: make test`。共通要求：改 production code 觸發自動測。|
| Step 3 agent 沒有 git diff 可讀 | 先執行 Step 1 建立 branch/PR |
| 找不到本地 CI 指令 | 讀 `Makefile` / `package.json` / `pyproject.toml`，或問使用者 |
| Linter 失敗 | 查對應工具的 `--fix` 選項（ruff: `ruff check --fix`；eslint: `--fix`；gofmt: 自動格式化） |
| Type checker 失敗 | 確認 untyped 第三方庫的設定（mypy: `follow_imports = skip`；tsc: 加 `@types/<pkg>` 或設 `skipLibCheck: true`）|
| Security scanner 失敗 | 加對應工具的忽略註解（bandit: `# nosec BXXX`；等），並在 PR 說明原因 |
| Re-review 發現新問題 | 回 Step 4，不要直接 merge |
| CI 與本地結果不一致 | 以本地 CI 為準，比對 CI/本地的工具版本與環境變數差異 |
| 想跳過某個 review agent | 可以，但必須說明原因 |
| spectra archive validation 失敗 | `spectra analyze {{change_name}}` 查看 Critical 錯誤，修正後再 archive；`--no-validate` 需使用者明確指示才使用 |
| Jira key 無法從 branch / PR 偵測 | 詢問使用者提供 key（格式：`PROJECT-123`），或確認此 PR 無對應 Jira issue 後跳過 |
| Jira transition 選項不確定 | 呼叫 `getTransitionsForJiraIssue` 列出所有選項後詢問使用者確認 |
| Jira MCP 需認證 | Atlassian MCP 需要 OAuth；若工具回傳 auth 錯誤，提示使用者在 claude.ai 完成授權 |
| 使用者跳過 bump 但事後需要版本標記 | 建立 release branch，在上面跑 [`/bump-version`](../bump-version/SKILL.md)，再開 PR merge 進 main（CI 通過 + 確認 CHANGELOG 正確即可合併，不需跑完整 review cycle；若 main 已有新 commit，CHANGELOG 可能含多餘項目，需人工確認） |

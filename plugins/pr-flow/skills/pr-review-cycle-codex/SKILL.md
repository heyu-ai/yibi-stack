---
name: pr-review-cycle-codex
type: know
scope: global
description: >
  [DEPRECATED] codex-only 強化版。新 session 請依規模選擇：小型 PR 用
  `/pr-review-cycle`（Claude-only，4 subagent 平行）；中大型或高風險 PR 用
  `/pr-review-cycle-mob`（mob review by multiple frontier-model agents，自動
  偵測 codex / gemini / 本地 open-weights，≥2 家可用即啟動 debate + aggregate）。
  本 skill 內容保留供既有 session / muscle memory 不中斷。
  觸發情境：「跑 PR cycle + codex」「pr-review-cycle-codex」「PR 流程加 cross-model review」「cross model review」「jira sync」「spectra archive」
---

# PR Review Cycle（Codex 強化版）— [DEPRECATED]

> **[DEPRECATED]** 本 skill 為 codex-only 強化版的早期設計。新 session 請依規模選擇：
>
> - 小型 PR / 快速合併 → [`/pr-review-cycle`](../pr-review-cycle/SKILL.md)
>   （Claude-only，4 subagent 平行）
> - 中大型或高風險 PR → [`/pr-review-cycle-mob`](../pr-review-cycle-mob/SKILL.md)
>   （mob review，自動偵測 codex / gemini / open-weights，≥2 家啟動 debate）
>
> 本檔案內容保留是為了不中斷既有 muscle memory，未來會移除。

延伸 `/pr-review-cycle`，在合併前追加 OpenAI Codex 的獨立 review + adversarial challenge，
以 cross-model 第二意見補強 Claude 系 reviewer 可能集體錯過的盲點。

Step 1–6 與 `/pr-review-cycle` 完全相同；本 skill 新增 Step 7–8，將 merge 移至 Step 9，收尾 Spectra Archive + Jira Sync 為 Step 10。

## 使用方式

```text
/pr-review-cycle-codex
/pr-review-cycle-codex #<PR number>   ← 已有 PR 時直接跳 Step 2
```

---

## 前置需求（在 Step 1 之前確認，節省時間）

Steps 1–6 可能需要 20–40 分鐘，請先執行以下確認，任一不符就停止並修正後再開始：

```bash
# bash call 1：確認 binary
which codex 2>/dev/null && echo "PREREQ: BINARY_OK" || echo "PREREQ: NOT_FOUND -- stop here"
```

```bash
# bash call 2（BINARY_OK 後執行）：確認 API key（無 key 時 exit 0，不阻斷流程）
env | grep -qE '^(CODEX_API_KEY|OPENAI_API_KEY)=.' && echo "AUTH: KEY_SET" || true
```

```bash
# bash call 3（call 2 無輸出時執行）：確認 auth.json（預設路徑 ~/.codex；自訂 CODEX_HOME 見 FAQ）
test -f ~/.codex/auth.json && echo "AUTH: FILE_EXISTS" || echo "AUTH: NOT_AUTHED"
```

| 輸出 | 處理 |
|------|------|
| `PREREQ: NOT_FOUND` | `npm install -g @openai/codex`；或退回 `/pr-review-cycle` |
| `AUTH: NOT_AUTHED` | `codex login`（或設 `$OPENAI_API_KEY`） |
| `AUTH: FILE_EXISTS` | 繼續，但 auth.json 存在不代表 token 有效；若 Step 7 報 auth 錯誤，執行 `codex login` 更新 |
| `PREREQ: BINARY_OK` + `AUTH: KEY_SET` 或 `FILE_EXISTS` | 繼續 Step 1 |

---

## Workflow

### Step 1–6 — 照 `/pr-review-cycle` 執行

完全照 `/pr-review-cycle` 的 Step 1–6 執行，不重複描述。
`{{pr_number}}` 為 Step 1 建立 PR 後取得的 PR 編號，後續步驟均使用此值。

| Step | 內容 |
|------|------|
| 1 | 建立 PR（commit + push + gh pr create） |
| 2 | Simplify（/simplify，作為獨立 commit） |
| 3 | Parallel review（4 個 Claude agent） |
| 4 | Fix（Critical → Important） |
| 5 | Re-review |
| 6 | CI Check（`gh pr checks {{pr_number}} --watch`） |

CI 全綠後才進 Step 7。

---

### Step 6.5 — Cross-Model Review 路徑選擇（CI 通過後）

CI 全綠後，選擇以下其中一條路徑執行 cross-model review：

| 路徑 | 指令 | 適用情境 |
|------|------|---------|
| **A：Codex Review + Challenge（原有流程）** | `Skill(skill="codex", args="review")` | 本地 codex CLI 可用、需要 adversarial challenge |
| **B：claude ultrareview（新選項）** | `claude ultrareview {{pr_number}}` | codex 不可用、CI 非互動式環境、需要雲端並行 multi-agent review |

### 路徑 B：claude ultrareview

```bash
claude ultrareview {{pr_number}}
```

> **注意**：`claude ultrareview` 為付費功能（billed），執行前確認使用者已授權計費。
> 選擇路徑 B 後，**跳過 Step 7 / Step 8**，直接進 Step 9（Merge）。
> ultrareview 輸出已包含 review findings；Critical findings 處理方式與 Step 7 GATE: FAIL 相同。

選擇路徑 A 繼續以下 Step 7。

---

### Step 7 — Codex Review（硬性 gate）

觸發方式：`Skill(skill="codex", args="review")`（codex skill 以 `args` 做 mode 偵測）

Codex 會對 PR 的完整 branch diff 做 review，輸出包含 `[P1]`（Critical）/ `[P2]`（Important）
分級的 findings，末尾顯示 PASS/FAIL gate，並輸出一行 `Recommendation:` 摘要。

**若 codex skill 本身失敗（auth / binary 錯誤）**：展示錯誤訊息給使用者 → 回到「前置需求」
重新確認 → 不可視為 GATE: PASS 繼續前進。

**若 codex skill 因 flag 衝突失敗**（錯誤訊息含 `[PROMPT] cannot be used with --base`）：
`codex review` 的 `--base` 與 positional `[PROMPT]` 互斥。直接執行 fallback：

```bash
codex review --base {{base_branch}} -c 'model_reasoning_effort="high"'
```

`codex review` 不支援 `-C` flag，從正確 cwd 執行即可。`--base` 已足夠讓 codex 找到 diff，不需要額外 prompt。輸出格式與 Skill 觸發相同，[P1]/[P2] gate 判定不變。

**解讀 gate 結果：**

**GATE: PASS** → 向使用者展示 `Recommendation:` 行與 cross-model analysis（哪些是 Claude
沒抓到、Codex 抓到的），然後進 Step 8。

**GATE: FAIL（N critical findings）**：

1. 列出每一個 `[P1]` finding，附 codex 的說明與 `Recommendation:` 行
2. 展示 cross-model analysis（Claude 系漏抓了什麼）
3. **強制**回 Step 4 修正：
   - 依序處理每個 `[P1]`
   - 修完執行本地 CI（參照 Step 4 的 CI 指令查找邏輯）
   - commit + push
4. CI 自動重跑（回 Step 6 等待）
5. CI 通過後重新執行 Step 7

Codex 修正後**不必**重跑 Step 3 / Step 5（修正範圍由 Codex finding 界定）；
若修正涉及 3 個以上新檔案，則回 Step 5 重跑 Claude review。

**Circuit breaker**：若重試達 3 次仍 GATE: FAIL，停止自動重試，向使用者呈現持續出現的
`[P1]` findings，詢問：「誤判、還是需要更多修改時間、還是退回重新設計 PR？」等待明確指示後才繼續。

**誤判處理**（使用者聲明 finding 不成立）：

- agent 不可自行 override
- 要求使用者在 PR description 補上說明（例：「Codex flagged X — 確認為誤判，原因 Y」）
- 使用者確認補上後，agent 才繼續（不自行輪詢 GitHub；明確詢問使用者是否已更新）

---

### Step 8 — Codex Challenge（adversarial 第二意見）

觸發方式：`Skill(skill="codex", args="challenge")`

Codex 以「破壞者」視角嘗試找出 race condition、security hole、資源洩漏、資料靜默損毀等問題。
此模式無形式化 gate，輸出含 `[codex thinking]` 推理行與最終散文分析 + `Recommendation:` 行；
agent 分類 findings 時以最終散文為準，忽略 `[codex thinking]` 推理行。

**若 codex skill 的 `--json` streaming 無輸出**：改用 Write tool 寫 prompt 再 stdin 傳入的 fallback（去掉 `--json` flag）：

用 Write tool 把 prompt 寫到 `/tmp/codex-challenge-prompt.txt`：

```text
Review the git diff against {{base_branch}} and find adversarial problems.
Run git diff {{base_branch}}...HEAD to see the diff.
Find edge cases, race conditions, security holes, resource leaks, silent data corruption.
Be adversarial. No compliments.
```

```bash
WT=$(git rev-parse --show-toplevel)
```

```bash
codex exec -C "$WT" -s read-only -c 'model_reasoning_effort="high"' < /tmp/codex-challenge-prompt.txt 2>&1
```

```bash
rm -f /tmp/codex-challenge-prompt.txt
```

**Agent 分級 findings：**

| 嚴重度 | 特徵 | 處置 |
|--------|------|------|
| **Critical** | race condition、security hole、auth bypass、silent data corruption | 強烈建議修；使用者以明確語句（「knowingly ship」「已知悉、接受風險」等）拒絕才放行 |
| **Important / Minor** | edge case、資源管理、效能問題 | 列入 PR description 留紀錄，不阻擋 merge |

若使用者給出模糊回應（「之後再修」「先這樣」），不構成明確拒絕，需再次確認：
「這個 Critical finding 我會記錄為 knowingly shipped。請確認：你理解此風險並接受在此次 PR 中不修正？」

**把完整 challenge 輸出貼到 PR comment：**

用 Write tool 把 challenge 輸出寫入 `/tmp/codex-challenge-report.md`，格式如下：

```text
## Codex Challenge Report

<challenge 完整輸出>

---
*Generated by /pr-review-cycle-codex Step 8*
```

```bash
gh pr comment {{pr_number}} --body-file /tmp/codex-challenge-report.md
```

```bash
rm -f /tmp/codex-challenge-report.md
```

若使用者拒絕修 Critical finding，在 PR description 補上 Known Issues 段落：

```bash
CURRENT_BODY=$(gh pr view {{pr_number}} --json body -q .body 2>/dev/null)
if [ -z "$CURRENT_BODY" ]; then
  echo "ERROR：gh pr view 失敗，無法讀取 PR description。請手動在 PR 補上 Known Issues。"
else
  TMPFILE=$(mktemp)
  printf '%s\n\n---\n## Codex Challenge -- Known Issues\n- <finding 摘要>：knowingly shipped -- <使用者提供的原因>\n' \
    "$CURRENT_BODY" > "$TMPFILE"
  gh pr edit {{pr_number}} --body-file "$TMPFILE"
  rm -f "$TMPFILE"
fi
```

---

### Step 9 — Merge

### Pre-merge 確認：版本 bump

執行 `gh pr merge` 之前，先暫停並向使用者確認：

> 此次變更是否需要 bump 版本？
>
> - **需要** → 請先執行 [`/bump-version`](../bump-version/SKILL.md)（會在 feature branch 上 commit 版本檔 + CHANGELOG + git tag + push）。
>   完成後**回到 Step 6 CI Check**（`gh pr checks {{pr_number}} --watch`，新 commit 觸發新一輪 CI），等待全綠後再回到本步驟繼續 merge。
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

所有 codex 問題處理完後，squash merge 並驗證結果：

```bash
# bash call 1：執行 merge
gh pr merge {{pr_number}} --squash --delete-branch
```

```bash
# bash call 2：取得結果（讀輸出判斷 state 是否為 MERGED，並記下 merge commit SHA）
gh pr view {{pr_number}} --json state,mergeCommit -q '{state: .state, sha: .mergeCommit.oid}'
```

確認 `state` 為 `MERGED` 後，記下 `sha` 作為 `{{merge_commit_sha}}`，回報給使用者。

---

### Step 10 — Spectra Archive + Jira Sync（收尾）

PR merge 完成後，同步 spec 狀態與 Jira ticket，結束此開發循環。兩個小節均為**選用**——無 spectra change 或無 Jira issue 時直接跳過。

#### 10a — Spectra Archive

若本次開發循環確定未建立 spectra change，直接跳過 Step 10a。

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

#### 10b — Jira Sync

**偵測 Jira Issue Key**：

merge 後 branch 已被 `--delete-branch` 刪除，改從 PR title / body 提取：

```bash
gh pr view {{pr_number}} --json title,body -q '.title + " " + (.body // "")'
```

若指令本身以非零退出碼失敗，停止並回報錯誤，詢問使用者手動提供 key。
若指令成功但輸出中無符合 `[A-Z]{2,}-[0-9]+` 格式的字串（如 `ABC-123`），詢問使用者提供 key，或跳過 Step 10b。

**取得 transitions（序列），再並行執行 transition + comment**：

先呼叫 `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`（`issueId`：`{{jira_issue_key}}`）取得 transition 清單。若呼叫失敗，停止並回報錯誤給使用者。

選擇語意最接近「已完成開發並合併」的選項（常見：`Done`、`Merged`、`Released`、`Closed`）。若不確定，詢問使用者確認後再執行。

確認 transition 後，以下兩個 MCP 呼叫**可同時送出**（無相依性）；任一失敗均須回報，不得靜默繼續：

- `mcp__claude_ai_Atlassian__transitionJiraIssue`：將 `{{jira_issue_key}}` 移至選定狀態
- `mcp__claude_ai_Atlassian__addCommentToJiraIssue`：新增以下格式 comment：

```text
PR #{{pr_number}} 已 squash merge 至 main。
Merge commit：{{merge_commit_sha}}
Codex review：GATE PASS（Step 7）；Challenge report 已附於 PR comment（Step 8）。
```

若 Step 10a 有 archive spectra change，comment 一併附上：

```text
Spectra change `{{change_name}}` 已 archive，spec 狀態已更新為完成。
```

完成後，向使用者回報：Spectra archive 狀態（已 archive / 已跳過）、Jira ticket 狀態（已 transition 至 `{{selected_state}}` + comment 已寫入 / 已跳過 / 失敗原因）。

> **下一步建議**：跑 `/pr-retro` 收尾這個 session（agent 會從 PR context 推論 5 題草稿給你校準，寫入專屬 retro tag 不污染 handover-back）。

---

## 常見問題

| 問題 | 處理方式 |
|------|----------|
| codex 安裝或認證問題 | 見「前置需求」表格 |
| 設定了自訂 `CODEX_HOME`，bash call 3 回報 `NOT_AUTHED` | bash call 3 固定查 `~/.codex/auth.json`；請在 terminal 手動確認實際路徑後再繼續 |
| codex review 報 `[PROMPT] cannot be used with --base` | `--base` 與 positional prompt 互斥；移除 prompt 字串，只用 `codex review --base <branch>` 見 Step 7 |
| codex review 跑到錯誤的 repo | `codex review` 不支援 `-C` flag；確保從 git repo 根目錄執行（AP3 Sub-class A） |
| codex challenge `--json` 模式無輸出 | 改用 stdin fallback（不加 `--json`），見 Step 8 |
| codex review timeout（>5 分鐘）| 重試一次；持續失敗查 `~/.codex/logs/` |
| codex challenge timeout（>10 分鐘）| 重試一次；持續失敗查 `~/.codex/logs/` |
| codex review FAIL 但確認是誤判 | 在 PR description 記錄理由 + reviewer 確認，agent 不可自行 override |
| codex review 連續 3 次 FAIL | 觸發 circuit breaker，停止重試，詢問使用者：誤判 / 需更多時間 / 退回重新設計 |
| codex review PASS 但 challenge 找到 Critical | 依 Step 8 分級處置；Critical 需使用者明確拒絕才能 knowingly ship |
| codex 跑去讀 `.claude/skills/` 噪音檔案 | codex skill 內建 filesystem boundary 防護；若仍發生，建議重跑 |
| 想跳過 challenge 只跑 review | 用 `/pr-review-cycle`；本 skill 是「全套 cross-model 強化」入口，不提供半套選項 |
| codex 無法使用、想用 claude ultrareview | 在 Step 6.5 選擇路徑 B，執行 `claude ultrareview {{pr_number}}`；路徑 B 跳過 Step 7/8 |
| claude ultrareview 報計費錯誤 | ultrareview 為付費功能，確認帳戶已授權後重試 |
| Step 1–6 遇到問題 | 參照 `/pr-review-cycle` 的常見問題表（完全共用） |
| spectra archive validation 失敗 | `spectra analyze {{change_name}}` 查看 Critical 錯誤，修正後再 archive；`--no-validate` 需使用者明確指示才使用 |
| Jira key 無法從 branch / PR 偵測 | 詢問使用者提供 key（格式：`PROJECT-123`），或確認此 PR 無對應 Jira issue 後跳過 |
| Jira transition 選項不確定 | 呼叫 `getTransitionsForJiraIssue` 列出所有選項後詢問使用者確認 |
| Jira MCP 需認證 | Atlassian MCP 需要 OAuth；若工具回傳 auth 錯誤，提示使用者在 claude.ai 完成授權 |
| 使用者跳過 bump 但事後需要版本標記 | 建立 release branch，在上面跑 [`/bump-version`](../bump-version/SKILL.md)，再開 PR merge 進 main（CI 通過 + 確認 CHANGELOG 正確即可合併，不需跑完整 review cycle；若 main 已有新 commit，CHANGELOG 可能含多餘項目，需人工確認） |

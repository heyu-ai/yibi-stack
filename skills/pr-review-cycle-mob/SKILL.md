---
name: pr-review-cycle-mob
type: know
scope: global
description: >
  Mob review by multiple frontier-model agents — 完整 PR 生命週期含跨家 LLM
  group review：自動偵測 codex / gemini，≥1 家即啟動
  R1 獨立 + R2 交叉 debate + aggregate；fix → re-review 直到全員 LGTM（含
  actionable NIT）→ 人類快速複查 → CI → merge → spectra archive + Jira sync。
  適用中大型 PR / 高風險改動 / 跨家視角壓力測試。小型 feature 或本地快速 review
  請改用 `/pr-review-cycle`（Claude-only，4 個 pr-review-toolkit subagent 平行）。
  偵測不到任何外部模型時提示使用者退回 `/pr-review-cycle`。
  觸發情境：「mob review」「group review」「multi-model PR review」「跨家 LLM review」
  「pr-review-cycle-mob」「frontier model 群審」「找 codex + gemini 一起 review」
---

# PR Review Cycle — Mob（Multi-Agent Group Review）

由多位 frontier-model agent 組成 mob 對 PR 進行群體 review 的完整流程，
適用任何技術棧（Python / JS / Go / Flutter / 其他）的 git 專案。

**何時用 mob 模式**：

- 中大型 PR（>200 行 diff，或跨多 module）
- 高風險改動（auth、payment、migration、infra、security-sensitive）
- 想在合併前壓力測試「跨家 LLM 是否一致警示」
- 願意花 10–30 分鐘換更廣的視角覆蓋

**何時用 `/pr-review-cycle`（Claude-only）**：

- 小型 feature / bug fix / refactor
- 想快速合併、不想啟動多家模型
- 沒裝 codex 且沒裝 gemini

**核心理念**：當 codex / gemini 偵測得到時，把它們和 Claude 開成**同步平行**的
reviewer 群，先各自獨立評審，再交叉看彼此意見 debate，產出 aggregated 最終報告。
Coding agent（Claude main session）按報告修改，再開一輪 group review，循環到全員
LGTM（含 actionable NIT）為止。最後人類花幾分鐘掃一眼所有改動，當場提出疑慮，由
reviewer lead（Claude main）即時回應排除——比找一兩個資深工程師更快、視角也更廣。

偵測不到任何外部模型 → 提示使用者退回 `/pr-review-cycle`，本 skill 終止
（不在 mob skill 內 fallback，避免語意混淆）。

## 使用方式

```text
/pr-review-cycle-mob
/pr-review-cycle-mob #<PR number>   ← 已有 PR 時直接跳 Step 2
```

---

## Step 0 — Reviewer 偵測（決定流程模式）

三個 bash calls，每個彼此獨立，快速偵測完畢：

```bash
# Codex CLI binary
which codex >/dev/null 2>&1 && echo "CODEX: BINARY_OK" || echo "CODEX: NOT_FOUND"
```

```bash
# Codex auth（KEY_SET 或 FILE_EXISTS 任一即可）
test -n "$CODEX_API_KEY" -o -n "$OPENAI_API_KEY" && echo "CODEX_AUTH: KEY_SET" || \
test -f ~/.codex/auth.json && echo "CODEX_AUTH: FILE_EXISTS" || echo "CODEX_AUTH: NOT_AUTHED"
```

```bash
# Gemini CLI binary
which gemini >/dev/null 2>&1 && echo "GEMINI: BINARY_OK" || echo "GEMINI: NOT_FOUND"
```

```bash
# Gemini auth（GEMINI_API_KEY 或 GOOGLE_API_KEY 任一即可）
test -n "$GEMINI_API_KEY" -o -n "$GOOGLE_API_KEY" && echo "GEMINI_AUTH: KEY_SET" || \
test -f ~/.gemini/credentials.json && echo "GEMINI_AUTH: FILE_EXISTS" || echo "GEMINI_AUTH: NOT_AUTHED"
```

### 模式判定

外部 reviewer「可用」= binary OK + auth OK（Codex 或 Gemini）。

| 可用外部 reviewer | 動作 |
|---:|---|
| 0 | **退回 `/pr-review-cycle`**（Claude-only 即足夠；本 skill 終止） |
| **1**（Codex 或 Gemini）| **2-voice mob**（Claude + 1 外部，cross-model debate 已有意義） |
| **2**（Codex + Gemini）| **3-voice full mob**（最廣覆蓋） |

向使用者回報偵測結果與選擇的模式，等待確認再繼續：

```text
偵測結果：
- Claude  ✓ 永遠可用（pr-review-toolkit）
- Codex   ✓ / ✗
- Gemini  ✓ / ✗ (optional)

外部 reviewer 計數：{{N}}/2
模式：{{2-voice-mob | 3-voice-full-mob | REDIRECT}}

  ← 若 REDIRECT：本 skill 終止，請改執行 /pr-review-cycle
進入 Step 1？
```

---

## Workflow（mob review 模式）

### Step 1 — 建立 PR

若尚未建立 PR，依序執行：

```bash
git branch --show-current
```

```bash
git -C "$(git rev-parse --show-toplevel)" status --short
```

確認在 feature branch 後 commit + push + 建立 PR：

```bash
git add <files>
```

```bash
git commit -m "..."
```

```bash
git push -u origin HEAD
```

PR body 用 Write tool 先寫到 `/tmp/pr-body.md`（避免 heredoc 觸發 hook），再傳入：

```bash
gh pr create --title "..." --body-file /tmp/pr-body.md
```

```bash
rm -f /tmp/pr-body.md
```

若專案有 `/commit-commands:commit-push-pr` slash command，可直接執行（自動 commit + push + PR）。

記下 PR number 作 `{{pr_number}}`，記下 base branch 作 `{{base_branch}}`（通常是 `main`）。

---

### Step 2 — Simplify

執行 `/simplify` 對 PR 全部變更跑三向度 review（reuse / quality / efficiency）。
先 simplify 讓程式碼進入最終形態，group review 才針對真實結果評審而非過渡狀態。

無改動 → 直接進 Step 3。
有改動 → 作為**獨立 commit**（方便每位 reviewer 看 diff）：

```bash
git add -A
```

```bash
git commit -m "refactor(...): simplify per /simplify review"
```

```bash
git push
```

---

### Step 3 — Round 1：獨立平行 review

**目的**：四個 voice（Claude / Codex / Gemini / Open-weights）各自獨立評審，
**互不參考**，避免錨定偏誤。每個 voice 把 findings 寫到 `/tmp/pr-review/<voice>-r1.md`。

#### 3.1 — 準備工作目錄與共用 prompt

```bash
mkdir -p /tmp/pr-review
```

```bash
git -C "$(git rev-parse --show-toplevel)" diff "{{base_branch}}"...HEAD > /tmp/pr-review/diff.patch
```

```bash
git -C "$(git rev-parse --show-toplevel)" diff "{{base_branch}}"...HEAD --name-only > /tmp/pr-review/changed-files.txt
```

用 Write tool 把 review prompt 寫到 `/tmp/pr-review/prompt-r1.md`：

```text
你是資深 code reviewer。對以下 PR diff 做獨立 review。

Base branch: {{base_branch}}
PR #: {{pr_number}}
Diff: 見 /tmp/pr-review/diff.patch
變更檔案清單: 見 /tmp/pr-review/changed-files.txt

輸出格式（嚴格遵守，便於後續 aggregate）：

## Summary
<1-2 句總評>

## Findings

### [Critical] <短標題>
- File: <path:line>
- Issue: <問題描述>
- Suggested fix: <如何修>

### [Important] <短標題>
...

### [Actionable NIT] <短標題>
- 必須是具體可執行的小修正（命名、註解錯誤、import 順序等），非主觀偏好

## Verdict
- LGTM / NEEDS_CHANGES

聚焦：
- 邏輯錯誤、race condition、security hole、silent failure、resource leak
- 測試覆蓋缺口（critical path 未測試）
- 文件 / comment 與實作不一致
- 不要列「程式碼風格偏好」「主觀美學」這類 non-actionable items
- Be skeptical, be terse, no compliments
```

#### 3.2 — 平行啟動 3 個 voice

**在同一則訊息中**並行送出所有 reviewer 呼叫（只送可用的 voice）：

##### Claude voice（pr-review-toolkit 4 subagents）

平行啟動四個 Task subagent（每個產生獨立 finding，最後由 lead 合併為 Claude voice）：

| Subagent | 聚焦 |
|---|---|
| `code-reviewer` | 規範合規、bug、邏輯錯誤 |
| `silent-failure-hunter` | 靜默失敗、exception 吞噬 |
| `pr-test-analyzer` | 測試覆蓋缺口 |
| `comment-analyzer` | 文件 / comment 準確性 |

四個都跑完後，lead 用 Write tool 合併為 `/tmp/pr-review/claude-r1.md`（依上述輸出格式）。

##### Codex voice（CODEX_OK 時）

```bash
codex review -C "$(git rev-parse --show-toplevel)" --base "{{base_branch}}" -c 'model_reasoning_effort="high"' > /tmp/pr-review/codex-r1.md 2>&1
```

`-C` 防 CWD 漂移（AP3 Sub-class A）。`--base` 與 positional prompt 互斥，不能再加
prompt 字串；codex 內建 review 模式自動產生 [P1]/[P2] 分級，lead 後續轉成
Critical/Important。

##### Gemini voice（GEMINI_OK 時）

Gemini CLI 不接受 stdin prompt + diff path 的多檔組合，先串成單一檔：

```bash
cat /tmp/pr-review/prompt-r1.md /tmp/pr-review/diff.patch > /tmp/pr-review/gemini-r1-input.md
```

```bash
gemini -m gemini-3.1-pro-preview -p "@/tmp/pr-review/gemini-r1-input.md" > /tmp/pr-review/gemini-r1.md 2>&1
```

```bash
rm -f /tmp/pr-review/gemini-r1-input.md
```

若無 `gemini-3.1-pro-preview` 權限，依序 fallback：`gemini-3-pro-preview` →
`gemini-2.5-pro`（用 verify-gemini-models skill 確認可用模型）。

#### 3.3 — Sanity check

```bash
ls -lh /tmp/pr-review/*-r1.md
```

任一檔案 < 200 bytes 或內容只有錯誤訊息 → 重跑該 voice。連續 2 次失敗 → 把該 voice
標記為「unavailable for this PR」，記錄在最終 aggregated 報告，不阻塞流程。

---

### Step 4 — Round 2：交叉 debate

**目的**：每個 voice 看其他 voice 的 R1 findings，表態同意 / 反對 / 補充，
逼出共識與爭議。

#### 4.1 — 產生 R1 aggregate

用 Write tool 把所有 R1 內容串成 `/tmp/pr-review/r1-aggregate.md`（只包含有產出的 voice）：

```text
# Round 1 Findings — 各 reviewer 獨立結果

## Claude
<貼 /tmp/pr-review/claude-r1.md>

## Codex（若 CODEX_OK）
<貼 /tmp/pr-review/codex-r1.md>

## Gemini（若 GEMINI_OK）
<貼 /tmp/pr-review/gemini-r1.md>
```

#### 4.2 — Round 2 prompt

用 Write tool 寫 `/tmp/pr-review/prompt-r2.md`：

```text
你剛剛在 Round 1 對這個 PR 做了 review。現在看其他 reviewer 的結果，
重新表態：

## Round 1 全員結果
<r1-aggregate 內容>

## 你的任務
針對其他 reviewer 提出的每一個 finding：
- AGREE: 同意，理由（可選）
- DISAGREE: 不同意，理由（必填）
- DUPLICATE: 與你 R1 的 X 重複
- UPGRADE/DOWNGRADE: 嚴重度應調整為 ___，理由

額外：
- 看完別人的 review 後，你 R1 漏掉了什麼？補上 [Critical/Important/NIT] 新項目。
- 你 R1 哪些項目看完別人意見後想撤回？標 WITHDRAW + 理由。

輸出格式：

## Cross-review verdict
<2-3 句：你對其他 reviewer 整體表現的看法>

## Per-finding response
### Other reviewer's finding: <原 finding 標題>
- Verdict: AGREE/DISAGREE/DUPLICATE/UPGRADE/DOWNGRADE
- Reason: ...

## New findings (R1 漏掉的)
### [Critical/Important/NIT] <標題>
- File / Issue / Fix

## Withdrawals (R1 我撤回的)
- <原標題>: 理由

## Final verdict
- LGTM / NEEDS_CHANGES
```

#### 4.3 — 平行送 R2 給每個 voice

每個 voice 用相同模式呼叫，但這次 prompt 是 R2，input 是 r1-aggregate（不是 raw diff）：

```bash
cat /tmp/pr-review/prompt-r2.md /tmp/pr-review/r1-aggregate.md > /tmp/pr-review/codex-r2-input.md
```

```bash
codex exec -C "$(git rev-parse --show-toplevel)" -s read-only -c 'model_reasoning_effort="high"' < /tmp/pr-review/codex-r2-input.md > /tmp/pr-review/codex-r2.md 2>&1
```

```bash
cat /tmp/pr-review/prompt-r2.md /tmp/pr-review/r1-aggregate.md > /tmp/pr-review/gemini-r2-input.md
```

```bash
gemini -m gemini-3.1-pro-preview -p "@/tmp/pr-review/gemini-r2-input.md" > /tmp/pr-review/gemini-r2.md 2>&1
```

只送可用的 voice（CODEX_OK / GEMINI_OK）。

Claude voice：lead 自己讀 r1-aggregate 後寫 `/tmp/pr-review/claude-r2.md`，不再開
subagent（避免 4×4 = 16 次 review 太多 noise）。

---

### Step 5 — Aggregator synthesis

Lead 讀完所有 R1 + R2 後，產出 `/tmp/pr-review/final.md`，分級：

| 階級 | 條件 | 處置 |
|---|---|---|
| **Consensus Critical** | ≥2 voice 標 Critical 且無人 DISAGREE | 必須修 |
| **Consensus Important** | ≥2 voice 標 Important 且無人 DISAGREE | 必須修 |
| **Disputed** | 1 voice 標 Critical/Important，其他 DISAGREE | 列出爭議點，使用者決定 |
| **Single-voice Critical** | 1 voice 標 Critical，其他未提 | 由 lead 評估：技術合理就升 Consensus；否則列 Disputed |
| **Actionable NIT** | 任 1 voice 標 NIT 且非主觀偏好 | **必須修**（user 強調 "all NITs cleaned up"）|
| **Withdrawn** | R2 標 WITHDRAW | 從清單剔除 |
| **Voice unavailable** | 該 voice R1/R2 連續 2 次失敗 | final.md 標註，不阻塞 |

`final.md` 格式：

```text
# Final Aggregated Review — PR #{{pr_number}}

## Mode
group-review（{{N}}/3 voices active）

## Consensus Critical（必修）
1. <finding>...

## Consensus Important（必修）
1. <finding>...

## Actionable NIT（必修，使用者要求 all NITs cleaned up）
1. <finding>...

## Disputed（使用者決策）
- Voice X 主張 Critical：<理由>
- Voice Y 反對：<理由>
- Lead 建議：<決策建議>

## Voices unavailable
- <voice>: <原因>
```

向使用者回報 final.md 摘要，等 Disputed 項目決策後進 Step 6。

---

### Step 6 — Fix（Critical → Important → NIT）

依序處理：

1. 修改程式碼
2. 跑本地 CI（先讀專案找 CI 指令）：

   ```bash
   grep -E "^(ci|test|check):" Makefile 2>/dev/null | head -5
   ```

   常見對應：

   | 技術棧 | 本地 CI |
   |---|---|
   | Python (make) | `make ci` |
   | Python (bare) | `uv run pytest` |
   | Node | `npm test` |
   | Go | `go test ./...` |
   | Flutter | `flutter test` |

   失敗就修好再繼續，不跳過。

3. commit（描述修了什麼，不要寫 "fix review comments"）：

   ```bash
   git commit -m "fix(...): ..."
   ```

   ```bash
   git push
   ```

修一批 commit 一批，方便 group re-review 看到對應 diff。

---

### Step 7 — Group re-review（直到全員 LGTM）

對**本次修改的檔案**重跑 Step 3 + Step 4（R1 + R2）。

```bash
git -C "$(git rev-parse --show-toplevel)" diff "{{base_branch}}"...HEAD --name-only > /tmp/pr-review/changed-files.txt
```

新一輪覆蓋舊的 r1/r2 檔案。

#### 收斂條件

**全員 LGTM** = 每個 active voice 在最新一輪都輸出：

- `Final verdict: LGTM`，且
- 無新增 [Critical] / [Important] / [Actionable NIT] finding

任一 voice 仍有 actionable item → 回 Step 6 修。

#### Circuit breaker

連續 **3 輪**仍未全員 LGTM → 停止自動重試，向使用者呈現持續未解的 findings，詢問：

```text
Group review 已跑 3 輪仍未全員 LGTM，剩餘未解項目：
1. <Voice X>: <finding> — 連續 3 輪標 Critical
2. <Voice Y>: <finding> — 第 2 輪新提

可能原因：
- 誤判（voice X 對 codebase context 理解不足）
- 需要更多修改時間（這項實際是大重構）
- 退回重新設計 PR（scope 太大）

請選擇：[誤判 / 繼續修 / 退回重設計]
```

等待明確指示後才繼續。

---

### Step 8 — Human quick pass（人類複查）

全員 LGTM 後，lead 給人類一份**幾分鐘可掃完**的摘要：

```bash
git -C "$(git rev-parse --show-toplevel)" diff "{{base_branch}}"...HEAD --stat
```

用 Write tool 寫 `/tmp/pr-review/human-summary.md`：

```text
# Human Quick Pass — PR #{{pr_number}}

## What changed（一頁摘要）
- 主要功能：...
- 改動範圍：N 檔案 +X/-Y 行
- 新增測試：...

## Group review 處理過的關鍵決策
1. <Consensus Critical 1>: 修法 = ...
2. <Disputed 項目>: 使用者選了 ___，理由 ...

## Voices final verdict
- Claude: LGTM
- Codex: LGTM（若 CODEX_OK）/ N/A
- Gemini: LGTM（若 GEMINI_OK）/ N/A

## 改動 hotspot（最值得人類眼睛看的 3 處）
1. <file:line> — <為何 hotspot>
2. ...
```

向使用者展示 summary 與 hotspot，邀請質疑：

```text
全員 LGTM。Hotspot 三處列在 /tmp/pr-review/human-summary.md。
有任何疑慮就在此 session 直接提，我（reviewer lead）即時回應。
無疑慮就回 "ship"，進 Step 9 CI check。
```

使用者提疑慮 → lead 直接回應（必要時調 R1/R2 原始 finding 佐證）；解不開的疑慮 →
回 Step 6 修；解開後使用者回 "ship" 才進 Step 9。

---

### Step 9 — CI Check

等待 GitHub Actions 全綠：

```bash
gh pr checks "{{pr_number}}" --watch
```

CI 失敗：本地重現（用 Step 6 找到的 CI 指令）→ 修 → commit + push → 重等。
本地 CI 是權威：CI 與本地不一致時以本地為準，檢查 CI 環境差異。

---

### Step 10 — Merge

**Pre-merge 確認：版本 bump**

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
BRANCH=$(git branch --show-current)
git fetch origin $BRANCH
git log --oneline -3 origin/$BRANCH
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

```bash
gh pr merge "{{pr_number}}" --squash --delete-branch
```

```bash
gh pr view "{{pr_number}}" --json mergeCommit -q .mergeCommit.oid
```

記下 SHA 作 `{{merge_commit_sha}}`，回報使用者。

---

### Step 11 — Spectra Archive + Jira Sync（收尾，選用）

兩小節均**選用**——無 spectra change 或無 Jira issue 直接跳過。

#### 11a — Spectra Archive

未建立 spectra change → 跳過。否則：

```bash
spectra list
```

找到對應 change（名稱通常與 feature branch 相近），**先回報名稱等待使用者確認**
（archive 不可逆，Rule 15）：

> 找到疑似對應的 spectra change：`{{change_name}}`。確認執行 archive？

確認後：

```bash
spectra archive "{{change_name}}" --yes
```

非零退出碼 → 停止回報。validation 有 Critical 錯誤 → `spectra analyze {{change_name}}`
查問題，修正後再 archive；`--no-validate` 需使用者明確指示才用。

#### 11b — Jira Sync

merge 後 branch 已被 `--delete-branch` 刪除，從 PR title / body 提取 Jira key：

```bash
gh pr view "{{pr_number}}" --json title,body -q '.title + " " + (.body // "")'
```

輸出無 `[A-Z]{2,}-[0-9]+` 格式字串 → 詢問使用者，或跳過 11b。

取得 transitions（先 sequential 再並行）：

- `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`（`issueId`：`{{jira_issue_key}}`）

選最接近「已完成開發並合併」的選項（常見：`Done` / `Merged` / `Released` / `Closed`）。
不確定就詢問使用者。

確認後**並行**送出（無相依性）：

- `mcp__claude_ai_Atlassian__transitionJiraIssue`：將 `{{jira_issue_key}}` 移至選定狀態
- `mcp__claude_ai_Atlassian__addCommentToJiraIssue`：comment 內容：

```text
PR #{{pr_number}} 已 squash merge 至 main。
Merge commit：{{merge_commit_sha}}
Group review 模式：{{N}}/3 voices LGTM（Claude / Codex / Gemini）。
```

11a 有 archive → 一併附上：

```text
Spectra change `{{change_name}}` 已 archive，spec 狀態已更新為完成。
```

完成後向使用者回報：spectra archive 狀態、Jira ticket 狀態。

> **下一步建議**：跑 `/pr-retro` 收尾這個 session，agent 從 PR context 推論 5 題草稿給你校準。

---

## Reviewer 呼叫快速對照表

| Voice | 偵測 | R1 呼叫 | R2 呼叫 | 預期輸出 |
|---|---|---|---|---|
| Claude | always | Task() pr-review-toolkit 4 subagents | lead 自己寫 claude-r2.md | finding markdown |
| Codex | `which codex` + auth | `codex review -C $REPO --base $BASE` | `codex exec -C $REPO -s read-only < input.md` | [P1]/[P2] 分級 |
| Gemini *(optional)* | `which gemini` + auth | `gemini -m gemini-3.1-pro-preview -p @input.md` | `gemini -m ... -p @input.md` | 散文格式（lead 解析）|

每個 voice 的 R1 / R2 都應寫到 `/tmp/pr-review/<voice>-r{1,2}.md`，由 lead 統一讀取
aggregate。

---

## 常見問題

| 問題 | 處理方式 |
|---|---|
| Step 0 全部 NOT_FOUND（0 家可用） | 本 skill 終止，改執行 `/pr-review-cycle`（Claude-only 即足夠） |
| Step 0 只偵測到 Codex（Gemini 無）| 進入 2-voice mob（Claude + Codex），正常流程 |
| Step 0 只偵測到 Gemini（Codex 無）| 進入 2-voice mob（Claude + Gemini），正常流程 |
| 偵測到 codex 但 auth 失敗 | `codex login`；或 `export OPENAI_API_KEY=...` |
| 偵測到 gemini 但 auth 失敗 | `gemini auth login`；或 `export GEMINI_API_KEY=...` |
| `gemini-3.1-pro-preview` 回 404 | 用 verify-gemini-models skill 重新確認可用模型，改用 `gemini-3-pro-preview` 或 `gemini-2.5-pro` |
| codex review 報 `[PROMPT] cannot be used with --base` | `--base` 與 positional prompt 互斥；移除 prompt 字串只留 `--base` |
| codex review 跑到錯 repo | gstack preamble 改了 CWD（AP3 Sub-class A）；`-C "$(git rev-parse --show-toplevel)"` 已防護 |
| 某個 voice R1/R2 連續失敗 | 標為 unavailable，不阻塞，aggregate 報告附原因 |
| R2 收到的 r1-aggregate 太大 voice 處理不了 | 把 raw diff 從 r1-aggregate 拿掉，只留 findings；diff 已在 r1 prompt 處理過 |
| 連續 3 輪未全員 LGTM | 觸發 circuit breaker，向使用者報告剩餘 findings 與三選一決策 |
| Disputed finding 使用者選 ignore | 在 PR description 補 Known Issues 段落記錄理由 |
| 人類快速複查時提出新疑慮 | reviewer lead（Claude main）即時回應；解不開 → 回 Step 6 修；解開 → 等使用者 "ship" |
| 想跳過 R2 只跑 R1 | 不行；R2 是 mob review 的核心價值（互相 debate）。想跳過就改用 `/pr-review-cycle`（Claude-only） |
| Linter / type-check 失敗 | `ruff check --fix` / `eslint --fix` / `mypy follow_imports = skip` 等 |
| Security scanner 失敗 | bandit `# nosec BXXX` 等忽略註解，PR 說明原因 |
| spectra archive validation 失敗 | `spectra analyze {{change_name}}`，修正後再 archive；`--no-validate` 需使用者明確指示 |
| Jira key 無法偵測 | 詢問使用者提供（`PROJECT-123` 格式），或確認無對應 ticket 後跳過 |
| Jira transition 選項不確定 | 列出所有 transition 詢問使用者確認 |
| Jira MCP auth 錯誤 | Atlassian MCP 需 OAuth；提示使用者在 claude.ai 完成授權 |
| 使用者跳過 bump 但事後需要版本標記 | 建立 release branch，在上面跑 [`/bump-version`](../bump-version/SKILL.md)，再開 PR merge 進 main（CI 通過 + 確認 CHANGELOG 正確即可合併，不需跑完整 review cycle；若 main 已有新 commit，CHANGELOG 可能含多餘項目，需人工確認） |

---

## 與其他 PR review skill 的關係

| Skill | 適用場景 | reviewer 組成 |
|---|---|---|
| `/pr-review-cycle` | 小型 feature / bug fix / refactor；快速合併 | Claude pr-review-toolkit 4 subagents 平行 |
| `/pr-review-cycle-mob`（本 skill）| 中大型 PR / 高風險改動 / 跨家視角壓力測試 | Claude + Codex（必要） + Gemini（選用）R1 獨立 + R2 debate |
| `/pr-review-cycle-codex` [DEPRECATED] | 只裝 codex 一家、想當硬性 gate 用 | Claude + codex（codex-only 強化版） |

本 skill 需要 ≥1 家外部 reviewer（Codex 或 Gemini）才啟動；0 家退回 `/pr-review-cycle`。
Gemini 為選用——只有 Codex 可用時仍跑 2-voice mob，兩者都可用時跑 3-voice full mob。

---
name: pr-retrospective
type: tool
scope: global
description: >
  單一 PR / session 收尾的 agent-led 回顧：agent 從 PR context（title/body/AC/commits/diff）
  自動推論 5 題草稿（problem / value / experience / lessons / improvement），
  呈現給使用者校準後寫入 mycelium handover（tags 含 "pr-retrospective" 以便 handover-back 排除），
  並依 Lesson Classifier 路由到 .claude/rules/ 子檔（bash/quoting/skill-authoring/irreversible/security）
  或 CLAUDE.md（fallback），再觸發 hookify:hookify、/claude-md-management:revise-claude-md、
  /claude-code-setup:claude-automation-recommender、superpowers:writing-skills 等下游 skill。
  觸發關鍵字：pr 回顧、pr retro、pr retrospective、session 收尾、merge 後檢討、
  五個問題回顧、AC 驗收、DoD 完成、what problem we want to solve、
  what value we deliver、lessons learned this session
---

# PR Retrospective — agent 推論 + 使用者校準

## 適用情境

- 剛完成 `/pr-review-cycle` 或 `/pr-review-cycle-mob` 流程，PR 已 merge（或即將 merge）
- 想為這個 PR session 留下結構化學習記錄
- 想讓 agent 幫你從 PR context 提煉「我們解決了什麼問題、學到了什麼」

## 不適用

| 情境 | 應使用 |
|------|--------|
| 週度工程回顧 | `/retro`（weekly engineering retrospective）|
| 查詢歷史 lessons | `/recall <keyword>` |
| 對話中途交班 | `/handover`（工作中交班，非 session 收尾）|

---

## 步驟

### Step 0 — 環境與 PR 解析（只在 skill 啟動時跑一次）

環境檢查 + 專案偵測 + SKILL_REPO 解析（prereqs check / case-free project detection / config）：

```bash
bash /Users/howie/Workspace/github/yibi-stack/plugins/pr-flow/skills/pr-retrospective/scripts/bootstrap.sh
```

Script stdout 輸出 `KEY=VALUE`，agent 解析並記住：

- `SKILL_REPO` — yibi-stack 根目錄路徑
- `ORIG_PROJECT` — 呼叫端 git repo 名稱
- `REAL_WORKDIR` — 目前工作目錄
- `BRANCH` — 目前分支名稱

> 其他使用者需依自己的 `skill_repo` 調整此路徑。

偵測 PR 號（從 ARGUMENTS 解析 `--pr <n>` 或 fallback 到 `gh pr view`）。

**無 `--pr` 引數時**（在 PR branch 上，gh 自動偵測）：

```bash
bash /Users/howie/Workspace/github/yibi-stack/plugins/pr-flow/skills/pr-retrospective/scripts/detect-pr.sh
```

**有 `--pr <n>` 引數時**（agent 把實際 PR 號附在後）：

```bash
bash /Users/howie/Workspace/github/yibi-stack/plugins/pr-flow/skills/pr-retrospective/scripts/detect-pr.sh --pr 65
```

> 其他使用者需依自己的 `skill_repo` 調整此路徑（同上）。

Agent 依 ARGUMENTS 選擇對應形式。Script 用 `$*` 合併所有位置引數，支援 shell-split 傳入。
Script stdout 輸出 `PR_NUMBER=<n>`；agent 解析並記住供後續步驟使用。

檢查是否已有 retro（重跑提示）：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium handover search \
  --query "Retro: PR #$PR_NUMBER" --limit 3 2>/dev/null || true
```

---

### Step 1 — 蒐集 PR Context

每個 call 獨立執行，agent 依輸出做推論（**不在 bash 裡寫 Python 解析**）：

```bash
gh pr view "$PR_NUMBER" --json title,body,state,mergedAt,labels,commits,additions,deletions
```

```bash
gh pr view "$PR_NUMBER" --json comments -q '.comments[] | select(.author.login | test("codex|claude")) | .body' | head -200
```

PR commit 訊息（PR-keyed，不依賴 current checkout）：

```bash
gh pr view "$PR_NUMBER" --json commits -q '.commits[].messageHeadline' 2>/dev/null | head -30
```

可選（branch 還在時；若已 merge + delete 改用 gh api）：

```bash
gh pr diff "$PR_NUMBER" --name-only 2>/dev/null | head -30
```

**GATE**：若 PR `state != MERGED`，用 `AskUserQuestion` 問「PR 還沒 merge，仍要做 retro 嗎？」（預設 No）。使用者選 No 則中止，不寫入 DB。

---

### Step 2 — Agent 推論 5 題草稿並呈現

**核心**：agent 不問使用者，而是自己從 Step 1 材料推論出草稿，一次呈現：

```markdown
## PR #<N> Retrospective Draft

> 以下是 agent 從 PR context 推論出的 5 題草稿，請逐題 confirm 或指出要修改的部分。

### Q1 Problem（從 PR title + body 的 Test plan 推論）
這次 PR 解決的問題：**<一句 problem statement>**

引用依據：
- PR title: "<quoted>"
- Test plan 第 N 項: "<quoted>"

### Q2 Value（從 PR labels + commits 推論）
我們交付的 value：**<one-liner>**
- 目標對象：end user / internal / tech debt / risk
- 引用依據：commit "<sha>: <subject>"

### Q3 Experience（從 diff stat + UI 相關檔案推論）
給 customer 的體驗變化：**<one-liner>**
- 引用依據：<files changed>，看起來是 <UX-impacting / infra-only>

### Q4 Lessons（從 codex/claude review comments + commits 推論）
這個 session 學到的 3 點：
1. **<lesson 1>** -- 來源：codex review comment "..."
2. **<lesson 2>** -- 來源：commit "<sha>" 的 fix 行為
3. **<lesson 3>** -- 來源：本次對話中提到的 pattern

### Q5 Improvement Actions（依 Q4 lessons 路由）
建議下一步動作：
- [ ] 寫入規則文件（lesson N 是可重用規則）-> 依 Step 5 Lesson Classifier 路由到對應層
- [ ] 新增 hook（lesson N 是應該被自動阻擋的 pattern）-> hookify:hookify
- [ ] 查歷史 lesson（驗證是否重複犯）-> /recall "<keyword>"
- [ ] 產生 control log（記錄本 PR 的 AI 行為審計 entries）-> /pr-control-log

請回覆：
- "OK" -- 全部採用
- "修 Q3" / "Q4 第 2 點不對" -- 指定要改的部分
- "重寫" -- 全部重來
```

**Inference 要求**：

- 每題必附「引用依據」，不能憑空編造
- 草稿語氣是 draft，留校準空間
- Q5 的勾選由 agent 依 Q4 訊號決定
- 若 `control_log_entries` table 已存在 PR 相關記錄，可作為 Q4 lessons 的補充 evidence：
  `uv run python -m tasks.mycelium control-log show --pr $PR_NUMBER 2>/dev/null || true`

---

### Step 3 — 使用者校準

| 使用者回應 | Agent 動作 |
|---|---|
| `OK` / `好` / `沒問題` | 進入 Step 4 |
| `修 Q3 為 ...` / `Q4 第 2 點改成 ...` | 局部修改後只重印該題 |
| `重寫` / `不對，應該是 ...` | 整份草稿重新 inference 後重呈現 |
| `cancel` / `算了` | GATE 中止，不寫入 DB |

iteration 上限 3 次，超過後提示「我的 inference 似乎抓不到重點，請直接給定 5 題答案」。

---

### Step 4 — 寫入 handover（含 pr-retrospective tag）

把 Step 3 確定的答案寫入 handover（變數先賦值，避免巢狀 quoting）：

```bash
Q1_PROBLEM="<final from Step 3>"
Q2_VALUE="<final>"
Q3_EXPERIENCE="<final>"
```

```bash
Q4_LESSONS_JSON=$(jq -nc '$ARGS.positional' --args -- "<lesson1>" "<lesson2>" "<lesson3>")
Q5_NEXT_JSON=$(jq -nc '$ARGS.positional' --args -- "<action1>" "<action2>")
ROUTING_TAGS_JSON=$(jq -nc '$ARGS.positional' --args -- "<routing-tag-1>")
```

```bash
TOPIC="Retro: PR #$PR_NUMBER - $Q1_PROBLEM"
SUMMARY="Problem: $Q1_PROBLEM. Value: $Q2_VALUE. Experience: $Q3_EXPERIENCE."
```

```bash
DECISIONS=$(jq -nc --arg v "Value: $Q2_VALUE" --arg e "Experience: $Q3_EXPERIENCE" '[$v,$e]')
COMPLETED=$(jq -nc --arg pr "PR #$PR_NUMBER merged" '[$pr]')
```

```bash
TAGS=$(jq -nc \
  --arg br "$BRANCH" \
  --arg pr "pr-$PR_NUMBER" \
  --argjson extra "$ROUTING_TAGS_JSON" \
  '["pr-retrospective",$br,$pr] + $extra')
```

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium handover write \
  --workdir "$REAL_WORKDIR" --project "$ORIG_PROJECT" \
  --session-type discussion \
  --topic "$TOPIC" --summary "$SUMMARY" \
  --completed "$COMPLETED" --decisions "$DECISIONS" \
  --blocked '[]' --next "$Q5_NEXT_JSON" \
  --lessons "$Q4_LESSONS_JSON" --approaches '[]' \
  --tags "$TAGS"
```

**Discriminator**（讓 handover-back 能辨識）：

- `tags` 第一個元素**強制** `"pr-retrospective"`
- `topic` 強制 `Retro:` 前綴
- `session_type` 為 `discussion`（DB enum 不可改，tag + topic 已足夠辨識）

若 Step 4 寫入失敗，輸出上面的完整 bash 重試指令（含已填好的 var 值），讓使用者手動重跑。

---

### Step 4b — 寫入 typed lessons（tier promotion 用）

> **執行條件**：只對通過 Step 5 Promotion Gate G1+G2+G3 的 lesson 執行。
> 若 Step 4 handover 寫入已失敗，此步驟跳過。

Classifier → `--type` 對照表：

| Lesson 分類 | `--type` |
|------------|---------|
| Bash anti-pattern / Quoting | `pitfall` |
| SKILL.md authoring | `pattern` |
| Irreversible operations | `pitfall` |
| Security / injection | `pitfall` |
| Python / task conventions | `pattern` |
| Repo metadata | `operational` |
| Cross-project preference | `preference` |
| Investigation-driven discovery | `investigation` |

**先呈現 derived `--type` 給 user 確認**，再執行 `lessons add`（避免分類偏差）：

確認後對每筆通過 Gate 的 lesson 執行（一次一筆）：

```bash
LESSON_KEY="{{slugified-lesson-key}}"
LESSON_TYPE="{{pitfall|pattern|preference|architecture|tool|operational|investigation}}"
LESSON_TEXT="{{lesson body}}"
HANDOVER_ID="{{id from Step 4 output}}"
```

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium lessons add \
  --key "$LESSON_KEY" \
  --type "$LESSON_TYPE" \
  --insight "$LESSON_TEXT" \
  --confidence 7 \
  --source inferred \
  --skill pr-retrospective \
  --retro-pr "$PR_NUMBER" \
  --handover-id "$HANDOVER_ID"
```

若呼叫失敗：停止並輸出完整指令讓使用者手動重跑。

> **為什麼需要 Step 4b**：Step 4 的 handover write 把 lesson 存在 `handovers.lessons_learned` JSON 欄位。
> `tasks/mycelium/tier_service.py` 的 `working→hot→cold→archival` promotion 只處理 typed `lessons` 表。
> 不執行 Step 4b 的話，retro lesson 永遠不會進入 tier promotion 生命週期。

---

### Step 5 — 路由建議 + 自動跑 read-only 動作

#### Promotion Gate（3 條，全通過才路由到 rule 檔）

每個 Q4 lesson 在進入 Lesson Classifier 前，先依序通過 3 條 gate。**任一失敗 → 只存 mycelium handover，不寫規則文件**：

| Gate | 判斷問題 | 失敗時行動 |
|------|---------|-----------|
| **G1 automation-infeasible** | 這個 lesson 能被 hook 自動阻擋嗎？（PreToolUse / PostToolUse 能機械偵測？） | 先執行 `hookify:hookify`，不寫 rule；rule 只給 hook 無法覆蓋的情境 |
| **G2 onboarding-relevant** | 一個剛加入的貢獻者（day-1）也會犯這個錯誤嗎？ | 若 No（只有深度 context 才會踩）→ mycelium handover only，不開 rule |
| **G3 no existing rule covers it** | 搜尋現有 `.claude/rules/` 後，沒有任何 rule 已覆蓋此 pattern 嗎？ | 若已有 → extend 現有 rule（append），不建新 rule 檔 |

> 此 gate 的設計邏輯：rule 檔是每 session 全量載入的 token cost（無 globs 的 rule 永遠佔用 context）。
> 只有 hook 無法解、新人也會踩、且尚無 rule 覆蓋的 lesson，才值得加進 rule。

#### Lesson Classifier

Q4 每個 lesson 先按下表分類再決定目的地。**CLAUDE.md 是最後 fallback，不是 default**：

| Lesson 類別 | 判斷訊號（關鍵字 / 情境）| 目的地 |
|-------------|--------------------------|--------|
| Bash anti-pattern（AP1/AP2/AP3）| `for loop`、`heredoc`、`$()`、`cd &&`、bash 字串 Unicode | `.claude/rules/13-bash-anti-patterns.md` |
| Shell quoting hygiene | `simple_expansion`、`Unhandled node type: string`、BRE alternation、反向巢狀 subshell | `.claude/rules/13-bash-anti-patterns.md`（已合併自 rule 14）|
| SKILL.md authoring | `scope:` 欄位、`{{placeholder}}`、frontmatter 格式、skill 執行介面設計 | `.claude/rules/11-skill-authoring.md` |
| 不可逆操作邊界 | `protect-push`、`gh pr merge`、`alembic`、`rm -rf`、force push | `.claude/rules/15-irreversible-operations.md` |
| 安全性 / 注入 | mrkdwn sanitize、`Content-Type`、SQL injection、API key 明文 | `.claude/rules/03-security.md` |
| Python / task module 慣例 | Pydantic、`@field_validator`、click CLI、SQLite、pytest、parser registry、module structure、CJK 文字規範 | `.claude/rules/` 對應子檔（rule 01-10；依主題對應；03/11/13-15 已有上方專屬行）|
| Repo metadata（無對應 rule）| 新 runtime 檔案、新 make target、`CLAUDE_EFFORT` hook 語意、本 repo 特定設定 | `<repo>/CLAUDE.md` 對應段落 |
| 跨專案個人偏好 | 個人工具選擇（`gwscli`、commit email 格式）、跨專案操作習慣 | `~/.claude/CLAUDE.md` |
| **一次性 / 無重現性** | 環境問題、偶發錯誤、與 codebase 無關的學習 | **不寫文件**（mycelium handover 已記錄即可）|

> **rules/ 存在性**：`.claude/rules/` 只存在於採用 path-scoped rules 架構的 repo。在其他 repo 執行 `/pr-retro` 時，若目標 rule 檔不存在，改路由到 `<repo>/CLAUDE.md` 作為 fallback。

#### CLAUDE.md 行數檢查（路由到任何 CLAUDE.md 時才執行）

若 Lesson Classifier 結果是 `<repo>/CLAUDE.md` 或 `~/.claude/CLAUDE.md`，先確認**目標**行數：

- 路由到 `<repo>/CLAUDE.md` → `wc -l CLAUDE.md`
- 路由到 `~/.claude/CLAUDE.md` → `wc -l ~/.claude/CLAUDE.md`

若目標 CLAUDE.md >= 180 行（精簡目標 200 行，Anthropic adherence 參考值；提前 20 行為 append buffer），在建議更新前輸出：

```text
[WARN] <target-path> 已 <N> 行，接近 200 行精簡目標。
metadata / preference 類 lesson 本就適合 CLAUDE.md；若整體已過長，
建議先執行 /claude-md-prune 精簡後再 append。本次仍可繼續，由使用者決定。
```

#### Q5 勾選 -> 行動映射

依 Q5 勾選映射：

| Q5 勾選 | 動作 |
|---|---|
| 查歷史 lesson | `Skill(skill="recall", args="<Q1 keyword>")` **自動執行** |
| 寫入規則文件 | 依 Lesson Classifier 輸出建議：「lesson N 屬於 <類別>，建議 append 到 `.claude/rules/XX.md`（最相關段落後；不確定就 append 到檔尾）。草稿：`<draft text>`。用 Edit 工具直接寫入 rule 檔。」|
| 新增 hook | 輸出建議文字：「執行 `hookify:hookify`，建議的 trigger：`<draft>`」|
| 建立 skill | 輸出建議文字：「執行 `superpowers:writing-skills`，問題定義：`<Q4 lesson>`」|
| 找 automation | 輸出建議文字：「執行 `/claude-code-setup:claude-automation-recommender`」|
| 產生 control log | 執行 `Skill(skill="pr-control-log")` 紀錄本 PR 的 AI 行為審計 entries |

寫檔動作**只建議**，由使用者決定是否執行。

---

### Step 6 — 確認寫入

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium handover read --last 1
```

---

## GATE / 中止規則

- PR `state != MERGED` → 詢問是否強制（預設 No）
- 找不到 PR 號 → FAIL
- inference iteration > 3 次仍無共識 → 切換「請使用者直接給答案」模式
- 使用者 `cancel` → 不寫入 DB
- 重跑同 PR → Step 0 提示先前已有 retro（但不阻擋）

---

## 與 handover-back 的關係

> 本 skill 寫入的 record 帶有 `pr-retrospective` tag。
> `commands/handover-back.md` 已使用 `handover read --exclude-tags pr-retrospective`，
> 因此 retro records **不會**出現在「下次接續工作」的查詢中。
>
> 若要查詢過往 retro：
>
> ```bash
> uv run --directory "$SKILL_REPO" \
>   python -m tasks.mycelium handover search \
>   --query pr-retrospective --limit 10
> ```
>
> 或透過 `/learn` 聚合視圖（retro 的 lessons 會被自動納入）：`/learn search "<keyword>"`

---

## PostToolUse Hook 延伸

PostToolUse hook 現在支援所有工具輸出替換（`hookSpecificOutput.updatedToolOutput`），
不再只限 MCP 工具。可考慮在高價值工具（如 `Write`、`Bash`）執行後自動記錄 insight，
在 retro 時提供更豐富的素材：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [{ "type": "command", "command": "python3 ~/.agents/scripts/capture-write-insight.py" }]
      }
    ]
  }
}
```

> 評估建議：只為「寫入重要產出」的工具加 hook，避免 Bash/Read 等高頻工具造成過多雜訊。
> 此 hook 主要補強 mycelium Stop hook 尚未收到的 mid-session insight。

---

## 常見問題

| 問題 | 處理方式 |
|------|----------|
| 我還沒 merge，能跑嗎？ | GATE，問是否強制（預設 No）|
| 跑兩次同 PR 會重複寫入嗎？ | 會，Step 0 提示先前已有 retro |
| handover-back 會看到我的 retro 嗎？ | 不會（已加 `--exclude-tags pr-retrospective`）|
| 如何只看 PR retro？ | `/recall pr-retrospective` 或 `/recall "pr-<n>"`|
| Agent 推論總是抓不到重點？ | iteration > 3 次後切換「請使用者直接給答案」模式 |
| 想改寫已存在的 retro | append-only；建議寫新一筆並在 tags 加 `revised`；舊 retro 留存 |

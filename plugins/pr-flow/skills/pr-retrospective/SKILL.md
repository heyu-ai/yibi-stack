---
name: pr-retrospective
type: tool
scope: global
description: >
  單一 PR / session 收尾的 agent-led 回顧：agent 從 PR context（title/body/AC/commits/diff）
  自動推論 5 題草稿（problem / value / experience / lessons / improvement），
  呈現給使用者校準後寫入 session-memory handover（tags 含 "pr-retrospective" 以便 handover-back 排除），
  並依 Lesson Classifier 路由到 .claude/rules/ 子檔（bash/quoting/skill-authoring/irreversible/security）
  或 CLAUDE.md（fallback），再觸發 hookify:hookify、/claude-md-management:revise-claude-md、
  /claude-code-setup:claude-automation-recommender、superpowers:writing-skills 等下游 skill。
  觸發關鍵字：pr 回顧、pr retro、pr retrospective、session 收尾、merge 後檢討、
  五個問題回顧、AC 驗收、DoD 完成、what problem we want to solve、
  what value we deliver、lessons learned this session
---

# PR Retrospective — agent 推論 + 使用者校準

## 適用情境

- 剛完成 `/pr-review-cycle-codex` 流程，PR 已 merge（或即將 merge）
- 想為這個 PR session 留下結構化學習記錄
- 想讓 agent 幫你從 PR context 提煉「我們解決了什麼問題、學到了什麼」

## 不適用

| 情境 | 應使用 |
|------|--------|
| 週度工程回顧 | `/retro`（weekly engineering retrospective）|
| 查詢歷史 lessons | `/learn search <keyword>` |
| 對話中途交班 | `/handover`（工作中交班，非 session 收尾）|

---

## 步驟

### Step 0 — 環境與 PR 解析（只在 skill 啟動時跑一次）

```bash
if ! command -v jq >/dev/null 2>&1; then echo '[FAIL] jq not installed' >&2; exit 1; fi
if ! command -v gh >/dev/null 2>&1; then echo '[FAIL] gh not installed' >&2; exit 1; fi
```

```bash
_gcd=$(git rev-parse --git-common-dir 2>/dev/null)
case "$_gcd" in
    /*)
      _dir=$(dirname "$_gcd")
      ORIG_PROJECT=$(basename "$_dir")
      ;;
    ?*)
      _top=$(git rev-parse --show-toplevel)
      ORIG_PROJECT=$(basename "$_top")
      ;;
    *)
      ORIG_PROJECT=$(basename "$PWD")
      ;;
esac
unset _gcd _dir _top
```

```bash
if ! SKILL_REPO=$(jq -r .skill_repo "$HOME/.agents/config.json"); then echo '[FAIL] reading ~/.agents/config.json failed' >&2; exit 1; fi
[ "$SKILL_REPO" = "null" ] && SKILL_REPO=""
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo not configured' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo '[FAIL] skill_repo path not found' >&2; exit 1; fi
REAL_WORKDIR=$(pwd)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
```

從 skill 的 `args`（即 `$ARGUMENTS`）解析 `--pr <n>`：

```bash
ARG_PR=""
_raw_args="${ARGUMENTS:-}"
if echo "$_raw_args" | grep -qE -- '--pr [0-9]+'; then
  ARG_PR=$(echo "$_raw_args" | grep -oE -- '--pr [0-9]+' | grep -oE '[0-9]+')
fi
unset _raw_args
```

偵測 PR 號（優先用參數，其次用 gh）：

```bash
PR_NUMBER="${ARG_PR:-}"
if [ -z "$PR_NUMBER" ]; then
  PR_NUMBER=$(gh pr view --json number -q .number 2>/dev/null || echo "")
fi
if [ -z "$PR_NUMBER" ]; then
  echo '[FAIL] no PR detected; pass --pr <n> if needed' >&2; exit 1
fi
```

檢查是否已有 retro（重跑提示）：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory handover search \
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
- [ ] 查歷史 lesson（驗證是否重複犯）-> /learn search "<keyword>"

請回覆：
- "OK" -- 全部採用
- "修 Q3" / "Q4 第 2 點不對" -- 指定要改的部分
- "重寫" -- 全部重來
```

**Inference 要求**：

- 每題必附「引用依據」，不能憑空編造
- 草稿語氣是 draft，留校準空間
- Q5 的勾選由 agent 依 Q4 訊號決定

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
  python -m tasks.session_memory handover write \
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

### Step 5 — 路由建議 + 自動跑 read-only 動作

#### Lesson Classifier

Q4 每個 lesson 先按下表分類再決定目的地。**CLAUDE.md 是最後 fallback，不是 default**：

| Lesson 類別 | 判斷訊號（關鍵字 / 情境）| 目的地 |
|-------------|--------------------------|--------|
| Bash anti-pattern（AP1/AP2/AP3）| `for loop`、`heredoc`、`$()`、`cd &&`、bash 字串 Unicode | `.claude/rules/13-bash-anti-patterns.md` |
| Shell quoting hygiene | `simple_expansion`、`Unhandled node type: string`、BRE alternation、反向巢狀 subshell | `.claude/rules/14-shell-quoting-hygiene.md` |
| SKILL.md authoring | `scope:` 欄位、`{{placeholder}}`、frontmatter 格式、skill 執行介面設計 | `.claude/rules/11-skill-authoring.md` |
| 不可逆操作邊界 | `protect-push`、`gh pr merge`、`alembic`、`rm -rf`、force push | `.claude/rules/15-irreversible-operations.md` |
| 安全性 / 注入 | mrkdwn sanitize、`Content-Type`、SQL injection、API key 明文 | `.claude/rules/03-security.md` |
| Python / task module 慣例 | Pydantic、`@field_validator`、click CLI、SQLite、pytest、parser registry、module structure、CJK 文字規範 | `.claude/rules/` 對應子檔（rule 01-10；依主題對應；03/11/13-15 已有上方專屬行）|
| Repo metadata（無對應 rule）| 新 runtime 檔案、新 make target、`CLAUDE_EFFORT` hook 語意、本 repo 特定設定 | `<repo>/CLAUDE.md` 對應段落 |
| 跨專案個人偏好 | 個人工具選擇（`gwscli`、commit email 格式）、跨專案操作習慣 | `~/.claude/CLAUDE.md` |
| **一次性 / 無重現性** | 環境問題、偶發錯誤、與 codebase 無關的學習 | **不寫文件**（session-memory handover 已記錄即可）|

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
| 查歷史 lesson | `Skill(skill="learn", args="search '<Q1 keyword>'")` **自動執行** |
| 寫入規則文件 | 依 Lesson Classifier 輸出建議：「lesson N 屬於 <類別>，建議 append 到 `.claude/rules/XX.md`（最相關段落後；不確定就 append 到檔尾）。草稿：`<draft text>`。用 Edit 工具直接寫入 rule 檔。」|
| 新增 hook | 輸出建議文字：「執行 `hookify:hookify`，建議的 trigger：`<draft>`」|
| 建立 skill | 輸出建議文字：「執行 `superpowers:writing-skills`，問題定義：`<Q4 lesson>`」|
| 找 automation | 輸出建議文字：「執行 `/claude-code-setup:claude-automation-recommender`」|

寫檔動作**只建議**，由使用者決定是否執行。

---

### Step 6 — 確認寫入

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.session_memory handover read --last 1
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
>   python -m tasks.session_memory handover search \
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
> 此 hook 主要補強 session-memory Stop hook 尚未收到的 mid-session insight。

---

## 常見問題

| 問題 | 處理方式 |
|------|----------|
| 我還沒 merge，能跑嗎？ | GATE，問是否強制（預設 No）|
| 跑兩次同 PR 會重複寫入嗎？ | 會，Step 0 提示先前已有 retro |
| handover-back 會看到我的 retro 嗎？ | 不會（已加 `--exclude-tags pr-retrospective`）|
| 如何只看 PR retro？ | `/learn search "pr-retrospective"` 或 `lessons search "pr-<n>"`|
| Agent 推論總是抓不到重點？ | iteration > 3 次後切換「請使用者直接給答案」模式 |
| 想改寫已存在的 retro | append-only；建議寫新一筆並在 tags 加 `revised`；舊 retro 留存 |

---
name: pr-retrospective
type: tool
scope: global
description: >
  單一 PR / session 收尾的 agent-led 回顧：agent 從 PR context（title/body/AC/commits/diff）
  自動推論 5 題草稿（problem / value / experience / lessons / improvement），
  呈現給使用者校準後寫入 mycelium 獨立的 retrospectives table（與工作中途暫存的 handover
  概念分開，不會被 handover-back 撿到），
  並依 Lesson Classifier 路由到 .claude/rules/ 子檔（bash/quoting/skill-authoring/irreversible/security）
  或 CLAUDE.md（fallback），再觸發 hookify:hookify、/claude-md-management:revise-claude-md、
  /claude-code-setup:claude-automation-recommender、superpowers:writing-skills 等下游 skill。
  觸發關鍵字：pr 回顧、pr retro、pr retrospective、session 收尾、merge 後檢討、
  五個問題回顧、AC 驗收、DoD 完成、what problem we want to solve、
  what value we deliver、lessons learned this session
---

# PR Retrospective — agent 推論 + 使用者校準

## 適用情境

- 剛完成 `/pr-review-cycle`、`/pr-cycle-fast` 或 `/pr-cycle-deep` 流程，PR 已 merge（或即將 merge）
- 想為這個 PR session 留下結構化學習記錄
- 想讓 agent 幫你從 PR context 提煉「我們解決了什麼問題、學到了什麼」

## 不適用

| 情境 | 應使用 |
|------|--------|
| 週度工程回顧 | `/retro`（weekly engineering retrospective）|
| 查詢歷史 lessons | `/lessons find <keyword>` |
| 對話中途交班 | `/handover`（工作中交班，非 session 收尾）|

---

## 步驟

### Step 0 — 環境與 PR 解析（只在 skill 啟動時跑一次）

先定位 bootstrap.sh。**不要用 `~/.agents/config.json` 的 `skill_repo` 來找它**：該 key 是多個
repo 的 `make install` 共寫的單一值，會被最後一個安裝者覆寫而指向錯 repo，而只驗 `[ -d ]`
的 gate 擋不住（錯 repo 也「存在」），結果 `bash "$SKILL_REPO/plugins/.../bootstrap.sh"` 直接
死在 No such file——bootstrap 一行都跑不到。

改用 `make install` 建立的 symlink 定位。**本 skill 需要一份真實的 yibi-stack checkout**
（要跑 `tasks/mycelium`），而 `~/.claude/skills/pr-retrospective` symlink 正好指向它；
純 plugin 安裝（`~/.claude/plugins/cache/...`）是非 git 的解壓目錄且不含 `tasks/`，無法支撐
本 skill，故不走 `CLAUDE_PLUGIN_ROOT`（實測該變數在 Bash tool 環境未設定）：

```bash
RETRO_ROOT="$HOME/.claude/skills/pr-retrospective"
if [ ! -r "$RETRO_ROOT/scripts/bootstrap.sh" ]; then echo "[FAIL] 讀不到 bootstrap.sh：$RETRO_ROOT/scripts/bootstrap.sh（請在 yibi-stack 執行 make install）" >&2; exit 1; fi
```

再執行環境檢查 + 專案偵測（prereqs check / case-free project detection / config）：

```bash
bash "$RETRO_ROOT/scripts/bootstrap.sh"
```

Script stdout 輸出 `KEY=VALUE`，agent 解析並記住。**`SKILL_REPO` 以此輸出為唯一來源**
（bootstrap 從自身位置 self-locate，與 config 無關；後續所有步驟都用這個值）：

- `SKILL_REPO` — 這份 skill 腳本所屬的 yibi-stack checkout 根目錄
- `ORIG_PROJECT` — 呼叫端 git repo 名稱
- `REAL_WORKDIR` — 目前工作目錄
- `BRANCH` — 目前分支名稱

偵測 PR 號（從 ARGUMENTS 解析 `--pr <n>` 或 fallback 到 `gh pr view`）。

`detect-pr.sh` 是 `bootstrap.sh` 的同目錄 sibling，一律用 `$RETRO_ROOT` 定址（與上方同一個
idiom，不要再從 `$SKILL_REPO` 重推 `plugins/pr-flow/...` 佈局路徑）。

**無 `--pr` 引數時**（在 PR branch 上，gh 自動偵測）：

```bash
bash "$RETRO_ROOT/scripts/detect-pr.sh"
```

**有 `--pr <n>` 引數時**（agent 把實際 PR 號附在後）：

```bash
bash "$RETRO_ROOT/scripts/detect-pr.sh" --pr 65
```

Agent 依 ARGUMENTS 選擇對應形式。Script 用 `$*` 合併所有位置引數，支援 shell-split 傳入。
Script stdout 輸出 `PR_NUMBER=<n>`；agent 解析並記住供後續步驟使用。

檢查是否已有 retro（重跑提示；`--pr-number` 是精確匹配，不依賴 topic 字串）：

```bash
uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium retro search \
  --pr-number "$PR_NUMBER" --limit 3 2>/dev/null || true
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
這個 session 學到的可重用教訓（**0–5 條，寧缺勿濫**；只收真正能重用的，沒有就誠實寫 0，不要為湊數編低訊號項）：
1. **<lesson 1>** -- 來源：codex review comment "..."
2. **<lesson 2>** -- 來源：commit "<sha>" 的 fix 行為
（依實際有幾條可重用教訓增減；下游 `/knowledge-distill` 蒸餾會聚合多 PR 的同類教訓，湊數項只會稀釋 cluster）

### Q5 Improvement Actions（依 Q4 lessons 路由）
建議下一步動作：
- [ ] 寫入規則文件（lesson N 是可重用規則）-> 依 Step 5 Lesson Classifier 路由到對應層
- [ ] 新增 hook（lesson N 是應該被自動阻擋的 pattern）-> hookify:hookify
- [ ] 查歷史 lesson（驗證是否重複犯）-> /lessons find "<keyword>"
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

### Step 4 — 寫入 retrospective

> **執行注意（單一 script，不要拆成多個 bash call）**：Claude Code 的 Bash tool 每次呼叫是
> 獨立 subprocess，**shell 變數不會跨 call 持續**（只有 cwd 會）——即使是 `export` 過的變數，
> 下一個 bash call 讀到的也是空值。若把下面的變數賦值拆成多個 bash call（如同早期版本
> 誤以為的寫法），`retro write` 呼叫時所有 `$Q1_PROBLEM`/`$TOPIC`/`$TAGS` 等變數都會是空字串，
> 寫入的 retro 記錄會整批是空欄位，且不會報錯。**用 Write tool 把整段邏輯寫成一個
> `$CLAUDE_JOB_DIR/tmp/retro_write.sh`，用單一 `bash "$CLAUDE_JOB_DIR/tmp/retro_write.sh"`
> 執行**（PR #205 retro 自己跑 `/pr-retro` 時實測發現此問題，見該次 retro 記錄）。

把 Step 3 確定的答案、Step 0/1 蒐集到的 `SKILL_REPO`/`REAL_WORKDIR`/`ORIG_PROJECT`/`BRANCH`/
`PR_NUMBER`，全部寫進同一個 script（範例邏輯，實際內容用 Write tool 產生）：

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILL_REPO="<from Step 0>"
REAL_WORKDIR="<from Step 0>"
ORIG_PROJECT="<from Step 0>"
BRANCH="<from Step 0>"
PR_NUMBER="<from Step 0>"

Q1_PROBLEM="<final from Step 3>"
Q2_VALUE="<final>"
Q3_EXPERIENCE="<final>"

Q4_LESSONS_JSON=$(jq -nc '$ARGS.positional' --args -- "<lesson1>" "<lesson2>" "<lesson3>")
Q5_NEXT_JSON=$(jq -nc '$ARGS.positional' --args -- "<action1>" "<action2>")
ROUTING_TAGS_JSON=$(jq -nc '$ARGS.positional' --args -- "<routing-tag-1>")

TOPIC="Retro: PR #$PR_NUMBER - $Q1_PROBLEM"
SUMMARY="Problem: $Q1_PROBLEM. Value: $Q2_VALUE. Experience: $Q3_EXPERIENCE."

DECISIONS=$(jq -nc --arg v "Value: $Q2_VALUE" --arg e "Experience: $Q3_EXPERIENCE" '[$v,$e]')
COMPLETED=$(jq -nc --arg pr "PR #$PR_NUMBER merged" '[$pr]')

TAGS=$(jq -nc \
  --arg br "$BRANCH" \
  --arg pr "pr-$PR_NUMBER" \
  --argjson extra "$ROUTING_TAGS_JSON" \
  '[$br,$pr] + $extra')

# 先顯示這次工作的 token 用量與成本估算給使用者看（best-effort，範圍是整個 session）
uv run --directory "$SKILL_REPO" python -m tasks.mycelium token-usage report \
  --workdir "$REAL_WORKDIR" --project "$ORIG_PROJECT" || true

uv run --directory "$SKILL_REPO" \
  python -m tasks.mycelium retro write \
  --workdir "$REAL_WORKDIR" --project "$ORIG_PROJECT" \
  --pr-number "$PR_NUMBER" \
  --topic "$TOPIC" --summary "$SUMMARY" \
  --completed "$COMPLETED" --decisions "$DECISIONS" \
  --next "$Q5_NEXT_JSON" \
  --lessons "$Q4_LESSONS_JSON" \
  --tags "$TAGS" \
  --auto-tokens
```

> **Exit code 分支**（`token-usage report` 那行）：`0` = 正常顯示（`computed`/`computed_partial`，
> partial 時輸出會自帶 `[WARN]` 標示哪些 model 沒定價）；`2` = 無法取得 token 用量（transcript
> 找不到、定位失敗或計算失敗，詳見 `[WARN]` 訊息）；`3` = 偵測到可能有
> 並行 session，無法判斷是哪一個。**`2`/`3` 都只是 `[WARN]`，不阻擋接下來的 retro
> write 步驟**——把這段輸出原樣呈現給使用者看（token 數、估算成本、model 拆分、
> 優化建議），再繼續往下走（script 裡的 `|| true` 已確保不會因此中止）。數字是整個 session
> 的估算值，若同一 session 裡混雜了其他不相關的工作，數字會偏高。

若 Step 4 寫入失敗，輸出完整的 script 內容讓使用者手動重跑（`bash <path>`）。

---

### Step 4b — 寫入 typed lessons（tier promotion 用）

> **執行條件**：只對通過 Step 5 Promotion Gate G1+G2+G3 的 lesson 執行。
> 若 Step 4 retro 寫入已失敗，此步驟跳過。

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

> **下游蒸餾品質要求**（`/knowledge-distill` 依賴這些訊號聚合多 PR 教訓，不可壓平）：
>
> - **`--confidence` 必須差異化，不可一律寫 7**。依來源與校準給分：
>   `user-stated` 且使用者校準過 → 8–9；`cross-model`（codex/claude 兩家都提同一點）→ 8；
>   純 `inferred`（agent 單方推論）→ 5–6。**若 Step 5 Q5 查歷史發現此教訓重複犯（recurrence）→ 在原分數上 +1**（封頂 10），重複犯是「值得變 skill」的最強訊號。
> - **`--source` 必須與上面的 confidence 依據一致，不可一律 `inferred`**：使用者校準過填 `user-stated`、
>   兩家模型都提填 `cross-model`、agent 單方推論才填 `inferred`。source 不只是標籤——
>   `inferred`/`observed` 會隨時間 decay，`user-stated`/`cross-model` 不衰減；填錯會讓高信心教訓被錯誤衰減。
> - **`--skill` 填「教訓的主題 skill」而非 `pr-retrospective`**（產生者）。例：教訓是關於 `gmail-billing` 的 parser → 填 `gmail-billing`；關於 bash/quoting 等泛用主題 → **留空**（`--skill` 省略），讓蒸餾以 type + 語意聚類。
> - **`--key` slug 加領域前綴**（`bash-`、`pydantic-`、`gmail-billing-`、`cli-` …），讓同類教訓跨 PR 的 key 前綴一致，提升 dedup 與 cluster 收斂。

確認後對每筆通過 Gate 的 lesson 執行。**同 Step 4 的執行注意**：shell 變數不跨 bash call
持續，所有通過 Gate 的 lesson 都寫進**同一個** `$CLAUDE_JOB_DIR/tmp/retro_lessons.sh`（用一個
shell function 包住重複邏輯，每筆 lesson 呼叫一次該 function），用單一 bash call 執行：

> **`--project "$ORIG_PROJECT"` 不可省略**（issue #243）。`lessons add` 的 `--project` 預設是
> 「從 git common-dir 推斷」，但 `uv run --directory "$SKILL_REPO"` 已經把子行程 cwd 換成
> **skill repo**——省略時每一條 retro lesson 都會被記到 `yibi-stack` 名下，不論這個 retro 實際
> 是哪個 repo 的 PR。此坑靜默：retro 照樣顯示成功、`handover read` 也查得到（Step 4 有顯式傳
> `--project`，scope 是對的），只有 lessons 悄悄跑到別的 project，於是各 repo 用 `/lessons`
> 查不到自己的教訓。實際影響：修復前已有 287 條 lesson 誤記（2026-05-28 起約 7 週）。

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILL_REPO="<from Step 0>"
PR_NUMBER="<from Step 0>"
ORIG_PROJECT="<from Step 0>"
RETRO_ID="<id from Step 4 output>"

add_lesson() {
  local key="$1" type="$2" insight="$3" confidence="$4" source="$5" skill_flag_val="$6"
  local skill_flag=()
  if [ -n "$skill_flag_val" ]; then
    skill_flag=(--skill "$skill_flag_val")
  fi
  uv run --directory "$SKILL_REPO" \
    python -m tasks.mycelium lessons add \
    --key "$key" \
    --type "$type" \
    --insight "$insight" \
    --confidence "$confidence" \
    --source "$source" \
    --project "$ORIG_PROJECT" \
    ${skill_flag[@]+"${skill_flag[@]}"} \
    --retro-pr "$PR_NUMBER" \
    --retrospective-id "$RETRO_ID"
}

# 每筆通過 Gate 的 lesson 呼叫一次；--skill 留空字串代表省略（避免把產生者誤記成主題）
add_lesson \
  "{{domain-prefixed-slug}}" \
  "{{pitfall|pattern|preference|architecture|tool|operational|investigation}}" \
  "{{lesson body}}" \
  "{{5-10 依來源差異化；recurrence +1，封頂 10}}" \
  "{{user-stated|cross-model|inferred；與 confidence 依據一致}}" \
  "{{主題 skill 名；泛用教訓留空字串}}"
```

> **`${skill_flag[@]+"${skill_flag[@]}"}` 而非 `"${skill_flag[@]}"`**：`set -u` 底下對空陣列
> 直接展開 `"${skill_flag[@]}"` 在 macOS 系統 bash 3.2 會炸 `unbound variable`（homebrew
> bash 5.x 沒事）；`${arr[@]+...}` 是可攜寫法，陣列為空時整段安全消失。

若呼叫失敗：停止並輸出完整 script 內容讓使用者手動重跑（`bash <path>`）。

> **為什麼需要 Step 4b**：Step 4 的 retro write 把 lesson 存在 `retrospectives.lessons_learned` JSON 欄位。
> `tasks/mycelium/tier_service.py` 的 `working→hot→cold→archival` promotion 只處理 typed `lessons` 表。
> 不執行 Step 4b 的話，retro lesson 永遠不會進入 tier promotion 生命週期。

---

### Step 5 — 路由建議 + 自動跑 read-only 動作

#### Promotion Gate（3 條，全通過才路由到 rule 檔）

每個 Q4 lesson 在進入 Lesson Classifier 前，先依序通過 3 條 gate。**任一失敗 → 只存在 retro 記錄裡，不寫規則文件**：

| Gate | 判斷問題 | 失敗時行動 |
|------|---------|-----------|
| **G1 automation-infeasible** | 這個 lesson 能被 hook 自動阻擋嗎？（PreToolUse / PostToolUse 能機械偵測？） | 先執行 `hookify:hookify`，不寫 rule；rule 只給 hook 無法覆蓋的情境 |
| **G2 onboarding-relevant** | 一個剛加入的貢獻者（day-1）也會犯這個錯誤嗎？ | 若 No（只有深度 context 才會踩）→ 只存在 retro 記錄裡，不開 rule |
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
| **一次性 / 無重現性** | 環境問題、偶發錯誤、與 codebase 無關的學習 | **不寫文件**（retro 記錄已存下即可）|

> **rules/ 存在性**：`.claude/rules/` 只存在於採用 path-scoped rules 架構的 repo。在其他 repo 執行 `/pr-retro` 時，若目標 rule 檔不存在，改路由到 `<repo>/CLAUDE.md` 作為 fallback。

#### 最小相容修改階梯（Patch-Surface Ladder）

前兩層已決定 lesson 的**去留**與**目的地**：Promotion Gate（3 條）決定「能不能寫進 rule 檔」，
Lesson Classifier 決定「寫到哪個檔」。本階梯是第三軸——決定**改動面多大**。原則是**優先選最輕、
相容性最高的修改面，只有上層擋不住才往下爬**：改 frontmatter 一行 < 加流程 gate < append rule <
寫 script < 建 eval < 動 skill 邊界。每往下一階，token cost 與維護負擔就升一級。

先確認 Promotion Gate 通過、Classifier 已選定目的地，再對照下表挑最上層可行的修改面：

| 修改面 | 何時選（訊號）| 成本 / 相容性 |
|--------|--------------|----------------|
| `no-change` | 一次性 / 環境問題，Promotion Gate 已擋下 | 零 |
| `description` | 觸發不準（over/under-trigger）；見 rule 11「Trigger Coverage」 | 極低；只改 frontmatter 觸發詞 |
| `workflow gate` | 流程缺一步驗證（`[FAIL]` gate / 前置檢查 / 失敗停止條件）| 低；SKILL.md 加 gate 行 |
| `reference rule` | 跨 session 通則、day-1 新人也會踩 | 中；append `.claude/rules/` 對應子檔 |
| `script helper` | 可機械化的重複檢查（lint / 掃描）| 中高；寫 `scripts/*.py` 或 `scripts/*.sh` |
| `eval` | 有評分資料、需回歸保護 | 高；建 eval / regression gate（issue #186，尚未落地）|
| `merge / split` | skill 職責過寬或過窄，邊界本身錯了 | 高；動 skill 邊界 + 更新 `skills/README.md` |
| `deprecate / retire` | skill 已被取代，或長期 over-trigger 無法靠上層修好 | 最高；移除 symlink + 更新 index |

> **與 Lesson Classifier 的關係**：Classifier 選「哪個 rule 檔」，本階梯選「用多重的手段」。
> 例：一個觸發不準的 lesson，Classifier 指向 `11-skill-authoring.md`，但本階梯會先問——這其實
> 只需改該 skill 的 `description`（`description` 階）就好，不必真的 append 一條新 rule。

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
| 查歷史 lesson | `Skill(skill="lessons", args="find <Q1 keyword>")` **自動執行** |
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
  python -m tasks.mycelium retro read --last 1
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

> 本 skill 的 record 寫在獨立的 `retrospectives` table，與 `handovers`（`handover-back`
> 查詢的對象）完全分開——**不需要**任何 tag/topic discriminator 或
> `--exclude-tags` 排除機制，新資料在資料模型層級就不會被 `handover-back` 撿到。
>
> `commands/scripts/handover-read.sh` 仍保留 `--exclude-tags pr-retrospective`
> 這行，是為了相容**尚未遷移**的舊資料（在這次改版之前寫進 `handovers` 的舊 retro
> 記錄）；若要把舊資料搬進 `retrospectives`，執行一次性遷移工具（冪等，可重複執行）：
>
> ```bash
> uv run --directory "$SKILL_REPO" \
>   python -m tasks.mycelium retro migrate-from-handovers
> ```
>
> 若要查詢過往 retro：
>
> ```bash
> uv run --directory "$SKILL_REPO" \
>   python -m tasks.mycelium retro search \
>   --pr-number <n>
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
| handover-back 會看到我的 retro 嗎？ | 不會，retro 寫在獨立的 `retrospectives` table，`handover-back` 只查 `handovers`，資料模型層級就分開，新資料不需要 exclude-tags |
| 如何只看 PR retro？ | `uv run --directory "$SKILL_REPO" python -m tasks.mycelium retro search --pr-number <n>` 或 `retro read --last N` |
| Agent 推論總是抓不到重點？ | iteration > 3 次後切換「請使用者直接給答案」模式 |
| 想改寫已存在的 retro | append-only；建議寫新一筆並在 tags 加 `revised`；舊 retro 留存（`retrospectives` 沒有 `pr_number` 唯一限制，允許同 PR 多筆） |
| token/cost 數字看起來偏高或偏低 | 計算範圍是整個 session（從開始到呼叫 `/pr-retro` 為止），若同一 session 混雜了其他不相關的工作，數字會失真；這是已知限制 |
| token-usage report 印出 `[WARN]` 找不到 transcript 或偵測到並行 session | best-effort 啟發式無法保證找到，屬正常情況；不影響 retro 寫入，繼續往下走即可 |
| 這次改版之前寫的舊 retro 去哪了？ | 還在 `handovers` table（帶 `pr-retrospective` tag），執行一次性遷移工具 `retro migrate-from-handovers`（冪等，可重複執行）把它們搬進 `retrospectives` |

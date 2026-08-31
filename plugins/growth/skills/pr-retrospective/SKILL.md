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
的 gate 擋不住（錯 repo 也「存在」），用該值拼出的 bootstrap 路徑會直接死在
No such file——bootstrap 一行都跑不到。

依序從目前生效的 plugin cache、`make install` symlink、source checkout 定位，且每個候選都直接
檢查 bootstrap.sh 可讀。tasks-backed 操作一律呼叫 PATH 中 installed `mycelium`，不從 checkout
import `tasks/mycelium`：

```bash
PR_FLOW_CACHED=$(python3 -c "import json,pathlib; d=json.loads((pathlib.Path.home()/'.claude'/'plugins'/'installed_plugins.json').read_text(encoding='utf-8')); print(next((e.get('installPath','') for e in d.get('plugins',{}).get('growth@yibi-stack',[]) if e.get('installPath')), ''))" 2>/dev/null)
RETRO_ROOT=""
if [ -r "${PR_FLOW_CACHED:-/nonexistent}/skills/pr-retrospective/scripts/bootstrap.sh" ]; then RETRO_ROOT="$PR_FLOW_CACHED/skills/pr-retrospective"; elif [ -r "$HOME/.claude/skills/pr-retrospective/scripts/bootstrap.sh" ]; then RETRO_ROOT="$HOME/.claude/skills/pr-retrospective"; elif [ -r "plugins/growth/skills/pr-retrospective/scripts/bootstrap.sh" ]; then RETRO_ROOT="plugins/growth/skills/pr-retrospective"; fi
if ! test -n "$RETRO_ROOT"; then echo "[FAIL] 讀不到 pr-retrospective bootstrap.sh；請執行 claude plugin install growth@yibi-stack，或在 yibi-stack checkout 執行 make install" >&2; exit 1; fi
if ! command -v mycelium >/dev/null 2>&1; then echo '[FAIL] 缺少 mycelium，請執行：uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"' >&2; exit 1; fi
```

再執行環境檢查 + 專案偵測（prereqs check / case-free project detection / config）：

```bash
bash "$RETRO_ROOT/scripts/bootstrap.sh"
```

Script stdout 輸出 `KEY=VALUE`，agent 解析並記住：

- `ORIG_PROJECT` — 呼叫端 git repo 名稱
- `REAL_WORKDIR` — 目前工作目錄
- `BRANCH` — 目前分支名稱

偵測 PR 號（從 ARGUMENTS 解析 `--pr <n>` 或 fallback 到 `gh pr view`）。

`detect-pr.sh` 是 `bootstrap.sh` 的同目錄 sibling，一律用 `$RETRO_ROOT` 定址。

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
mycelium retro search --pr-number "$PR_NUMBER" --project "$ORIG_PROJECT" --limit 3 2>/dev/null || true
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
  `mycelium control-log show --pr "$PR_NUMBER" --project "$ORIG_PROJECT" 2>/dev/null || true`

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

把 Step 3 確定的答案、Step 0/1 蒐集到的 `REAL_WORKDIR`/`ORIG_PROJECT`/`BRANCH`/
`PR_NUMBER`，全部寫進同一個 script（範例邏輯，實際內容用 Write tool 產生）：

```bash
#!/usr/bin/env bash
set -euo pipefail

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
mycelium token-usage report --workdir "$REAL_WORKDIR" --project "$ORIG_PROJECT" || true

mycelium retro write \
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

### Step 4b — 準備 typed-lessons 寫入（Step 5 分級後才執行）

> **此處只準備 metadata 與 script，不得執行。** 實際 mutation 必須等 Step 5.0 Evidence Gate
> 分級：Tier 3 走 `--park`；Tier 1/2 還須通過 Promotion Gate G1+G2+G3 才正常寫入。
> 若 Step 4 retro 寫入已失敗，此步驟與後續 mutation 都跳過。

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

**先呈現 derived `--type` 給 user 確認**，再把 `lessons add` 呼叫**寫進** script（避免分類偏差）。
此處仍然不執行——執行點是 Step 5.0 分級之後（見本步驟開頭的紅字）：

> **下游蒸餾品質要求**（`/knowledge-distill` 依賴這些訊號聚合多 PR 教訓，不可壓平）：
>
> - **`--confidence` 必須差異化，不可一律寫 7**。依來源與校準給分：
>   `user-stated` 且使用者校準過 → 8–9；`cross-model`（codex/claude 兩家都提同一點）→ 8；
>   純 `inferred`（agent 單方推論）→ 5–6。**此教訓重複犯（recurrence）→ 在原分數上 +1**（封頂 10），
>   重複犯是「值得變 skill」的最強訊號——但 recurrence 必須在**這一步**先查出來，見下方
>   「recurrence 前置查詢」。
> - **`--source` 必須與上面的 confidence 依據一致，不可一律 `inferred`**：使用者校準過填 `user-stated`、
>   兩家模型都提填 `cross-model`、agent 單方推論才填 `inferred`。source 不只是標籤——
>   `inferred`/`observed` 會隨時間 decay，`user-stated`/`cross-model` 不衰減；填錯會讓高信心教訓被錯誤衰減。
> - **`--skill` 填「教訓的主題 skill」而非 `pr-retrospective`**（產生者）。例：教訓是關於 `gmail-billing` 的 parser → 填 `gmail-billing`；關於 bash/quoting 等泛用主題 → **留空**（`--skill` 省略），讓蒸餾以 type + 語意聚類。
> - **`--key` slug 加領域前綴**（`bash-`、`pydantic-`、`gmail-billing-`、`cli-` …），讓同類教訓跨 PR 的 key 前綴一致，提升 dedup 與 cluster 收斂。
>
> **recurrence 前置查詢（必跑，在決定 `--confidence` 之前）**
>
> 這個查詢排在這裡不是順手，是**唯一**套得上 +1 的時機：`lessons add` 是無條件 INSERT，而
> **沒有任何指令能原地改一筆 active lesson 的 confidence**——`lessons finalize` 是 compare-and-set，
> 只吃「已解除 park 且帶 `recurrence-<n>` tag」的那一列（見下方 reassess 收尾段），直接以 active
> 寫入的列不在其適用範圍；剩下的手段只有 `retire` + 重新 `add`，代價是換掉 id 並留一筆 tombstone，
> 只為了改一個分數。Step 5 Q5 的「查歷史 lesson」排在寫入**之後**，照 runbook 順序執行時，寫入的
> 那一刻還不知道有沒有 recurrence（issue #373，實例：PR #1169 的 `ci-local-timing-not-transferable`
> 依規則該給 9，卻已用 8 寫入且補不回來）。
>
> 對每個候選 lesson 各跑一次。這是唯讀查詢，**不需要使用者在 Q5 勾選**：
>
> ```bash
> mycelium lessons search "<候選 key 的領域關鍵字>" --project "$ORIG_PROJECT"
> ```
>
> 命中同族既有教訓 → 該筆 `--confidence` +1（封頂 10），並在把候選 metadata 呈現給使用者確認時
> **列出命中的是哪幾筆**（key + 日期），讓使用者能否決這個 +1。零命中也要說，那本身是有用的訊號。
>
> 這**不取代** Step 5 Q5：Q5 查的是 Q1 問題敘述的歷史，範圍較廣且由使用者決定要不要查；此處查的
> 是**單筆 lesson 的同族前例**，只為定分數。兩者目的不同，都保留。

確認後先把候選 metadata 寫進**同一個** `$CLAUDE_JOB_DIR/tmp/retro_lessons.sh`，但此時**不可執行**。
Step 5 決定每筆的 `active|park` outcome 後，再用一個 shell function 包住重複邏輯並以單一 bash
call 執行，避免 shell 變數跨 bash call 遺失：

> **`--project "$ORIG_PROJECT"` 不可省略**（issue #243）。`lessons add` 的 `--project` 預設是
> 從 git common-dir 推斷，但 installed CLI 的 process cwd 不應作為 target contract。省略時每一條
> retro lesson 都可能被記到錯誤 project。此坑靜默：retro 照樣顯示成功、`handover read` 也查得到（Step 4 有顯式傳
> `--project`，scope 是對的），只有 lessons 悄悄跑到別的 project，於是各 repo 用 `/lessons`
> 查不到自己的教訓。實際影響：修復前已有 287 條 lesson 誤記（2026-05-28 起約 7 週）。

```bash
#!/usr/bin/env bash
set -euo pipefail

PR_NUMBER="<from Step 0>"
ORIG_PROJECT="<from Step 0>"
RETRO_ID="<id from Step 4 output>"

add_lesson() {
  # 位置參數一律用 ${N} braced form，不可寫裸 $N（issue #386）：skill body 的 argument
  # substitution 會在 agent 讀到之前把裸 $N 換成呼叫端的 argument token——磁碟上的檔案
  # 完全正確，所以 grep 原始檔看不出問題。
  local key="${1}" type="${2}" insight="${3}" confidence="${4}" source="${5}" skill_flag_val="${6}" state="${7}"
  local skill_flag=()
  local state_flag=()
  if [ -n "$skill_flag_val" ]; then
    skill_flag=(--skill "$skill_flag_val")
  fi
  # --park 與 --skip-if-exists 互斥（tasks/mycelium/cli.py 直接 raise），故依 state 二擇一：
  # active 走冪等的 --skip-if-exists；park 的重跑語意由下方「park 出口不可重試」那段負責。
  if [ "$state" = "park" ]; then
    state_flag=(--park)
  else
    state_flag=(--skip-if-exists)
  fi
  mycelium lessons add \
    --key "$key" \
    --type "$type" \
    --insight "$insight" \
    --confidence "$confidence" \
    --source "$source" \
    --project "$ORIG_PROJECT" \
    ${skill_flag[@]+"${skill_flag[@]}"} \
    ${state_flag[@]+"${state_flag[@]}"} \
    --retro-pr "$PR_NUMBER" \
    --retrospective-id "$RETRO_ID"
}

# Step 5 完成後才加入呼叫；--skill 留空字串代表省略（避免把產生者誤記成主題）
# 每個字面值一律用單引號，見下方「範本一律單引號」——雙引號會讓 insight 裡的 $ 觸發參數展開。
add_lesson \
  '{{domain-prefixed-slug}}' \
  '{{pitfall|pattern|preference|architecture|tool|operational|investigation}}' \
  '{{lesson body}}' \
  '{{active: 5-10 依來源差異化；park: 1-4}}' \
  '{{user-stated|cross-model|inferred；與 confidence 依據一致}}' \
  '{{主題 skill 名；泛用教訓留空字串}}' \
  '{{active|park；Tier 3 必須 park 且 confidence ≤ 4}}'
```

> **`${skill_flag[@]+"${skill_flag[@]}"}` 而非 `"${skill_flag[@]}"`**：`set -u` 底下對空陣列
> 直接展開 `"${skill_flag[@]}"` 在 macOS 系統 bash 3.2 會炸 `unbound variable`（homebrew
> bash 5.x 沒事）；`${arr[@]+...}` 是可攜寫法，陣列為空時整段安全消失。
>
> **範本一律單引號**：呼叫端的字面值若用雙引號包，insight 內文出現 `$` 時 bash 會嘗試參數展開，
> 在 `set -euo pipefail` 下直接中止整個 script（實測回報 `retro_lessons.sh: line 63: ?: unbound
> variable`，環境 `GNU bash 3.2.57(1)-release (arm64-apple-darwin25)`，即 macOS 內建 `/bin/bash`）。
> 引用 regex、YAML 片段、shell 字串的 insight 在 harness / CI 主題的 retro 裡是常態，不是邊緣案例。
> 單引號完全不展開，是這裡的正解。**唯一例外**是內文本身含單引號——此時不要硬拗跳脫，改把內文寫進
> 一個檔案再 `--insight "$(cat <path>)"`，或改寫措辭避開。函式**內部**的 `"$insight"` / `"$key"`
> 維持雙引號不變，那些是真的變數展開。
>
> **`active` 路徑帶 `--skip-if-exists`，所以整個 script 可安全重跑**：`lessons add` 本身是無條件
> INSERT，一個寫到一半才死的 script 若照 Step 4 的通用指示重跑，會把前面已成功的那幾筆再寫一次
> （issue #373 實例：5 筆中第 4 筆炸掉，重跑會多出 3 筆重複 lesson）。加上 `--skip-if-exists` 後
> 同 project/type/key 已存在即略過並 exit 0，重跑變成冪等。
>
> **但 `park` 路徑不適用——這兩個旗標互斥**：`mycelium lessons add` 對 `--park` + `--skip-if-exists`
> 直接以 `--park 與 --skip-if-exists 不可同時使用` 失敗（強制點在 `tasks/mycelium/cli.py`），所以範本
> 依 `state` 二擇一，**不是無條件都加**——無條件加會讓每一條 park 路徑乾淨失敗。park 的重跑危險性由下方「`--park` 這兩條出口不可重試」那段負責——那條
> 警告仍然完全有效，**不因本節而放寬**。重跑前先 `mycelium lessons search "<key>" --project
> "$ORIG_PROJECT"` 確認哪幾筆已寫入，再決定是重跑整個 script 還是只補跑失敗的那幾筆。

此步驟到此為止**只寫檔、不執行**——因此這裡沒有「呼叫失敗」的處理，失敗處理屬於實際執行點
（Step 5.0 與 Promotion Gate 之後），各自有自己的停止規則。

> **為什麼需要 Step 4b**：Step 4 的 retro write 把 lesson 存在 `retrospectives.lessons_learned` JSON 欄位。
> `tasks/mycelium/tier_service.py` 的 `working→hot→cold→archival` promotion 只處理 typed `lessons` 表。
> 不執行 Step 4b 的話，retro lesson 永遠不會進入 tier promotion 生命週期。

---

### Step 5 — 路由建議 + 自動跑 read-only 動作

#### Step 5.0 Evidence Gate（分級 + 驗證；在 Promotion Gate 之上游）

**在既有三道 gate（Promotion Gate / Lesson Classifier / Patch-Surface Ladder）之前**，先對每個
「新增 rule / 新增 hook」action item 分級並取得證據。**未完成分級的 action item 不進 Promotion
Gate**。分級依「此宣稱有無可接受的證據形式」，**不以 `--source` 分數升級**（來源信任度不等於實測）。

三層分級：**Tier 1 Probed**（可機械實測的可證偽宣稱）、**Tier 2 Incident-cited**（有真實事件佐證但
不易廉價重跑）、**Tier 3 Subjective**（主觀 / 單一次 / 無可接受證據形式）。

**證據形式表（封閉列舉；未列出的類型無可接受形式，恆歸 Tier 3；表中不得有 catch-all 列）**：

| lesson 類型 | 可接受證據形式 | Tier |
|-------------|----------------|------|
| bash 反模式 / hook 攔截 pattern | 正 / 負樣本 `echo … \| script` 顯示攔 / 放行如預期 | 1 |
| `paths:` / frontmatter / CLI flag 行為宣稱 | `claude -p` 拋棄式 repo 探針，或 failing→passing test 的輸出 | 1 |
| 工具輸出欄位 / 版本相依行為 | 目標平台實跑一次的輸出（CLI 宣稱須附工具版本） | 1 |
| 真實事件教訓（不易廉價重跑） | PR / issue 連結 + 貼原文 quote（雙端 verify，見 rule 11 Cross-doc Cite） | 2 |
| 精確度 / 可能誤導 / 建議補充 / 品味 | **無可接受形式** | **3（恆 park）** |

**Tier 1 probe 的三種執行結果**（三者處置相異；「證據無效」不等於「宣稱不成立」）：

| 執行結果 | 意義 | 處置 |
|----------|------|------|
| 跑了、宣稱重現 | 判斷正確 | 可寫入（往下進 Promotion Gate） |
| 跑了、宣稱不成立 | 判斷錯誤 | 不寫入，記錄「未重現」（不是 park） |
| **根本跑不起來（證據無效）** | 宣稱狀態未知 | **先修一次**；修不好則**降 Tier 3 park**，**不 drop**、**不記為未重現** |

**驗證成本分層**（多數淘汰發生在零成本的結構檢查，避免昂貴 probe 卡住互動 session）：

- **結構檢查（零指令）**：action item 是否已分級、Tier 1 / 2 是否附證據欄位——不跑任何指令即判定。
- **秒級 probe 當場跑**：正 / 負樣本、`failing→passing test` 等。
- **昂貴 probe（`claude -p` 拋棄式 repo 探針）**：**派 subagent 執行，或降級 Tier 2** 要求貼出 PR 階段
  已產生的證據；**互動式 retro 不得被單一昂貴 probe 同步阻塞**。機制宣稱先跑再寫、`verified` 標記須
  附工具版本並在 CLI 升級後重跑等 probe 紀律，見 `.claude/rules/11-skill-authoring.md`
  「Blanket Claims and Reader-Run Commands Must Be Empirically Probed」與
  「A `verified` Annotation Is a Claim About a Version」兩段。

**Tier 3 park 與 recurrence 升級**（不新增檔案面；park 複用既有 typed-lessons）：

- Tier 3 **不得寫入** `.claude/rules/*` / `CLAUDE.md` 或註冊 hook；**park 到 typed-lessons**，以
  `confidence ≤ 4` + `tags` 含 `"parked"` 記錄（Step 4b prepared script 以 `--park` 執行），
  原標題 / 描述逐字保留；parked lesson 預設不進 normal recall / tier promotion。
- **recurrence**：同類 friction（同 `key`）於後續 retro 再現時，於既有 parked lesson 的 `tags` bump
  `"recurrence-<n>"`。**recurrence ≥ 2 才「解除 park」重新進入 Evidence Gate**——但**仍須通過 Tier 1
  或 Tier 2 證據才得寫入**。recurrence 證明「問題真且會重現」，不證明「此修法有效」，故不單獨構成寫入理由。

**Tier 3 可執行流程**：

1. 把 Step 4b prepared call 設為 `state=park`、`confidence ≤ 4` 後執行。
2. `mycelium lessons add --park` 必須回傳 `status=parked recurrence=<n>` 或
   `status=reassess recurrence=<n>`；任何其他輸出或 non-zero 都停止並呈現完整 script。
3. `status=parked` → 此項流程終止，不進 Promotion Gate。
4. `status=reassess recurrence≥2` → 立刻把**同一項**重新送入 Evidence Gate，不得直接寫 rule/hook。
   **記下這次輸出的 `id=<uuid>`**，重評結論兩條路各自要用到它：
   - 重評仍為 Tier 3 → 再執行同一個 `--park` call；此時只重套 parked、不再次 bump recurrence。
   - 重評通過 Tier 1/2 → 見下方「reassess 通過後的收尾」，**不可**只跑一般 `lessons add` 就結束。

> **reassess 通過 Tier 1/2 後必須收尾舊列，否則同 key 留下兩筆**（PR #347 mob review，
> lead 實證重現）。`lessons add` 是無條件 INSERT 新 UUID，沒有 key-based upsert；而 reassess
> 已經把舊列的 `parked` tag 拿掉了。若只跑一般 add，舊列會變成一筆**未 parked、未 retired、
> confidence ≤ 4** 的孤兒：它被 `_dedup_latest_winner` 藏出 `show` / `search`（所以看起來沒事），
> 卻通過 tier promotion 的三個過濾條件（實測 `_fetch_non_archival` 回 2 列），最終 age 成
> archival 並匯出到 `~/.agents/archive/`，成為一筆重複的低信心 lesson。
>
> **收尾用 `lessons finalize`，原地升級同一列**——不要跑一般 `lessons add`：
>
> ```bash
> mycelium lessons finalize --id "$OLD_PARKED_ID" --confidence <5-10> --source <與依據一致>
> ```
>
> 非零 exit → 停止並輸出完整 script 讓使用者手動重跑。**這個指令冪等**：同樣引數重跑只是把
> 同一列設成同樣的值，不會新增列。這一點是刻意的——runbook 對失敗的指示就是「重跑整個
> script」，而先前設計的「先 add 後 retire」在重跑時會再 INSERT 一列，讓狀況比修之前更糟
> （Codex 於 R2 與 re-review 兩輪指出，第二輪明確以「不可重試」為由升為 Critical，已照做）。
> `finalize` 內部是單一 transaction 的 compare-and-set：id 不存在、已 retire、仍為 parked、
> 或沒有 `recurrence-<n>` tag（代表它不是等待重評的那一列）都直接失敗，不做部分更新。
>
> **重評通過 Tier 1/2、但 Promotion Gate（G1/G2/G3）沒過**：這條分支同樣需要終止轉移，
> 否則舊列會停在「已解除 park、confidence ≤ 4」的孤兒狀態，重新進入一般 recall 與 tier
> promotion——與上面那個 bug 完全相同的後果，只是入口不同（Codex re-review Critical）。
> 此時**不要** finalize，改為再跑一次 `--park` 把它放回 parked：
>
> ```bash
> mycelium lessons add --park ...   # 同一組 metadata；只重套 parked，不再次 bump recurrence
> ```
>
> 三條出口整理如下，**每條都必須落到一個明確狀態**，不得留在 reassess 中繼態：
>
> | 重評結論 | 動作 | 終止狀態 | 可重試？ |
> |---|---|---|---|
> | 仍為 Tier 3 | 再跑 `--park` | parked（recurrence 不變） | **否**——見下方 |
> | Tier 1/2 且 Promotion Gate 全過 | `lessons finalize --id` | active（同一列升級） | 是（冪等） |
> | Tier 1/2 但 Promotion Gate 未過 | 再跑 `--park` | parked（recurrence 不變） | **否**——見下方 |
>
> **`--park` 這兩條出口不可重試**：`--park` 分不出「重試同一次 occurrence」與「這是新的一次
> occurrence」，所以對**已經 re-park 的列**再跑一次同樣的 call，會走 `if "parked" in tags`
> 分支——recurrence 2→3、拿掉 `parked`、狀態翻回 reassess，那筆孤兒又重新進 tier promotion。
> 這與本 runbook 對失敗的通用指示（「停止並輸出完整 script 讓使用者手動重跑」）相衝突：
> **re-park 失敗時不要盲目重跑整個 script**，先用 `mycelium lessons show --include-parked`
> 確認該列目前是 parked 還是 reassess，再決定要不要補跑。
> （`finalize` 沒有這個問題——它是 compare-and-set，重跑是 no-op。
> PR #347 Round 2 code-reviewer 以四次連續呼叫實證這個奇偶震盪。）
>
> **與下方三道 gate 的關係**：Evidence Gate 問「這宣稱是真的嗎」；Promotion Gate 問「該不該寫進 rule
> 檔」、Classifier 問「寫到哪個檔」、Patch-Surface Ladder 問「改動面多大」。先驗真偽（Tier 1/2 帶證據
> 或 Tier 3 park），通過者才往下。

#### Promotion Gate（3 條，全通過才路由到 rule 檔）

每個 Q4 lesson 在進入 Lesson Classifier 前，先依序通過 3 條 gate。**任一失敗 → 只存在 retro 記錄裡，不寫規則文件**：

| Gate | 判斷問題 | 失敗時行動 |
|------|---------|-----------|
| **G1 automation-infeasible** | 這個 lesson 能被 hook 自動阻擋嗎？（PreToolUse / PostToolUse 能機械偵測？） | 先執行 `hookify:hookify`，不寫 rule；rule 只給 hook 無法覆蓋的情境 |
| **G2 onboarding-relevant** | 一個剛加入的貢獻者（day-1）也會犯這個錯誤嗎？ | 若 No（只有深度 context 才會踩）→ 只存在 retro 記錄裡，不開 rule |
| **G3 no existing rule covers it** | 搜尋現有 `.claude/rules/` 後，沒有任何 rule 已覆蓋此 pattern 嗎？ | 若已有 → extend 現有 rule（append），不建新 rule 檔 |

Tier 1/2 只有在 G1+G2+G3 全通過後，才執行 Step 4b prepared script 的 `state=active` call；
未全通過者不寫 typed lesson promotion path，也不得用 `active` 繞過 Evidence Gate。

> 此 gate 的設計邏輯：rule 檔是每 session 全量載入的 token cost（frontmatter 內沒有 `paths:`
> key 的 rule 永遠佔用 context；key 名寫錯——`globs:` / `glob:` / `path:`——會被靜默忽略，
> 效果等同沒寫，該檔案變成全量載入）。
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
| 查歷史 lesson | `Skill(skill="lessons", args="find <Q1 keyword>")` **自動執行**。headless / 直接打 CLI 時用 `mycelium lessons search "<keyword>" --project "$ORIG_PROJECT"` — CLI 子指令是 **`search`**（`find` 只是 `/lessons` slash 的別名，raw CLI **無** `find` 子指令），且**不要**加 `2>/dev/null`，否則子指令打錯會被靜默吞成「無結果」 |
| 寫入規則文件 | **須先通過 Step 5.0 Evidence Gate（Tier 1/2 帶證據；判為 Tier 3 則改 park，不寫 rule）**。通過後**先走下方「批次佇列分流」判斷**。緊急例外、或 target repo 無佇列時，才照原行為——依 Lesson Classifier 輸出建議：「lesson N 屬於 <類別>，建議 append 到 `.claude/rules/XX.md`（最相關段落後；不確定就 append 到檔尾）。草稿：`<draft text>`（附證據標記：Tier 1 標 `<!-- verified: probe -->`、Tier 2 標 `(Source: PR #NNN`）。用 Edit 工具直接寫入 rule 檔。」|
| 新增 hook | **須先通過 Step 5.0 Evidence Gate（Tier 1/2 帶證據；判為 Tier 3 則改 park）**。輸出建議文字：「執行 `hookify:hookify`，建議的 trigger：`<draft>`（附正 / 負樣本作為 Tier 1 證據）」|
| 建立 skill | 輸出建議文字：「執行 `superpowers:writing-skills`，問題定義：`<Q4 lesson>`」|
| 找 automation | 輸出建議文字：「執行 `/claude-code-setup:claude-automation-recommender`」|
| 產生 control log | 執行 `Skill(skill="pr-control-log")` 紀錄本 PR 的 AI 行為審計 entries |

寫檔動作**只建議**，由使用者決定是否執行。

#### 批次佇列分流（「寫入規則文件」與 CLAUDE.md / memory 類落地需求適用）

採用 harness 批次化流程的 repo（如 yibi-mvp，design doc：該 repo
`docs/research/2026-07-23-harness-batch-workflow-design.md`）不再對每條散文類
harness 改動當場寫檔＋開 PR，而是排進常設佇列 issue、每週由 `/harness-batch`
結批成一個 PR。Promotion Gate（G1-G3）、Lesson Classifier、Patch-Surface Ladder
**照常先跑**——它們決定「值不值得落地、落到哪、用多重的手段」；本分流只攔截
最後的「怎麼送出」：

1. **緊急例外判斷**（二擇一成立即為緊急）：
   - 機械 gate 修「正在流血」的洞——延後一週有可預期的具體事故會發生；
   - 修正既有 rule / CLAUDE.md 的**錯誤內容**（錯的指引會誤導每個 session；
     刪除冗餘不算錯誤）。

   緊急 → 照上表原行為（Edit 直接寫檔，建議立即開獨立 PR）。
2. **非緊急 → 只寫 episode 到 Mycelium，不自動排入佇列**：

   Lesson 已在 Step 5 寫入 Mycelium（`epistemic_status = "episode"`）。
   **不再自動執行 `gh issue comment`**——讓 episode 在 Mycelium 自然累積，
   由 distill 聚合成 observation 後再由人類決定是否進入 policy candidate。

   如使用者判斷此 lesson 應立即排入 harness queue，可手動執行以下指令：

   ```bash
   gh issue list --label harness-queue --state open --json number,title
   ```

   若找到恰好 1 筆佇列 issue（假設編號為 N），使用者可自行操作：

   1. 把以下模板存成暫存檔（替換 `<>` 佔位符）：

      ```markdown
      ### [queue] <一句摘要>
      - type: rule-prose | gate-script | claude-md | skill | memory | other
      - 來源：PR #<n> retro / lesson key `<slug>`
      - 建議落點：`<檔案路徑>`
      - 建議 patch-surface：description | workflow-gate | reference-rule | script-helper
      - 草稿：<1-3 句的改動內容草稿>
      ```

   2. 發布到 queue issue：

      ```bash
      gh issue comment <N> --body-file <暫存檔路徑>
      ```

   Agent 的職責到顯示上述提示為止。

---

### Step 6 — 確認寫入

```bash
mycelium retro read --last 1 --project "$ORIG_PROJECT"
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
> mycelium retro migrate-from-handovers
> ```
>
> 若要查詢過往 retro：
>
> ```bash
> mycelium retro search --pr-number <n> --project "$ORIG_PROJECT"
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
| 如何只看 PR retro？ | `mycelium retro search --pr-number <n> --project "$ORIG_PROJECT"` 或 `mycelium retro read --last N --project "$ORIG_PROJECT"` |
| Agent 推論總是抓不到重點？ | iteration > 3 次後切換「請使用者直接給答案」模式 |
| 想改寫已存在的 retro | append-only；建議寫新一筆並在 tags 加 `revised`；舊 retro 留存（`retrospectives` 沒有 `pr_number` 唯一限制，允許同 PR 多筆） |
| token/cost 數字看起來偏高或偏低 | 計算範圍是整個 session（從開始到呼叫 `/pr-retro` 為止），若同一 session 混雜了其他不相關的工作，數字會失真；這是已知限制 |
| token-usage report 印出 `[WARN]` 找不到 transcript 或偵測到並行 session | best-effort 啟發式無法保證找到，屬正常情況；不影響 retro 寫入，繼續往下走即可 |
| 這次改版之前寫的舊 retro 去哪了？ | 還在 `handovers` table（帶 `pr-retrospective` tag），執行一次性遷移工具 `retro migrate-from-handovers`（冪等，可重複執行）把它們搬進 `retrospectives` |

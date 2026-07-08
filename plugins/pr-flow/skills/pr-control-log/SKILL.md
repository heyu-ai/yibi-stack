---
name: pr-control-log
type: tool
scope: global
description: >
  PR 完成後的 AI 行為審計 control log：agent 從 git log / PR diff / PR body 推論
  autonomous_decision、assumption、spec_deviation 等 7 類行為 entries，
  使用者最多 3 輪校準後寫入 mycelium DB，並產生 .runtime/control-logs/pr-<N>.md
  markdown artifact（含 11 個 section）。統計 autonomy_ratio / deviation_ratio /
  verification_score，依閾值給出 rule/hook/skill 補充建議。
  觸發關鍵字：control log、行為審計、autonomy ratio、AI 自主決定比例、
  spec deviation、pr control log、ai governance
---

# PR Control Log — AI 行為審計

## 適用情境

- PR merge 後想記錄 AI 本次自主決定了哪些事、偏離了哪些規格
- 想追蹤 autonomy_ratio / deviation_ratio 趨勢以決定是否補充 rules/hooks
- 與 `/pr-retrospective` Q5 下游觸發整合

## 不適用

| 情境 | 應使用 |
|------|--------|
| 即時攔截 AI 操作 | Phase 3 PostToolUse hook（尚未實作）|
| 學習記錄 | `/pr-retrospective` + mycelium lessons |

---

## 步驟

### Step 0 — 環境與 PR 偵測

先解析 `SKILL_REPO`（bootstrap script 住在 yibi-stack repo，必須先定位才能呼叫——
不能反過來用 bootstrap 的輸出定義 `SKILL_REPO`）：

```bash
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; c=json.loads((pathlib.Path.home()/".agents"/"config.json").read_text(encoding="utf-8")); print((c.get("skill_repos") or {}).get("yibi-stack") or c.get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi
```

再執行 bootstrap：

```bash
bash "$SKILL_REPO/plugins/pr-flow/skills/pr-control-log/scripts/bootstrap.sh"
```

解析 stdout 的 `ORIG_PROJECT` / `REAL_WORKDIR` / `BRANCH`（script 也會回報它自己解析的
`SKILL_REPO`，應與上方一致）。
如果 script 輸出 `[FAIL]`，停止並回報錯誤。

然後偵測 PR 號：

```bash
bash "$SKILL_REPO/plugins/pr-flow/skills/pr-control-log/scripts/detect-pr.sh"
```

解析 `PR_NUMBER`。
如果 script 輸出 `[FAIL]`，停止並請使用者加 `--pr <n>` 重試。

### Step 1 — 推論草稿 entries（Entry inference from PR context）

從以下三個 context 來源推論 entries：

1. `git log --oneline origin/main..HEAD` — 取得 agent-authored commits
2. PR diff 重點（`gh pr diff`）— 找到 tradeoff comments / nosec / TODO
3. PR body（`gh pr view --json body -q .body`）— 找到 assumption / decision 陳述

對每個發現的 agent 行為，建立草稿 entry（至少包含三個必填欄位）：

```yaml
category: <7 值之一>
summary: <一行摘要，說明 AI 做了什麼>
user_requested: <0 = AI 自主 | 1 = 使用者明確要求>
```

**推論規則：**

| context 信號 | 建議 category | user_requested |
|-------------|---------------|----------------|
| commit: "chose X over Y" 無使用者指示 | autonomous_decision | 0 |
| commit/PR body: "as requested by user / 使用者要求" | autonomous_decision | 1 |
| 程式碼中的 TODO / assumption comment | assumption | 0 |
| `# nosec` / `# noqa` 新增 | tradeoff | 0 |
| spec 有但程式碼沒有的 AC | spec_deviation | 0 |
| `git reset --hard` / `rm -rf` / force push | irreversible_op | 0 |
| `pytest` / `make ci` / smoke test runs | verification | 0 |
| revert commit | rollback | 0 |

至少一個 entry 的 category 必須為 `autonomous_decision`（若 PR 有 agent-authored commits）。

### Step 2 — 使用者校準 loop（最多 3 輪，AC-002）

呈現草稿 entries（表格形式）給使用者，說明：

> 以下是本 PR 的 AI 行為草稿。請確認、修改、刪除，或新增。
> 你有 3 輪校準機會。

**校準動作：**

- **確認（approve）**：進入 Step 3
- **修改 summary**：更新對應 entry，重新呈現，計 1 輪
- **刪除 entry**：從草稿移除，重新呈現，計 1 輪
- **新增 entry**：新增 entry（user_requested=1），重新呈現，計 1 輪

**第 3 輪後仍有修改需求：**

> 已達 3 輪校準上限。請選擇：
> (A) 以目前草稿寫入  (B) 放棄，不寫入任何 entry

若使用者選 B，輸出 `已放棄，未寫入任何 entry` 後結束。

### Step 3 — 寫入 DB entries

對每個確認的 entry，執行：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.mycelium control-log add \
  --pr "$PR_NUMBER" \
  --category "<category>" \
  --summary "<summary>" \
  --user-requested <0|1> \
  [--evidence "<evidence>"] \
  [--severity <low|medium|high>] \
  [--verification-status <verified|partial|unverified>] \
  [--project "$ORIG_PROJECT"]
```

每個 entry 確認輸出 `已寫入 control log entry (id=N)`。
如果任何 add 命令失敗，停止並回報錯誤給使用者。

完成後輸出：`✓ 已寫入 N 筆 entries`（N = 實際寫入筆數）。

### Step 4 — 產生 Markdown artifact（AC-002-3~4）

在 `$REAL_WORKDIR/.runtime/control-logs/` 建立 `pr-$PR_NUMBER.md`（若目錄不存在先建立）。

Artifact 結構（12 個 section，0~11，不可省略）：

```markdown
# PR Control Log — PR #<N>: <PR Title>

**Project:** <ORIG_PROJECT>
**Branch:** <BRANCH>
**Date:** <today>
**Total entries:** <N>

---

## 0. 語言與目標讀者

本文件由 AI agent 輔助生成，供人類開發者在 PR review 期間閱讀。

## 1. 任務目標與範圍

<從 PR body 或 proposal 摘要>

## 2. 使用者明確要求

<user_requested=1 的 entries>

## 3. Assumptions

<category=assumption 的 entries>

## 4. Autonomous Decisions

<category=autonomous_decision 的 entries>

## 5. Spec Deviations

<category=spec_deviation 的 entries；無則 "N/A">

## 6. 變更追溯表（Surgical Change Traceability）

| File | Change | Rationale |
|------|--------|-----------|
<從 git diff --stat 與 entries 交叉對應>

## 7. Trade-offs

<category=tradeoff 的 entries；無則 "N/A">

## 8. 不可逆操作清單

<category=irreversible_op 的 entries；無則 "N/A">

## 9. 驗證結果

<category=verification 的 entries；無則 "N/A">

## 10. Rollback Plan

<category=rollback 的 entries；無則 "N/A">

## 11. 人類審閱摘要

<統計：autonomy_ratio / deviation_ratio / verification_score（若有 3+ 筆）>
<建議（generate_advice 結果）>
```

**Sections 無 entries 時**必須寫 `N/A` 或 `無此類型 entries`，不可省略 section heading。
Artifact **不應** commit（`.runtime/` 在 `.gitignore`）。

### Step 5 — 顯示統計（選用，若 entries >= 3）

```bash
uv run --directory "$SKILL_REPO" python -m tasks.mycelium control-log stats --since-days 90
```

顯示四個指標。若有建議：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.mycelium control-log advice --since-days 90
```

---

## FAQ

| 問題 | 解決方式 |
|------|---------|
| bootstrap.sh `[FAIL] skill_repo not configured` | 在 yibi-stack 根目錄執行 `make install`，設定 `~/.agents/config.json` 的 `skill_repo` |
| detect-pr.sh `[FAIL] no PR detected` | 傳入 `--pr <n>` 引數，或確認在有 PR 的分支上 |
| `control-log add` 失敗 | 確認 `uv` 與 `tasks.mycelium` module 存在：`uv run --directory "$SKILL_REPO" python -m tasks.mycelium --help` |
| artifact 路徑不存在 | `.runtime/control-logs/` 不存在時 agent 應先 `mkdir -p` 建立 |

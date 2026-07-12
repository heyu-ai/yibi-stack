---
name: skill-trigger-eval
type: exec
scope: project
description: >
  評測單一 skill 的觸發準確度（trigger accuracy）：載入該 skill 旁的 trigger_eval.json
  三類 prompt（direct/indirect/negative），派 subagent 逐一判斷目標 skill 是否會觸發，
  算出各類 pass rate 並與 baseline 比對，偵測觸發回歸（over-trigger / under-trigger）。
  觸發關鍵字：skill 觸發評測、trigger eval、觸發準確度、over-trigger 回歸、pass rate、
  direct/indirect/negative、regression gate、觸發詞誤搶 sibling。
  注意：這不是關鍵字重疊「靜態」偵測（那是 scripts/lint_skill_overlap.py / B1），
  也不是 PR review／PR lifecycle（請改用 /pr-review-cycle、/pr-cycle-fast、/pr-cycle-deep）。
---

# Skill Trigger Eval（觸發準確度評測）

以 fixture 驅動的 LLM-judge 評測：量測「給定一個 prompt，目標 skill 是否正確觸發」，
補 B1（`scripts/lint_skill_overlap.py`，只做確定性關鍵字重疊靜態偵測）無法量測實際觸發行為的洞。

判斷由 subagent 完成（Design B，agent-driven，無需 API key）；Python 端只負責載入 fixture、
建構任務清單、計分與 baseline 比對，全程無 LLM 依賴。

## Steps

### Step 1 — 環境確認

確認位於 repo 根目錄且 `uv` 可用。決定要評測的目標 skill 名稱 {{skill_name}}（其
`SKILL.md` 旁需存在 `trigger_eval.json`；可用 `--all` 評測所有具 fixture 的 skill）。

### Step 2 — 產生判斷任務 manifest

```bash
uv run python -m tasks.skill_eval eval --skill {{skill_name}} --emit-manifest > "$CLAUDE_JOB_DIR/manifest.json"
```

`manifest.json` 是任務陣列，每個元素含 `index / skill / cls / prompt / expect_trigger`。
若指令失敗，停止並回報錯誤。

### Step 3 — 派 subagent 判斷觸發

以 `Explore` subagent（唯讀）處理 manifest：對每個 task，讀取
`skills/<task.skill>/SKILL.md` 的 frontmatter `description`，判斷「若使用者輸入
`task.prompt`，這個 description 會不會觸發該 skill」。

輸出一個與 manifest 等長、依 `index` 對齊的布林陣列（true=會觸發），寫入
`$CLAUDE_JOB_DIR/judgments.json`。**陣列長度必須等於 manifest 長度**，否則 Step 4 會
以 RuntimeError 中止（刻意不補零）。

判斷準則（與 rule 11 一致）：只依 `description` 的觸發詞與 negative 導引文字判斷，
不看 SKILL.md 內文步驟；`negative` 類 prompt 的正確答案是「不觸發」。

### Step 4 — 計分並比對 baseline

```bash
uv run python -m tasks.skill_eval eval --skill {{skill_name}} --judgments "$CLAUDE_JOB_DIR/judgments.json"
```

輸出各類 pass rate。若某類低於 baseline 減容忍門檻（預設 0.1），指令 exit 1 並列出回歸的
skill 與類別。首次評測（baseline 尚無此 skill）不會誤報回歸。

### Step 5 — （選用）更新 baseline

確認當前 pass rate 為期望基準後，寫入 baseline（`.runtime/skill_eval_baseline.json`）：

```bash
uv run python -m tasks.skill_eval baseline --skill {{skill_name}} --judgments "$CLAUDE_JOB_DIR/judgments.json"
```

## FAQ

| 問題 | 解法 |
| ---- | ---- |
| 找不到 fixture | 在 `skills/<skill>/` 旁建立 `trigger_eval.json`（含 direct/indirect/negative 三陣列） |
| judgments 數與 manifest 不符 | subagent 輸出的布林陣列長度需等於 manifest；重跑 Step 3 對齊 index |
| 首評就報回歸 | 不會——baseline 無此 skill 時視為無基準，先用 Step 5 建立 baseline |
| 想一次評測全部 | 用 `--all` 取代 `--skill <name>`（會評所有具 fixture 的 skill） |

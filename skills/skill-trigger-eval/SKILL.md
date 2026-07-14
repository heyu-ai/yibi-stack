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
uv run python -m tasks.skill_eval eval --skill {{skill_name}} --manifest "$CLAUDE_JOB_DIR/manifest.json" --judgments "$CLAUDE_JOB_DIR/judgments.json"
```

`--manifest` 為必要：judgments 依 index 對位，fixture 在 Step 2 之後只要改動就會靜默錯位。
指令會核對簽章，不符即 `[FAIL]` 中止，而非算出靜默錯誤的 pass rate。輸出各類 pass rate。
若某類低於 baseline 減容忍門檻（預設 0.1），指令 exit 1 並列出回歸的 skill 與類別。
首次評測（baseline 尚無此 skill）不會誤報回歸。

若確有理由跳過核對，須顯式加 `--no-manifest-check`（會印 `[WARN]`）——讓「跳過」成為一個
被記錄的決定，而非預設行為。

### Step 5 — （選用）更新 baseline

確認當前 pass rate 為期望基準後，寫入 baseline（`.runtime/skill_eval_baseline.json`）。
**須傳與 Step 4 相同的 `--manifest`**：

```bash
uv run python -m tasks.skill_eval baseline --skill {{skill_name}} --manifest "$CLAUDE_JOB_DIR/manifest.json" --judgments "$CLAUDE_JOB_DIR/judgments.json"
```

`baseline` 的 `--manifest` 沒有跳過選項（`eval` 才有 `--no-manifest-check`）：`eval` 算錯只是
一次性輸出，`baseline` 卻會把錯位的 pass rate 寫成往後每次 gate 的比較基準，污染是持久的。

> **已知限制**：`baseline --skill <name>` 目前會整檔覆寫，抹掉其他 skill 的既有基準
> （issue #219）；在該問題修復前，若 baseline 已含多個 skill，請改用 `--all` 一次寫入。
> 另外 baseline 存於 gitignore 的 `.runtime/`，未進版控，故在 CI／新 clone 上此 gate
> 目前不會實際把關（issue #220）。

## FAQ

| 問題 | 解法 |
| ---- | ---- |
| 找不到 fixture | 在 `skills/<skill>/` 旁建立 `trigger_eval.json`（含 direct/indirect/negative 三陣列） |
| judgments 數與 manifest 不符 | subagent 輸出的布林陣列長度需等於 manifest；重跑 Step 3 對齊 index |
| 首評就報回歸 | 不會——baseline 無此 skill 時視為無基準，先用 Step 5 建立 baseline |
| 想一次評測全部 | 用 `--all` 取代 `--skill <name>`（會評所有具 fixture 的 skill） |
| `[FAIL] 請提供 --manifest` | Step 4/5 須傳 Step 2 產出的 `manifest.json`；judgments 必然來自先前的 `--emit-manifest`，故一定有檔可傳 |
| `[FAIL] manifest 與當前 fixture 不符` | fixture 在 Step 2 後變動（或 `--skill`/`--all` 選擇與 emit 當下不同）。重跑 Step 2 產生新 manifest，再重跑 Step 3 重判 judgments |
| `[FAIL] 下列 skill 的 fixture 三類皆空` | 該 fixture 沒有任何 prompt，不會被當作通過。補齊 direct/indirect/negative 至少一筆 |
| `[FAIL] --tolerance 須為 0.0 <= t < 1.0` | `nan` 或 `>= 1.0` 會讓回歸偵測恆不觸發（等同關閉 gate），故被拒 |
| `[FAIL] baseline 格式錯誤` | baseline 檔須為 `skill -> class -> 0.0~1.0` 浮點數；`null` 或其他形狀代表檔案已損壞，不會被當成「無基準」略過 |
| `[WARN] --all 只涵蓋 skills/ 第一層` | 該 fixture 在 `plugins/` 底下但 `skills/` 搆不到（未 symlink，或是巢狀 sub-skill）。用 `--skill <name>` 個別評測，或建立 symlink |

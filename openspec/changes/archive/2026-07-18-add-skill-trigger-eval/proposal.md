## Why

yibi-stack 有 per-skill 觸發準確度的驗證缺口：B1（`scripts/lint_skill_overlap.py`，PR #190）只做確定性關鍵字重疊靜態偵測，只能示警「description 看起來易混」，無法量測「給定一個 prompt，目標 skill 是否真的正確觸發」。over-trigger / under-trigger 風險在 PR lifecycle、retro、harness、TDD 等家族已確實存在（見 rule 11），目前只靠人工在 description 寫「請改用 X」互斥文字硬擋，沒有任何回歸防護——改一次 description 就可能靜默破壞觸發邊界而無人察覺。

## What Changes

- 新增 `tasks/skill_eval/` 模組（仿 `tasks/harness_eval/` 佈局，rule 04），提供 skill 觸發準確度評測。
- 確定性核心：載入 fixture → 對每個 prompt 取得 judge verdict → 算 pass rate → 與 baseline 比對 → 產出回歸報告。核心本身不含 LLM，可完整單元測試。
- 可插拔 judge backend：核心透過一個 Judge 介面取得 verdict，backend 可替換。本 change 只實作 `judges/agent.py`（Design B，agent-driven：核心產出 judge 任務清單，由 SKILL.md 派 Claude subagent 判斷，無需 API key）。
- Fixture schema：每個 skill 的 `trigger_eval.json` 放在其 `SKILL.md` 旁，含 `direct[] / indirect[] / negative[]` 三類 prompt（對映 rule 11 的 direct/indirect/negative 三軸）。
- CLI：`eval`（跑評測、比對 baseline、出報告）與 `baseline`（把當前 pass rate 寫成 baseline）兩個 subcommand。
- Agent-driven runbook：新增 `skills/skill-trigger-eval/SKILL.md`，說明如何派 subagent 判斷 verdict 並回饋給 CLI。
- **後續增量（本 change 只在 design.md 定義，不實作）**：`judges/api.py`（Design A，API key headless，供 `workflow_dispatch` 手動 CI gate）；`judges/acp.py`（Design A-local，本機 MiniShell ACP Gateway 訂閱認證）；月頻本機 scheduler 漂移報告。

## Capabilities

### New Capabilities

- `skill-trigger-eval`: 給定一個 skill 的 `SKILL.md` description 與其 `trigger_eval.json` fixture，透過可插拔 judge backend 判斷每個 direct/indirect/negative prompt 是否正確觸發目標 skill，算出分類 pass rate，並與 baseline 比對，超出容忍門檻時回報回歸。

### Modified Capabilities

(none)

## Impact

- Affected specs: `skill-trigger-eval`（new）
- Affected code:
  - New:
    - tasks/skill_eval/__init__.py
    - tasks/skill_eval/__main__.py
    - tasks/skill_eval/models.py
    - tasks/skill_eval/config.py
    - tasks/skill_eval/service.py
    - tasks/skill_eval/judges/__init__.py
    - tasks/skill_eval/judges/base.py
    - tasks/skill_eval/judges/agent.py
    - tasks/skill_eval/tests/__init__.py
    - tasks/skill_eval/tests/test_models.py
    - tasks/skill_eval/tests/test_service.py
    - tasks/skill_eval/tests/test_cli.py
    - skills/skill-trigger-eval/SKILL.md
    - skills/skill-trigger-eval/trigger_eval.json
  - Modified:
    - skills/README.md
  - Removed: (none)

## User Stories（Step 1，[ADDED] amplifier）

### US-001：量化 skill 的觸發準確度

**Persona**：維護觸發詞高度相近之 skill 家族（如 PR lifecycle：pr-cycle-fast / pr-cycle-deep / pr-review-cycle）的 skill 作者；目前只能靠人工在 description 寫「請改用 X」互斥文字，無法量化「這個 skill 對哪些 prompt 會／不會觸發」。
**Action**：對目標 skill 跑觸發評測，取得 direct / indirect / negative 三類 pass rate。
**Outcome**：得到可量化的觸發準確度，定位 over-trigger（誤搶 sibling）與 under-trigger（換句話說就不觸發）。

**Acceptance Criteria**：
- AC-001-1：fixture 依 direct / indirect / negative 三類載入；negative 的 `expect_trigger` 必為 false，違反則驗證失敗（對映 W2）。
- AC-001-2：逐類算 pass rate；direct/indirect pass=判觸發、negative pass=判未觸發。
- AC-001-3：計分核心只透過 Judge 介面取得判斷，不 import LLM client。
- AC-001-4：judgments 數與 manifest 不符時抛錯，不補零不截斷（對映 R3 / invariant）。
- AC-001-5：目標 skill 缺 `trigger_eval.json` 時明確失敗（非零退出），不當作通過。
- AC-001-6：CLI 註冊 `eval` 與 `baseline` subcommand，皆出現在 `--help`。

五尺度自我檢查：單一 Actor（skill 作者）、單一 Goal（量測準確度）、6 條可獨立測試的 AC → 中尺度 User Story。

### US-002：觸發回歸守門

**Persona**：改動了某 skill 的 description（觸發詞）的 skill 作者，擔心無意間破壞既有觸發邊界卻無人察覺。
**Action**：把當前 pass rate 存為 baseline，日後評測自動與之比對。
**Outcome**：description 改動造成的觸發回歸被自動偵測，不需人工回想「原本的基準是多少」。

**Acceptance Criteria**：
- AC-002-1：`baseline` subcommand 以當前 judgments 計算 pass rate 並持久化（skill→class→pass_rate，對映 W3）。
- AC-002-2：`eval` 比對 baseline，任一類 pass rate < baseline − tolerance 時回報回歸並非零退出。
- AC-002-3：baseline 無此 skill／類別時不誤報回歸（首評不觸發 gate）。

五尺度自我檢查：單一 Actor、單一 Goal（回歸守門）、3 條 AC → 中尺度 User Story。

## 假設與約束（Step 4，[ADDED] amplifier）

> 假設表衍生自 `problem-frame.md` 的 W（單一來源，不另行重編）。

| # | 假設內容（來源 W）| 若不成立的影響 |
|---|-------------------|----------------|
| A1（W1）| 回饋的 judgments 由外部 agent 依 prompt × 目標 skill description 誠實判斷且依 index 對齊 | pass rate 反映錯位／亂填的判斷，評測無意義 |
| A2（W2）| fixture 的 `expect_trigger` 正確反映作者意圖（已由 model_validator 強制形狀）| pass 定義被扭曲，回歸訊號失真 |
| A3（W3）| baseline 是先前一次「作者已接受」的評測快照 | 回歸比對基準無效 |
| A4（W4）| 同一 fixture 的 prompt 集合在 emit-manifest 與 score 之間不變 | judgments 依 index 對位錯誤 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | 計分核心不得含任何 LLM 呼叫（可完整單元測試）| 設計約束（Design B，測試性）|
| C2 | negative prompt 的 `expect_trigger` 恆為 false | rule 05 model_validator |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| `judges/api.py`（API key headless）+ `workflow_dispatch` CI gate | Phase 1 聚焦零成本、零 Usage Policy 風險的 agent-driven 路徑 | Phase 2 |
| 月頻本機 scheduler 漂移報告 | 排程 = 漂移報告，不綁特定 PR，與 gate 語意不同 | Phase 3 |
| 自動產生 fixture | fixture 需人工 curate 以反映真實觸發意圖 | 以 B1 重疊輸出當投資清單，人工補 |
| 全 skill 覆蓋 | Phase 1 僅附一個高風險家族示範 fixture | 依 B1 輸出逐家族擴充 |

## Done 定義與 Traceability（Step 5，[ADDED] amplifier）

### Done 定義

- [x] US-001 / US-002 所有 AC 已實作
- [x] testplan.md 的核心 9 個 Scenario 均有對應測試（見 Traceability Matrix）
- [x] 冒煙測試 SMK-001（`--help` 列出 eval/baseline）通過
- [x] `make ci` 全綠（1361 passed）
- [ ] 程式碼已 code review 並合併（PR #211，draft）

### Traceability Matrix

| US | Gherkin scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `valid-fixture-loads` | SEVAL-EP-001 | `spec: skill-trigger-eval#valid-fixture-loads` |
| US-001 | `negative-expect-trigger-true-rejected` | SEVAL-VL-001 | `spec: skill-trigger-eval#negative-expect-trigger-true-rejected` |
| US-001 | `negative-not-triggered-passes` | SEVAL-DT-001/002（實作編號）| `spec: skill-trigger-eval#negative-not-triggered-passes` |
| US-001 | `core-scores-via-interface` | SEVAL-ST-004（實作編號）| `spec: skill-trigger-eval#core-scores-via-interface` |
| US-001 | `verdict-count-mismatch-surfaced` | SEVAL-BVA-002 | `spec: skill-trigger-eval#verdict-count-mismatch-surfaced` |
| US-001 | `absent-fixture-fails-loud` | SEVAL-ST-002 | `spec: skill-trigger-eval#absent-fixture-fails-loud` |
| US-001 | `eval-baseline-discoverable`（SMK-001）| SEVAL-SMK-001 | `spec: skill-trigger-eval#eval-baseline-discoverable` |
| US-002 | `regression-below-tolerance-exits-nonzero` | SEVAL-ST-004 | `spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero` |
| US-002 | `within-tolerance-passes` | SEVAL-EP-002 | `spec: skill-trigger-eval#within-tolerance-passes` |

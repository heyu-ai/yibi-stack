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

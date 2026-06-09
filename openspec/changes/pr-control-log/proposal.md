## Why

跨 session 的 AI 開發行為缺乏結構化記錄——哪些決定是 AI 自主做的、哪些偏離了規格、有多少不可逆操作——導致無法根據客觀數據判斷是否需要新增 rules、hooks 或 skills 來規範 AI 行為。

## What Changes

- 新增 `pr-control-log` skill（`plugins/pr-flow/skills/pr-control-log/`）：在每次 PR retro 後推論並記錄 11 個審計欄位，包括 AI 假設、自主決定、規格偏離、取捨、不可逆操作、驗證與回滾
- 擴充 mycelium DB，新增 `control_log_entries` 與 `control_log_sessions` 兩個資料表
- 新增 `tasks/mycelium/control_log_service.py`：提供寫入、讀取、跨 session 統計（`autonomy_ratio` / `deviation_ratio` / `verification_score`）與 rule/hook/skill 建議
- 擴充 `mycelium` CLI，加入 `control-log` subcommand group（`add` / `show` / `stats` / `advice`）
- 整合 `plugins/pr-flow/skills/pr-retrospective/SKILL.md`，在 Q5 actions 加入「產生 control log」選項
- 同時輸出人類可讀的 markdown artifact 到 `.runtime/control-logs/pr-<N>.md`（不 commit）

## Non-Goals

- 不做 PostToolUse hook 即時自動 capture（留到 Phase 3，待驗證推論流程足夠後再開新 PR）
- 不做 GitHub Actions daily digest cron 整合（跨 session 統計用 CLI 即可）
- 不做多語言模板（本 repo 慣例 zh-TW）
- control log 不進入 mycelium lessons tier promotion（兩者生命週期不同）

## Capabilities

### New Capabilities

- `control-log-capture`: 從 PR context 推論並記錄 AI 行為審計 entry，包含 11 個 schema
  欄位（assumption / autonomous_decision / spec_deviation / tradeoff / irreversible_op /
  verification / rollback），支援使用者校準後寫入 DB 並輸出 markdown artifact
- `control-log-analytics`: 跨 session 統計分析，計算 autonomy_ratio / deviation_ratio /
  irreversible_op_count / verification_score，並根據閾值產生 rule/hook/skill 建議

### Modified Capabilities

（無——本次為全新功能，不修改現有 spec）

## Impact

- Affected specs: `control-log-capture`（新建）、`control-log-analytics`（新建）
- Affected code:
  - New: `tasks/mycelium/control_log_service.py`,
    `tasks/mycelium/tests/test_control_log_service.py`,
    `tasks/mycelium/tests/test_control_log_db.py`,
    `tasks/mycelium/tests/test_control_log_cli.py`,
    `plugins/pr-flow/skills/pr-control-log/SKILL.md`,
    `plugins/pr-flow/skills/pr-control-log/scripts/bootstrap.sh`,
    `plugins/pr-flow/skills/pr-control-log/scripts/detect-pr.sh`
  - Modified: `tasks/mycelium/db.py`, `tasks/mycelium/models.py`, `tasks/mycelium/cli.py`,
    `plugins/pr-flow/skills/pr-retrospective/SKILL.md`, `skills/README.md`
  - Removed: none

---

## User Stories

### US-001：Entry 推論與寫入

**Persona**：Claude agent，在 PR retro 後執行 `pr-control-log` skill，需要將本次
PR 中的 AI 行為結構化記錄下來。

**Action**：從 git log + PR diff + PR body 推論 AI 行為，產出 11 欄位 entry draft。

**Outcome**：使用者校準後，entries 寫入 `control_log_entries`，日後可查詢與統計。

**Acceptance Criteria**：

- AC-001-1：agent 依 PR context（git log / PR diff / PR body）推論出至少一筆
  `autonomous_decision` 類別的 entry
- AC-001-2：每筆 entry 含 `category` / `summary` / `user_requested` 三個必填欄位
- AC-001-3：使用者拒絕某 entry 時，該 entry SHALL NOT 寫入 `control_log_entries`
- AC-001-4：所有 entries 寫入後，CLI 輸出已寫入筆數（`✓ 已寫入 N 筆 entries`）

---

### US-002：使用者校準與 Markdown Artifact 產出

**Persona**：Developer，PR 完成後審視 AI 行為 draft 並校準。

**Action**：在 ≤3 輪內修改、刪除、新增 entries，確認後產出 markdown artifact。

**Outcome**：`.runtime/control-logs/pr-<N>.md` 包含 12 個 section，人類可直接審閱。

**Acceptance Criteria**：

- AC-002-1：使用者可在 3 輪校準內任意修改 entries（新增 / 刪除 / 更新 summary）
- AC-002-2：超過 3 輪時，system SHALL 詢問「是否以目前狀態 finalize 或中止？」
- AC-002-3：使用者確認後，`.runtime/control-logs/pr-<N>.md` SHALL 包含 sections 0–11
- AC-002-4：artifact SHALL NOT 被 commit 到 git（`.runtime/` 已在 `.gitignore`）

---

### US-003：跨 Session 統計查詢

**Persona**：Developer，定期執行 CLI stats 觀察 AI 行為趨勢。

**Action**：`control-log stats --since-days D` 查詢時間窗口內的統計指標。

**Outcome**：取得 `autonomy_ratio` / `deviation_ratio` / `irreversible_op_count` /
`verification_score` 四個指標，用於 governance 決策。

**Acceptance Criteria**：

- AC-003-1：`stats --since-days D` 輸出包含四個指標與 `total_entries` 的表格
- AC-003-2：`--json` flag 輸出可以 `json.loads()` 解析的 JSON（含四個 metric key）
- AC-003-3：分母為 0 時指標顯示 `N/A`（`None` in Python，非 `0.0`）
- AC-003-4：`--by category` 依 category 分組輸出各類別 entry count
- AC-003-5：`--by project` 依 project 分組輸出各專案統計

---

### US-004：Governance 建議產生

**Persona**：Developer，希望根據 AI 行為趨勢數據，決定是否需要補充 rules / hooks。

**Action**：`control-log advice --since-days D` 取得 zh-TW 治理建議。

**Outcome**：依閾值規則（R1–R4）獲得具體建議文字，或確認「目前無建議」。

**Acceptance Criteria**：

- AC-004-1：`autonomy_ratio` > 30% → R1 建議輸出
- AC-004-2：`deviation_ratio` > 20% → R2 建議輸出
- AC-004-3：同類 `irreversible_op` pattern 出現 >= 3 次 → R3 建議輸出
- AC-004-4：`verification_score` < 60% → R4 建議輸出
- AC-004-5：無規則觸發 → 輸出 `目前無建議`
- AC-004-6：entries < 3 筆 → 標注資料不足，SHALL NOT 觸發任何 advice rule

---

## 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | mycelium DB（`handover.db`）已透過 `AgentsDB().init_db()` 初始化 | 寫入 entry 時回傳 table not found error |
| A2 | `.runtime/` 已在 `.gitignore` 中 | artifact 可能被誤 commit |
| A3 | PR 已有 `gh pr view` 可取得的 metadata（PR body 含 AC/spec 描述）| 推論品質下降，使用者需多輪校準 |
| A4 | Phase 3（PostToolUse hook）尚未實作 | 需手動觸發 skill；即時 capture 無法實現 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | 校準輪數 ≤ 3 次 | SKILL.md 設計決策，避免無限循環 |
| C2 | 統計分母為 0 時回傳 `None`，非 `0.0` | 設計決策，防止 0% 誤導 |
| C3 | `category` 限定 7 個固定值 | `ControlLogCategory` StrEnum 硬編碼 |
| C4 | `.runtime/control-logs/` 不 commit | `.gitignore` 慣例，與 `.runtime/scheduler.db` 一致 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| PostToolUse hook 即時 capture | Phase 1+2 先驗證推論流程是否足夠，避免 noise | Phase 3 下個 PR 評估 |
| GitHub Actions daily digest | CLI stats 統計已滿足需求 | 若需通知機制再加 |
| Lessons tier promotion 整合 | control log 與 lessons 生命週期不同 | 獨立演進，不強耦合 |
| 多語言模板 | 本 repo 慣例 zh-TW | — |

---

## Done 定義

此功能視為「完成」的條件：

- [ ] US-001~004 所有 AC 均已實作並通過測試
- [ ] `pytest tasks/mycelium/tests/test_control_log_*.py` 全部通過
- [ ] `make ci`（lint + typecheck + test）全部通過
- [ ] `AgentsDB().init_db()` 冪等執行（第二次無 error）
- [ ] `control-log stats --since-days 30 --json` 輸出可 `json.loads()` 解析
- [ ] `pr-control-log` skill 可在 yibi-stack worktree 中端對端執行
- [ ] `skills/README.md` 索引已更新

### Traceability Matrix

| US | Gherkin Scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `write-single-entry` | CTL-ST-001 | `CTL-ST-001: entry schema with 11 audit fields` |
| US-001 | `optional-fields-null` | CTL-VL-001 | `CTL-VL-001: optional fields default to NULL` |
| US-001 | `idempotent-db-init` | CTL-DB-001 | `CTL-DB-001: idempotent DB init` |
| US-002 | `calibration-approve` | CTL-ST-002 | `CTL-ST-002: user calibration loop approve` |
| US-002 | `calibration-exceed` | CTL-EG-001 | `CTL-EG-001: calibration loop exceed 3 rounds` |
| US-002 | `artifact-path` | CTL-VL-002 | `CTL-VL-002: markdown artifact output path` |
| US-003 | `stats-normal-output` | CTL-DT-001 | `CTL-DT-001: cross-session statistics normal` |
| US-003 | `stats-json-mode` | CTL-CV-001 | `CTL-CV-001: stats JSON output mode` |
| US-003 | `stats-division-by-zero` | CTL-DT-002 | `CTL-DT-002: autonomy_ratio division by zero` |
| US-003 | `stats-group-by-category` | CTL-DT-003 | `CTL-DT-003: grouping by category` |
| US-004 | `advice-r1-triggers` | CTL-DT-004 | `CTL-DT-004: threshold-based advice R1` |
| US-004 | `advice-no-trigger` | CTL-DT-005 | `CTL-DT-005: advice no rules trigger` |
| US-004 | `advice-insufficient-data` | CTL-EG-002 | `CTL-EG-002: advice insufficient data` |
| — | `smk-write-and-read` | SMK-001 | `SMK-001: smoke write and read entry` |
| — | `smk-stats-advice` | SMK-002 | `SMK-002: smoke stats and advice flow` |

## ADDED Requirements

### Requirement: Trigger evaluation fixture schema

The system SHALL load, per skill, a `trigger_eval.json` fixture located beside that skill's `SKILL.md`. The fixture SHALL contain three prompt classes — `direct`, `indirect`, and `negative` — where each prompt carries an `expect_trigger` boolean. Prompts in the `negative` class SHALL have `expect_trigger` set to `false`; prompts in `direct` and `indirect` SHALL have `expect_trigger` set to `true`. A fixture that violates this schema SHALL be rejected with a validation error, and the system SHALL NOT silently drop malformed prompts.

#### Scenario: valid-fixture-loads -- 合法 fixture 三類皆可載入

**GIVEN** 一份 `trigger_eval.json` 具備格式正確的 `direct` / `indirect` / `negative` 陣列
**WHEN** 系統載入該 fixture
**THEN** 系統 MUST 產生一個可存取全部三類 prompt 的 fixture 物件

#### Scenario: negative-expect-trigger-true-rejected -- negative 標 true 被拒

**GIVEN** 一份 fixture 的某個 `negative` prompt 其 `expect_trigger` 為 `true`
**WHEN** 系統載入該 fixture
**THEN** 系統 MUST 以驗證錯誤失敗並指出違規的類別
  AND 系統 MUST NOT 靜默丟棄該 prompt

### Requirement: Deterministic pass-rate scoring

Given a set of per-prompt verdicts, the system SHALL compute a pass rate for each prompt class independently. For `direct` and `indirect` prompts, a verdict SHALL count as passed when the target skill was judged to trigger. For `negative` prompts, a verdict SHALL count as passed when the target skill was judged NOT to trigger. The scoring step SHALL be deterministic and free of any LLM call.

#### Scenario: negative-not-triggered-passes -- negative 未觸發即通過

**GIVEN** 一個 `negative` prompt
**WHEN** judge 判斷目標 skill「未觸發」
**THEN** 系統 MUST 將該 prompt 計為 passed

##### Example: 逐類 pass rate

| Class    | Prompts | Judged triggered | Passed | Pass rate |
| -------- | ------- | ---------------- | ------ | --------- |
| direct   | 2       | 2                | 2      | 1.0       |
| indirect | 3       | 2                | 2      | 0.67      |
| negative | 2       | 1                | 1      | 0.5       |

### Requirement: Pluggable judge backend

The scoring core SHALL depend only on a Judge interface, not on any concrete LLM client. A Judge backend SHALL expose a step that builds a judgment manifest from the loaded fixtures and a step that maps returned judgments into per-prompt verdicts. The default backend provided by this change SHALL be an agent-driven backend that requires no API key: it SHALL emit the manifest for an external agent session to judge and SHALL accept the returned judgments without performing the judgment itself.

#### Scenario: core-scores-via-interface -- 核心只透過介面計分

**GIVEN** 一個回傳固定 verdict 的 stub Judge
**WHEN** 計分核心以某 fixture 與該 stub Judge 執行評測
**THEN** 系統 MUST 完成計分且 MUST NOT import 或呼叫任何 LLM client

#### Scenario: verdict-count-mismatch-surfaced -- verdict 數不符即中止

**GIVEN** 一個 N 筆任務的 manifest
**WHEN** 回饋的 judgments 數量不等於 N
**THEN** 系統 MUST 抛錯中止
  AND 系統 MUST NOT 補零或截斷

### Requirement: Baseline regression detection

The system SHALL persist a baseline of per-class pass rates per skill, and SHALL compare a current evaluation against that baseline using a configurable tolerance. When any class pass rate falls below its baseline minus the tolerance, the system SHALL report a regression and exit with a non-zero status, listing each regressed skill and class.

#### Scenario: regression-below-tolerance-exits-nonzero -- 低於容忍門檻即回歸

**GIVEN** 某 skill 的 `negative` pass rate 為 0.6、baseline 為 1.0、容忍門檻為 0.1
**WHEN** 系統執行評測比對
**THEN** 系統 MUST 回報該 skill `negative` 類的回歸並以非零狀態結束

#### Scenario: within-tolerance-passes -- 容忍門檻內通過

**GIVEN** 每一類 pass rate 皆不低於其 baseline 減容忍門檻
**WHEN** 系統執行評測比對
**THEN** 系統 MUST 回報無回歸並以零狀態結束

### Requirement: CLI eval and baseline commands

The system SHALL expose a command-line interface registering an `eval` subcommand and a `baseline` subcommand. The `eval` subcommand SHALL run the evaluation and baseline comparison; the `baseline` subcommand SHALL write current pass rates as the new baseline. Both subcommands SHALL appear in the module help output.

#### Scenario: eval-baseline-discoverable -- 兩個 subcommand 可被發現

**GIVEN** 已安裝的 skill_eval 模組
**WHEN** 以 help 旗標呼叫該模組
**THEN** 系統 MUST 在列出的 subcommand 中同時包含 `eval` 與 `baseline`

### Requirement: Missing fixture is surfaced

When an evaluation targets a skill whose `trigger_eval.json` does not exist, the system SHALL surface an explicit failure to standard error and SHALL NOT treat the absence as a passing result.

#### Scenario: absent-fixture-fails-loud -- 缺 fixture 明確失敗

**GIVEN** 一個沒有 `trigger_eval.json` 的目標 skill
**WHEN** `eval` 以該 skill 為目標
**THEN** 系統 MUST 印出指明該 skill 的失敗訊息並以非零狀態結束
  AND 系統 MUST NOT 將缺檔視為通過

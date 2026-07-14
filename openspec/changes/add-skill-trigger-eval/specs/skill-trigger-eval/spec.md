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

The tolerance SHALL be constrained to a finite value in `[0.0, 1.0)`, and the baseline file SHALL be validated on load -- both its pass-rate values (finite, in `[0.0, 1.0]`) and its class keys (a member of direct/indirect/negative). Values or keys outside those domains SHALL fail loudly rather than be treated as "no baseline for this class": every such input reaches the same `base is None` skip that silently disarms the gate for that class, so accepting them turns a corrupt file into a green run.

#### Scenario: tolerance-out-of-domain-rejected -- 容忍門檻值域外即失敗

**GIVEN** `--tolerance` 給定 `nan` 或 `>= 1.0` 的值
**WHEN** `eval` 執行比對
**THEN** 系統 MUST 以非零狀態結束並指明合法值域
  AND 系統 MUST NOT 逕行比對（該門檻會讓回歸偵測恆不觸發，等同關閉 gate）

#### Scenario: corrupt-baseline-rejected -- 損壞的 baseline 即失敗

**GIVEN** 一份 baseline 檔，其某項 pass rate 為 `null`／值域外，或其 class key 非 direct/indirect/negative（如錯字 `negatve`）
**WHEN** `eval` 載入該 baseline
**THEN** 系統 MUST 以非零狀態結束並指明格式錯誤
  AND 系統 MUST NOT 將該項視為「無此類基準」而略過比對

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

### Requirement: Empty fixture is surfaced

When a targeted skill's `trigger_eval.json` exists but contributes no prompts in any class, the system SHALL surface an explicit per-skill failure and SHALL NOT report a vacuous pass — including under `--all`, where one emptied fixture MUST NOT silently drop out of the regression gate.

#### Scenario: empty-fixture-fails-loud -- 空 fixture 明確失敗

**GIVEN** 一個 `trigger_eval.json` 存在但 direct/indirect/negative 三類皆空的 skill
**WHEN** `eval` 以該 skill 為目標（含 `--all` 中夾帶此 skill）
**THEN** 系統 MUST 印出指明該 skill 的失敗訊息並以非零狀態結束
  AND 系統 MUST NOT 回報 `[OK]` 無回歸

### Requirement: Manifest binding guards fixture drift

When a prior `--emit-manifest` output is passed back via `--manifest`, the system SHALL recompute the manifest signature from the current fixtures and SHALL fail loudly when it differs, so judgments produced for a since-changed fixture cannot be scored against misaligned prompts.

#### Scenario: manifest-binding-drift-fails -- fixture 漂移即失敗

**GIVEN** 一份先前 `--emit-manifest` 的 manifest，且其後 fixture 的 prompt 內容已變動
**WHEN** `eval --manifest <該 manifest> --judgments <...>` 或 `baseline --manifest <該 manifest> --judgments <...>` 執行
**THEN** 系統 MUST 偵測簽章不符並以非零狀態結束
  AND 系統 MUST NOT 以錯位的 prompt↔judgment 對算出 pass rate
  AND `baseline` MUST NOT 寫出該 baseline 檔

### Requirement: Manifest binding is required on both judgment-consuming paths

Any command that consumes an index-aligned `--judgments` array SHALL require the corresponding `--manifest`, because judgments cannot exist without a prior `--emit-manifest` and the length check alone cannot detect same-count drift. `eval` MAY expose an explicit opt-out flag so that skipping is a recorded decision rather than the default; `baseline` SHALL NOT, because it persists the reference every subsequent gate compares against and its corruption therefore outlives the run.

#### Scenario: manifest-binding-required -- 缺 manifest 即失敗

**GIVEN** 一份 judgments 檔
**WHEN** `eval --judgments <...>` 或 `baseline --judgments <...>` 未帶 `--manifest` 執行
**THEN** 系統 MUST 以非零狀態結束並指明需提供 `--manifest`
  AND 系統 MUST NOT 逕行計分或寫出 baseline
  AND `eval --judgments <...> --no-manifest-check` MUST 印出 `[WARN]` 後續跑（顯式豁免）

### Requirement: Plugin-only fixtures are surfaced under --all

When `eval --all` enumerates fixtures, the system SHALL warn about `trigger_eval.json` files under `plugins/` that are not reachable through `skills/`, so silently-skipped plugin-only fixtures are visible rather than dropped without notice. The warning SHALL be emitted before any "no fixtures found" failure, so that the case where *every* fixture is plugin-only -- the maximal instance of the silent drop this requirement targets -- is the one it covers rather than the one it misses.

#### Scenario: orphan-plugin-fixture-warned -- plugin-only fixture 顯式警告

**GIVEN** 一個位於 `plugins/` 底下、未經 `skills/` 第一層觸及的 `trigger_eval.json`
**WHEN** `eval --all` 列舉 fixture（含 `skills/` 完全無 fixture 的情況）
**THEN** 系統 MUST 於 stderr 印出 `[WARN]` 並列出該未涵蓋的 fixture
  AND 系統 MUST NOT 靜默地將其排除在評測範圍外
  AND 即使隨後因 `skills/` 無 fixture 而 `[FAIL]`，該 `[WARN]` MUST 仍先被印出

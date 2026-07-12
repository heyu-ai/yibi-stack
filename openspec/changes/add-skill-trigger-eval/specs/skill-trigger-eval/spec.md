## ADDED Requirements

### Requirement: Trigger evaluation fixture schema

The system SHALL load, per skill, a `trigger_eval.json` fixture located beside that skill's `SKILL.md`. The fixture SHALL contain three prompt classes — `direct`, `indirect`, and `negative` — where each prompt carries an `expect_trigger` boolean. Prompts in the `negative` class SHALL have `expect_trigger` set to `false`; prompts in `direct` and `indirect` SHALL have `expect_trigger` set to `true`. A fixture that violates this schema SHALL be rejected with a validation error, and the system SHALL NOT silently drop malformed prompts.

#### Scenario: Valid fixture loads

- **WHEN** a `trigger_eval.json` with well-formed `direct`, `indirect`, and `negative` arrays is loaded
- **THEN** the system produces a fixture object exposing all three prompt classes

#### Scenario: Negative prompt with expect_trigger true is rejected

- **WHEN** a fixture contains a `negative` prompt whose `expect_trigger` is `true`
- **THEN** loading fails with a validation error naming the offending class

### Requirement: Deterministic pass-rate scoring

Given a set of per-prompt verdicts, the system SHALL compute a pass rate for each prompt class independently. For `direct` and `indirect` prompts, a verdict SHALL count as passed when the target skill was judged to trigger. For `negative` prompts, a verdict SHALL count as passed when the target skill was judged NOT to trigger. The scoring step SHALL be deterministic and free of any LLM call.

#### Scenario: Negative prompt passes when not triggered

- **WHEN** a `negative` prompt receives a verdict of "not triggered"
- **THEN** that prompt is counted as passed

##### Example: Per-class pass rate

| Class    | Prompts | Judged triggered | Passed | Pass rate |
| -------- | ------- | ---------------- | ------ | --------- |
| direct   | 2       | 2                | 2      | 1.0       |
| indirect | 3       | 2                | 2      | 0.67      |
| negative | 2       | 1                | 1      | 0.5       |

### Requirement: Pluggable judge backend

The scoring core SHALL depend only on a Judge interface, not on any concrete LLM client. A Judge backend SHALL expose a step that builds a judgment manifest from the loaded fixtures and a step that maps returned judgments into per-prompt verdicts. The default backend provided by this change SHALL be an agent-driven backend that requires no API key: it SHALL emit the manifest for an external agent session to judge and SHALL accept the returned judgments without performing the judgment itself.

#### Scenario: Core scores through the interface

- **WHEN** the scoring core is invoked with a fixture and a stub Judge that returns fixed verdicts
- **THEN** the core computes results without importing or calling any LLM client

#### Scenario: Verdict count mismatch is surfaced

- **WHEN** the number of returned judgments does not match the manifest size
- **THEN** the backend raises an error rather than padding or truncating silently

### Requirement: Baseline regression detection

The system SHALL persist a baseline of per-class pass rates per skill, and SHALL compare a current evaluation against that baseline using a configurable tolerance. When any class pass rate falls below its baseline minus the tolerance, the system SHALL report a regression and exit with a non-zero status, listing each regressed skill and class.

#### Scenario: Regression below tolerance exits non-zero

- **WHEN** a skill's `negative` pass rate is 0.6, its baseline is 1.0, and the tolerance is 0.1
- **THEN** the evaluation reports a regression for that skill's `negative` class and exits non-zero

#### Scenario: Within tolerance passes

- **WHEN** every class pass rate is at or above its baseline minus the tolerance
- **THEN** the evaluation reports no regression and exits zero

### Requirement: CLI eval and baseline commands

The system SHALL expose a command-line interface registering an `eval` subcommand and a `baseline` subcommand. The `eval` subcommand SHALL run the evaluation and baseline comparison; the `baseline` subcommand SHALL write current pass rates as the new baseline. Both subcommands SHALL appear in the module help output.

#### Scenario: Subcommands are discoverable

- **WHEN** the module is invoked with the help flag
- **THEN** both `eval` and `baseline` appear in the listed subcommands

### Requirement: Missing fixture is surfaced

When an evaluation targets a skill whose `trigger_eval.json` does not exist, the system SHALL surface an explicit failure to standard error and SHALL NOT treat the absence as a passing result.

#### Scenario: Absent fixture fails loudly

- **WHEN** `eval` targets a skill that has no `trigger_eval.json`
- **THEN** the system prints a failure message identifying the skill and exits non-zero

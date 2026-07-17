## ADDED Requirements

### Requirement: Blocking findings require executable evidence

US-001 / AC-001-1. A finding SHALL block merge only when it carries an `Evidence:` field holding a command the lead can execute inside the review worktree that exhibits the defect. A finding without valid evidence SHALL NOT block merge; it SHALL be demoted, and SHALL remain in the aggregated output with its demotion reason stated.

Reviewers SHALL supply the evidence. The lead SHALL NOT construct evidence on a reviewer's behalf.

#### Scenario: evidence-present-blocks -- Critical 附可執行證據時擋 merge

**GIVEN** a reviewer voice has produced an R1 review
**WHEN** the voice reports a Critical finding whose `Evidence:` field holds a command that exhibits the defect
**THEN** the aggregator MUST place the finding in the blocking set
  AND the aggregator MUST NOT authorize merge while that finding is unresolved

#### Scenario: evidence-absent-demoted -- 無證據欄位者降級

**GIVEN** a reviewer voice has produced an R1 review
**WHEN** the voice reports a Critical finding with no `Evidence:` field
**THEN** the aggregator MUST demote the finding to the deferred set
  AND the aggregator MUST state that the demotion reason is absent evidence
  AND the aggregator MUST NOT place the finding in the blocking set

#### Scenario: demoted-stays-visible -- 降級不等於消失

**GIVEN** a finding has been demoted for lack of evidence
**WHEN** the aggregator emits its output
**THEN** the output MUST contain the finding's original title and description in the deferred section
  AND the aggregator MUST NOT silently discard the finding

### Requirement: Evidence forms are enumerated by finding type

US-001 / AC-001-2. The reviewer prompt SHALL enumerate a closed list of acceptable evidence forms per finding type. A finding type absent from that list SHALL have no acceptable evidence form and SHALL therefore always be demoted.

For logic and security defects the acceptable form SHALL be a concrete failure scenario — input value, expected output, and actual output — rather than a runnable command, because reviewers observe only the diff and SHALL NOT explore the repository. The lead SHALL convert a failure scenario into a runnable command.

#### Scenario: doc-error-evidence -- doc 事實錯誤以指令證明

**GIVEN** a reviewer reports that a document cites a path that does not exist
**WHEN** the reviewer supplies `Evidence:` containing a command that tests for that path
**THEN** the aggregator MUST accept the evidence form as valid for the doc-factual-error type

#### Scenario: logic-bug-failure-scenario -- logic bug 收 failure scenario 而非指令

**GIVEN** a reviewer reports a logic defect and observes only the diff
**WHEN** the reviewer supplies `Evidence:` containing input value, expected output, and actual output
**THEN** the aggregator MUST accept the evidence form as valid for the logic-defect type
  AND the aggregator MUST NOT require a runnable command from the reviewer for this type

##### Example: evidence forms by finding type

| Finding type | Acceptable evidence form | Blocking possible |
| ------------ | ------------------------ | ----------------- |
| Logic or security defect | concrete failure scenario: input, expected output, actual output | yes |
| Test gap | a surviving mutation: name the production line to break; tests stay green | yes |
| Doc factual error | a command proving the error: path absent, example exits non-zero, cited file:line mismatched, claim contradicts code | yes |
| Naming or structure inconsistency | grep output showing at least 2 siblings using the other convention | yes |
| Precision, potential misleading, suggested addition | none prescribed | no — always demoted |

#### Scenario: precision-finding-always-demoted -- 精確度類永遠降級

**GIVEN** the evidence table prescribes no acceptable form for the precision type
**WHEN** a reviewer reports that prose is imprecise, potentially misleading, or would benefit from a counter-example
**THEN** the aggregator MUST demote the finding regardless of any `Evidence:` content supplied
  AND the aggregator MUST NOT place the finding in the blocking set

### Requirement: Evidence verification is tiered by severity

US-001 / AC-001-3. The lead SHALL execute the evidence of every Critical finding. The lead SHALL NOT be required to execute the evidence of an Important finding. A finding whose `Evidence:` field is absent or malformed SHALL be demoted by structural inspection alone, without executing anything.

Execution SHALL yield exactly one of three outcomes: **reproduced**, **not reproduced**, or **invalid**. An invalid outcome — the command or scenario cannot be executed at all — SHALL NOT be treated as not reproduced.

#### Scenario: critical-evidence-reproduced -- 重現則留在 blocking

**GIVEN** a Critical finding carries evidence
**WHEN** the lead executes the evidence and the defect is exhibited
**THEN** the aggregator MUST keep the finding in the blocking set

#### Scenario: critical-evidence-not-reproduced -- 未重現則移除並記錄

**GIVEN** a Critical finding carries evidence
**WHEN** the lead executes the evidence and the defect is not exhibited
**THEN** the aggregator MUST remove the finding from the blocking set
  AND the aggregator MUST record that the evidence did not reproduce

#### Scenario: critical-evidence-invalid -- 無效證據降為 Important 而非 drop

**GIVEN** a Critical finding carries evidence naming a test, path, or harness that does not exist
**WHEN** the lead attempts to execute the evidence and it cannot run at all
**THEN** the lead MUST attempt to repair the evidence once
  AND if repair fails the aggregator MUST demote the finding to Important in the deferred set
  AND the aggregator MUST NOT drop the finding
  AND the aggregator MUST NOT record the outcome as not reproduced

##### Example: three execution outcomes

| Execution result | Meaning | Disposition |
| ---------------- | ------- | ----------- |
| command ran, defect exhibited | reviewer was right | stays blocking |
| command ran, defect absent | reviewer was wrong | dropped from blocking, recorded |
| command could not run at all | evidence invalid, defect status unknown | repair once; else demote to Important in deferred — never dropped |

#### Scenario: malformed-evidence-no-execution -- 結構檢查零成本降級

**GIVEN** a finding's `Evidence:` field is present but holds no executable command or failure scenario
**WHEN** the aggregator inspects the finding
**THEN** the aggregator MUST demote the finding by structural inspection
  AND the lead MUST NOT execute anything for that finding

### Requirement: Review surface is bounded to two rounds

US-002 / AC-002-1. The review loop SHALL admit at most two rounds. Round 1 SHALL review the complete diff and SHALL record the head SHA as the Round 2 baseline. Round 2 SHALL review the commit range after that baseline, together with confirmation that Round 1's blocking findings are resolved. A third round SHALL NOT exist.

Termination SHALL depend only on the round cap, and SHALL NOT depend on the Round 2 surface being smaller than Round 1's.

#### Scenario: round2-surface-is-fix-delta -- Round 2 只審 fix delta

**GIVEN** Round 1 concluded and recorded a baseline head SHA
**WHEN** Round 2 begins after fixes are pushed
**THEN** the review surface MUST be the commit range from the baseline SHA to the current head
  AND the review surface MUST NOT be the complete PR diff

#### Scenario: round2-important-demoted -- Round 2 的 Important 降級

**GIVEN** Round 2 is under way
**WHEN** a reviewer reports an Important finding
**THEN** the aggregator MUST demote the finding to the deferred set
  AND the aggregator MUST NOT place the finding in the blocking set

#### Scenario: round2-empty-blocking-merges -- Round 2 收斂則 merge

**GIVEN** Round 2 has concluded
**WHEN** the blocking set is empty
**THEN** the workflow MUST proceed to merge
  AND the workflow MUST NOT begin a third review round

#### Scenario: round2-unresolved-critical-adjudicated -- Round 2 未解 Critical 轉人類

**GIVEN** Round 2 has concluded
**WHEN** the blocking set holds at least one Critical finding
**THEN** the workflow MUST enter the circuit breaker and present its options for human adjudication
  AND the workflow MUST NOT begin a third review round automatically

##### Example: rounds, surface, and blocking severities

| Round | Surface (commit range) | Blocking severities | Next state when blocking set empties |
| ----- | ---------------------- | ------------------- | ------------------------------------ |
| 1 | `base..baseline` (complete diff) | Critical, Important — both evidenced | Round 2 when fixes were pushed, else merge |
| 2 | `baseline..HEAD` (fix delta; disjoint from Round 1, not a subset, size not guaranteed smaller) | Critical only, evidenced | merge |
| 3 | does not exist | — | — |

### Requirement: Actionable NIT never blocks merge

US-002 / AC-002-2. An Actionable NIT SHALL NOT block merge in any round. The lead SHALL be free to apply a trivial NIT fix within a round, and doing so SHALL NOT make the NIT a merge gate. The skill document SHALL NOT carry a convention requiring every actionable NIT to be cleared before merge.

#### Scenario: nit-present-at-merge -- NIT 未清仍可 merge

**GIVEN** the blocking set is empty
**WHEN** unresolved Actionable NIT findings exist
**THEN** the workflow MUST proceed to merge

#### Scenario: nit-convention-absent -- 約定句已從文件移除

**GIVEN** the skill document is inspected for a convention requiring every actionable NIT to be cleared before merge
**WHEN** the document is searched by string content rather than by line number
**THEN** no such convention MUST be present

### Requirement: Demoted findings have a defined destination

US-003 / AC-003-1. Demoted Important findings SHALL be recorded in one batched GitHub issue per pull request, labelled `deferred-from-review`. Demoted Actionable NIT findings SHALL NOT create an issue and SHALL rely on the review summary already posted as a pull request comment.

At most one issue SHALL be created per pull request regardless of how many Important findings were demoted.

#### Scenario: many-important-one-issue -- 多筆降級 Important 只開一張票

**GIVEN** the review loop has ended with three demoted Important findings
**WHEN** the deferral batch is routed
**THEN** exactly one issue MUST be created
  AND the issue MUST carry the `deferred-from-review` label
  AND the issue MUST list all three findings

#### Scenario: nit-only-no-issue -- 只有 NIT 降級則不開票

**GIVEN** the review loop has ended with demoted Actionable NIT findings and no demoted Important findings
**WHEN** the deferral batch is routed
**THEN** no issue MUST be created

#### Scenario: no-demotions-no-issue -- 無降級則不開票

**GIVEN** the review loop has ended with no demoted findings
**WHEN** the deferral batch is routed
**THEN** no issue MUST be created

### Requirement: Skill document line budget

US-003 / AC-003-2. The `pr-cycle-deep` skill document SHALL NOT exceed 1220 lines, its count immediately before this change. A mechanical check SHALL enforce the budget.

The mechanical check SHALL anchor on string content rather than line numbers. When an anchor string is absent, the check SHALL fail loudly rather than pass silently.

#### Scenario: line-budget-enforced -- 超出預算即失敗

**GIVEN** the mechanical check is run
**WHEN** the skill document holds 1221 lines or more
**THEN** the check MUST fail
  AND the failure message MUST state the actual line count and the budget

#### Scenario: anchor-absent-fails-loud -- 錨點失效必須紅燈

**GIVEN** the mechanical check searches for a required anchor string
**WHEN** the anchor string is absent from the document
**THEN** the check MUST fail
  AND the check MUST NOT report success on the grounds that nothing was found to inspect

##### Example: mechanical check outcomes

| Condition | Check result |
| --------- | ------------ |
| 1220 lines, every anchor found | pass |
| 1221 lines | fail: line budget exceeded |
| 900 lines, NIT-blocking convention string still present | fail: removal not applied |
| 900 lines, `Evidence:` anchor absent from the prompt spec | fail: anchor absent, verification inconclusive |

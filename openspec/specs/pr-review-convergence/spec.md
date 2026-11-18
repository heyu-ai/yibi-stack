# pr-review-convergence Specification

<!-- @trace-sidecar: spec.trace.yaml -->

## Purpose

TBD - created by archiving change 'bound-review-loop-with-evidence-gate'. Update Purpose after archive.

## Requirements

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

---
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

---
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

---
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

---
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

---
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

---

---
### Requirement: Skill document contract validation

The skill document SHOULD remain focused, but a historical total line count MUST NOT be used as
proof of review correctness. Changes to executable review helpers SHALL be verified through their
observable admission, isolation, error and lifecycle behavior rather than source-string or fixed
line-count assertions.

Existing document-contract checks SHALL anchor on required content rather than line numbers.
When a required anchor is absent, a retained document check SHALL fail loudly rather than pass
silently. Passing such a check SHALL mean document conformance only, not that an agent obeyed it.

#### Scenario: fixed line ceiling is not a correctness gate

- **GIVEN** a runbook update describes newly implemented isolation and finding admission behavior
- **WHEN** its total line count exceeds an old snapshot's count
- **THEN** that count alone MUST NOT fail a correctness check
- **AND** observable behavior regressions MUST still fail their regression checks

#### Scenario: anchor-absent-fails-loud -- 錨點失效必須紅燈

- **GIVEN** a retained document check searches for a required anchor string
- **WHEN** the anchor string is absent from the document
- **THEN** the check MUST fail
- **AND** it MUST NOT report success because nothing was found to inspect

##### Example: document check outcomes

| Condition | Check result |
| --- | --- |
| Empty document | fail: required content absent |
| Required Evidence anchor absent | fail: anchor absent, verification inconclusive |
| Required content present with different line wrapping | no fixed-line-count failure |

### Requirement: Draft readiness requires explicit human approval

The pre-merge gate SHALL read live PR state and a boolean isDraft before version bump or merge.
An OPEN draft PR SHALL stop even when mergeable is MERGEABLE and mergeStateStatus is CLEAN.
Prior ship approval SHALL NOT authorize marking a draft ready. Only explicit human approval
SHALL permit gh pr ready, followed by another live gate read confirming isDraft=false.
API failure, missing metadata, non-boolean isDraft, or non-enumerated mergeable/mergeStateStatus SHALL stop rather than infer readiness. Valid UNKNOWN SHALL retain the documented CI/approval routing, not become a metadata error.

#### Scenario: draft-clean-stops -- CLEAN draft still blocks

- **GIVEN** an OPEN PR with isDraft=true and mergeStateStatus=CLEAN
- **WHEN** the pre-merge gate executes
- **THEN** it MUST stop for human approval and MUST NOT mark ready or merge.

#### Scenario: ready-rechecked -- Approval does not replace readback

- **GIVEN** explicit approval to mark a draft ready
- **WHEN** gh pr ready succeeds but live readback still has isDraft=true
- **THEN** the gate MUST remain blocked until a live read confirms isDraft=false.

### Requirement: Early checkpoints retain safe resume boundaries

Before Step 1.5, the workflow SHALL atomically create schema_version=1 JSON state.md binding
canonical PR URL/repository, PR number, base, head and next=Step 1.5. Every action SHALL verify
the live canonical identity. Legacy free-format checkpoints SHALL fail closed with restart guidance.
Only bounded public transitions SHALL save progress; failed transitions SHALL leave prior bytes
unchanged. Resume SHALL reject changed live/checkout heads even when they move together.
Before Step 2 it SHALL NOT require red-first/final reports. From Step 2 it SHALL retain and validate
the original red-first capture, including unchanged bytes and unchecked distinct from pass.
Late checkpoint, baseline, human ruling, CI configuration and CI completion SHALL use atomic
validated interfaces, not handwritten state. Missing/stale current final or unresolved disputes
SHALL route to Step 5, never final.prev.md. Canonical final identity and fingerprint SHALL bind the
current pass and voice decisions. A legal fast-forward post-fix transition SHALL preserve baseline,
disputes and reviewed_head, record the new current head as unreviewed, and route only to Step 7.
Dispute IDs SHALL identify the same finding content; conflicting reuse SHALL be rejected without
changing state. Human rulings SHALL record their bounded pass. Re-checkpointing SHALL retain
blocking for a fix ruling from the current pass, even if the aggregation input has blocking=false;
retained fix history from an earlier pass SHALL NOT automatically block a newly reviewed pass.
Only pass 1 post-fix SHALL start pass 2 at Step 2; all prior voice approvals SHALL be invalidated.
There SHALL be no third pass or start-based reset of pass 2. MERGED resume SHALL route read-only
to Step 11 even after squash changes checkout HEAD; CLOSED SHALL stop. Neither terminal state
SHALL admit start, advance or voice mutation, push or merge. Read-only reviews SHALL never write state.md.

#### Scenario: resume-before-red-first -- Early interruption has no final yet

- **GIVEN** Step 1.6 completed and next=Step 1.7 was saved
- **WHEN** a new session resumes with the same PR, base and head and no final.md or red-first.md
- **THEN** resume MUST return Step 1.7 without restarting Step 1.5.

#### Scenario: resume-stale-head -- Checkpoint cannot adopt new commits

- **GIVEN** a saved checkpoint and a changed live PR head or checkout HEAD
- **WHEN** resume executes
- **THEN** it MUST fail without rewriting the checkpoint.

### Requirement: Runtime voice exhaustion requires a human decision

Static auth detection SHALL NOT certify runtime availability. Before dispatch or explicit retry,
begin-attempt SHALL invalidate prior outcomes/approval while preserving unavailable reason history.
Each outcome source SHALL bind canonical PR URL, head, bounded pass, debate phase and fresh attempt.
Success SHALL require a newly produced canonical voice report whose creation marker AND body scope
carry this identity, plus its complete-byte fingerprint. Old reports SHALL NOT be restamped as success.
Identity and scope metadata SHALL NOT satisfy substantive report completeness. R1 reports SHALL
contain nonempty Summary, Findings and Verdict sections in order. R2 reports SHALL contain nonempty
Cross-review verdict, Per-finding response, New findings, Withdrawals and Final verdict sections in
order. The terminal verdict SHALL select LGTM or NEEDS_CHANGES. Metadata-only, truncated, or
code/comment-quoted reports SHALL be rejected without publishing a successful decision.
Consumers SHALL revalidate source identity/digest, report fingerprints and matching durable publication;
cached active_voices or partial publication SHALL never certify success. After R1 only verified
current-pass successes determine mode. With zero external R1 successes the workflow SHALL stop
for explicit current-outcome Claude-only approval, switching workflow or a later retry; silence SHALL
NOT authorize continuation. Approval SHALL NOT carry across changed head/pass/attempt/outcomes/reports.
R2 SHALL select only valid R1 active voices and disclose its own unavailable reasons separately;
R2 failure SHALL NOT retroactively remove valid R1 participation or claim all R1 voices debated.
Final, human summary and Jira SHALL preserve actual mode and stage/pass-specific failure history.
Read-only reviews SHALL use the same attempt/publication/verification contract without lifecycle state;
their bounded pass stays 1, distinct from conditional R2 debate.

#### Scenario: external-exhaustion-stops -- Quota and 502 failures are not mob review

- **GIVEN** Claude succeeded, Codex hit its usage limit and Gemini failed with HTTP 502
- **WHEN** R1 availability is recorded without a human continuation decision
- **THEN** the workflow MUST report Claude-only, retain both failure reasons, and stop.

#### Scenario: continuation-is-pass-local -- Prior approval cannot waive a later outage

- **GIVEN** explicit Claude-only approval for pass 1
- **WHEN** pass 2 also has no external successful voice
- **THEN** the workflow MUST ask for a new decision rather than reuse pass 1 approval.

#### Scenario: dispute-id-collision -- A new finding cannot inherit old acceptance

- **GIVEN** finding A with id C1 has a human false-positive ruling
- **WHEN** a later checkpoint submits a different finding B with id C1 and no ruling
- **THEN** checkpoint MUST reject the conflicting identity without changing the prior state.

#### Scenario: current-fix-still-blocks -- Re-checkpoint preserves the human fix directive

- **GIVEN** a human ruled that a current-pass finding must be fixed
- **WHEN** checkpoint is repeated with the original aggregation input declaring blocking=false
- **THEN** effective blocking MUST remain true until a fresh reviewed pass resolves the finding.

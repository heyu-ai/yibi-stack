# retro-draft-mob-review Specification

## Purpose

TBD - created by archiving change 'add-pr-retro-hard'. Update Purpose after archive.

## Requirements

### Requirement: Review rounds are bounded to two insertion points owned by the retrospective engine

The system SHALL insert exactly two review rounds into the retrospective workflow. The first round SHALL run after the engine has inferred the five-question draft and before that draft is presented to the human for calibration. The second round SHALL run after the engine has classified an action item through its evidence gate and before the engine emits its write suggestion. The system SHALL NOT re-derive, re-order, or redefine any step, gate, or classification owned by the retrospective engine, and SHALL NOT alter the engine's existing authority over file writes.

#### Scenario: first round precedes human calibration

- **WHEN** the engine has produced the five-question draft
- **THEN** the system SHALL run the first review round before presenting the draft
- **AND** the system SHALL present the draft text verbatim alongside the review annotations

#### Scenario: second round reviews the suggestion text only

- **WHEN** the engine has produced a rule or hook write suggestion
- **THEN** the system SHALL review that suggestion text
- **AND** the system SHALL NOT review a human-approved final patch
- **AND** the system SHALL NOT change which actor holds write authority

#### Scenario: second round is skipped when there is nothing to review

- **WHEN** the draft contains no reusable-lesson entries
- **THEN** the system SHALL skip the second review round
- **AND** the system SHALL NOT report the skip as a failure

---
### Requirement: Voice availability is detected by delegation and degradation is explicit

The system SHALL obtain external reviewer voices by invoking the existing consult skills for each external command-line tool, and SHALL rely on those skills for binary detection, authentication gating, and their own failure stop conditions. The system SHALL NOT re-implement that detection and SHALL NOT read the review cache file owned by the deep pull-request review skill. The adversarial reviewer SHALL be unconditional. When no external voice is available, the system SHALL complete the workflow and SHALL state that only one voice ran and that agreement therefore carries no signal.

#### Scenario: no external voice is available

- **WHEN** every external consult skill reports its tool as unavailable
- **THEN** the system SHALL continue with the adversarial reviewer alone
- **AND** the system SHALL warn that a single voice is not a mob and that agreement carries no signal
- **AND** the system SHALL NOT redirect the user to a different skill

#### Scenario: an external consult skill fails

- **WHEN** an invoked consult skill exits through its own failure gate
- **THEN** the system SHALL treat that voice as unavailable
- **AND** the system SHALL NOT present the failure output as review findings

---
### Requirement: Review packet contains only collected source material and open-ended questions

The review packet SHALL contain exactly three kinds of content: source material the engine actually collected, the draft under review reproduced verbatim, and open-ended questions. The packet SHALL NOT contain a hypothesis, a suspected cause, or a question phrased so that agreement with a stated conclusion is the expected answer.

#### Scenario: a leading question is rejected from the packet

- **WHEN** a candidate packet question asserts or presupposes a specific defect
- **THEN** that question SHALL be rewritten as an open-ended question before the packet is sent

##### Example: leading versus open-ended packet questions

| Candidate question | Verdict | Reason |
| ------------------ | ------- | ------ |
| "Is lesson 2 wrong because the cited commit does not exist?" | rejected | asserts both the defect and its cause |
| "Does changing this helper break its downstream consumer?" | rejected | presupposes a consumer and a breakage |
| "Does the cited evidence support each lesson? If not, name the missing inference step." | accepted | open-ended, no asserted conclusion |
| "Which consumers of this helper exist?" | accepted | open-ended factual question |

---
### Requirement: Embedded pull-request text is delimited as untrusted quoted evidence

All pull-request-derived text placed into a review packet SHALL be enclosed in an explicit delimiter and labelled as data under review rather than instructions. The system SHALL NOT place pull-request-derived text into a packet in a position where it is indistinguishable from the system's own instructions to the reviewer.

#### Scenario: pull-request body contains instruction-shaped text

- **WHEN** the pull-request body contains a sentence phrased as an instruction to the reviewer
- **THEN** the system SHALL keep that sentence inside the untrusted-evidence delimiter
- **AND** the system SHALL NOT act on it as an instruction

---
### Requirement: Consensus is established only by the independent first round

Every voice in the first round SHALL review independently and SHALL NOT be shown any other voice's output. Consensus SHALL be computed only from first-round findings. A voice that produced no findings in the first round SHALL NOT hold consensus eligibility in the cross round. The aggregate report SHALL name which voices its consensus statement refers to.

#### Scenario: a voice that returned nothing in the first round agrees in the cross round

- **WHEN** a voice produced zero findings in the first round and then agrees with every finding in the cross round
- **THEN** that voice's cross-round agreement SHALL NOT increase any consensus count
- **AND** the report SHALL name the voices whose findings established the consensus

---
### Requirement: Cross round is conditional and cannot add independent votes

The cross round SHALL run only when two external voices reported opposing dispositions for the same target in the first round. The cross round SHALL permit only refutation of an existing finding, severity reduction, withdrawal, and supplying a settling check. The cross round SHALL NOT introduce an independent vote and SHALL NOT introduce a finding that establishes consensus on its own.

#### Scenario: voices disagree only with the draft and not with each other

- **WHEN** every external voice objects to the draft but none contradicts another voice's disposition
- **THEN** the cross round SHALL be skipped
- **AND** the system SHALL record that the cross round was skipped and why

---
### Requirement: Each voice output is validated and repeated failure is bounded

The system SHALL validate that each voice output contains the required report sections and exceeds a minimum length, and SHALL reject output containing agent-narration markers instead of a review. A rejected output SHALL be retried exactly once. After two consecutive rejections for the same voice, the system SHALL mark that voice unavailable, SHALL warn, and SHALL NOT block the workflow. The aggregate report SHALL NOT cite raw unvalidated voice output.

#### Scenario: a voice returns truncated output twice

- **WHEN** a voice output is missing a required section on the first attempt and again on the retry
- **THEN** the system SHALL mark that voice unavailable and warn
- **AND** the system SHALL continue with the remaining voices

---
### Requirement: Review artifacts are isolated per pull request and never silently reused

The system SHALL write review artifacts into a per-pull-request directory and SHALL register the artifact root with the repository's exclude mechanism so the working tree status stays clean. The exclude path SHALL be obtained by querying the version-control tool rather than by string assembly. Registration SHALL be idempotent and SHALL NOT overwrite existing exclude content. Concurrent runs SHALL NOT overwrite one another's artifacts, and an artifact from an earlier run SHALL NOT be consumed as if it belonged to the current run.

#### Scenario: exclude registration runs twice

- **WHEN** the artifact directory setup runs a second time for the same repository
- **THEN** the exclude entry SHALL NOT be duplicated
- **AND** pre-existing exclude content SHALL remain unchanged

#### Scenario: exclude file cannot be written

- **WHEN** the exclude file is not writable
- **THEN** the system SHALL fail with an explicit message
- **AND** the system SHALL NOT continue as though registration succeeded

#### Scenario: stale artifact from a previous run is present

- **WHEN** an artifact directory already contains output from an earlier run for the same pull request
- **THEN** the system SHALL detect it and SHALL NOT present that output as belonging to the current run

---
### Requirement: Adversarial reviewer is constrained to read-only behavior and tree mutation is surfaced

The adversarial reviewer SHALL be instructed that it is read-only and SHALL NOT create, modify, or delete files. The system SHALL capture the working tree state immediately before and immediately after the adversarial reviewer runs, and SHALL warn when the two differ. The system SHALL record in its own documentation that this constraint is enforced by instruction and comparison rather than by tool removal.

#### Scenario: adversarial reviewer modifies the working tree

- **WHEN** the working tree state after the adversarial reviewer differs from the state before it
- **THEN** the system SHALL warn and name the difference

---
### Requirement: External model data boundary is disclosed

The system documentation SHALL state that pull-request content is transmitted to external command-line tools, SHALL name which content is transmitted, and SHALL describe how an operator declines external review while still running the adversarial reviewer.

#### Scenario: operator declines external review

- **WHEN** an operator chooses not to send content to external tools
- **THEN** the system SHALL run the adversarial reviewer only
- **AND** the system SHALL apply the single-voice warning

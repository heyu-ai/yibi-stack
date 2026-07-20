## ADDED Requirements

### Requirement: Deep review requires a confirmed Review Contract

The workflow SHALL obtain human confirmation of a Review Contract before any Round 1 defect review starts. The contract SHALL contain Goal, Non-goals, Accepted Residual Risks, Acceptance Criteria, and Follow-ups sections. An existing pull request without the complete structure SHALL receive a generated draft for confirmation.

#### Scenario: Complete contract starts review

- **WHEN** all five sections are present and a human confirms the contract
- **THEN** the workflow SHALL freeze that contract snapshot and start Round 1

#### Scenario: Missing contract section blocks reviewer launch

- **WHEN** Goal, Non-goals, Accepted Residual Risks, Acceptance Criteria, or Follow-ups is absent
- **THEN** the workflow SHALL identify every missing section and SHALL NOT start Round 1

### Requirement: Blocking findings map to a closed set of merge-gate sources

Every pull-request-specific blocking finding SHALL contain a Contract mapping that identifies an Acceptance Criterion, a repository hard baseline reference, or an unaccepted material risk. The finding SHALL also pass the existing Evidence gate. A reviewer SHALL NOT create a new Acceptance Criterion or expand Goal scope without human approval.

#### Scenario: Acceptance Criterion violation can block

- **WHEN** an evidenced finding maps to AC-2 and demonstrates that AC-2 is not satisfied
- **THEN** the aggregator SHALL place the finding in the blocking set

#### Scenario: Missing mapping is non-blocking

- **WHEN** a finding has no valid Contract mapping
- **THEN** the aggregator SHALL preserve the finding with a demotion reason and SHALL NOT place it in the blocking set

#### Scenario: Repository baseline remains enforceable

- **WHEN** an evidenced finding maps to a located repository security or data-integrity baseline
- **THEN** the aggregator SHALL keep the finding eligible to block regardless of the PR Non-goals or Accepted Residual Risks text

### Requirement: Scope exclusions and deferrals do not become merge gates

A finding wholly contained by Non-goals, an accepted residual-risk boundary, or Follow-ups SHALL NOT block merge. Follow-ups SHALL remain non-blocking unless a human materially amends the frozen contract to promote the work into Goal or Acceptance Criteria.

#### Scenario: Non-goal suggestion is deferred

- **WHEN** a reviewer proposes behavior explicitly listed under Non-goals and no repository hard baseline is violated
- **THEN** the aggregator SHALL classify the proposal as non-blocking and preserve the scope reason

#### Scenario: Follow-up does not block

- **WHEN** a reviewer repeats hardening work already listed under Follow-ups
- **THEN** the workflow SHALL NOT require that work for LGTM

### Requirement: Residual-risk acceptance belongs to a human

Every accepted residual risk SHALL identify its failure mode and impact, accepted boundary, mitigation, detection and recovery procedure, and human acceptor. A review voice or lead SHALL NOT accept risk on behalf of a human. A residual risk without a human acceptor SHALL remain unaccepted.

#### Scenario: Risk inside accepted boundary is non-blocking

- **WHEN** an evidenced failure mode remains inside the documented boundary and the risk contains every required field plus a human acceptor
- **THEN** the aggregator SHALL preserve the risk as accepted and SHALL NOT place it in the blocking set

#### Scenario: Missing acceptor leaves risk unaccepted

- **WHEN** Accepted by is absent from a residual-risk entry
- **THEN** the aggregator SHALL treat the entry as an unaccepted risk

### Requirement: LGTM depends on contract compliance and the blocking set

The aggregator SHALL authorize LGTM only when Acceptance Criteria have verification evidence, no unauthorized scope drift remains, material risks are fixed or accepted within their boundaries, and the Evidence-gated blocking set is empty. An individual voice verdict SHALL NOT veto LGTM when that voice reports only non-blocking findings.

#### Scenario: Non-blocking NEEDS_CHANGES does not veto merge

- **WHEN** one voice returns NEEDS_CHANGES containing only an Actionable NIT and a Follow-up suggestion while the blocking set is empty
- **THEN** the aggregator SHALL authorize LGTM

#### Scenario: Blocking set prevents LGTM

- **WHEN** one evidenced Critical finding mapped to an Acceptance Criterion remains unresolved
- **THEN** the aggregator SHALL NOT authorize LGTM

### Requirement: Cross-debate Round 2 is conditional

All active voices SHALL execute independent Round 1 review. The workflow SHALL execute cross-debate Round 2 only when the preliminary contract mapping and Evidence structure check produces at least one candidate blocking finding or a disagreement about a finding's blocking source, severity, or disposition.

#### Scenario: Clean Round 1 skips cross-debate

- **WHEN** Round 1 produces no candidate blocking finding and no blocking disagreement
- **THEN** the workflow SHALL output `R2 skipped: no contract-blocking candidate or dispute` and proceed to aggregation without cross-debate

#### Scenario: Candidate blocker activates cross-debate

- **WHEN** Round 1 contains an evidenced Important finding mapped to AC-3
- **THEN** the workflow SHALL execute cross-debate Round 2

#### Scenario: Blocking disagreement activates cross-debate

- **WHEN** two voices disagree whether the same finding violates a repository hard baseline
- **THEN** the workflow SHALL execute cross-debate Round 2

### Requirement: Contract amendments preserve review integrity

A material amendment SHALL require human confirmation, update the pull request body, and restart full-diff Round 1. A material amendment SHALL include any semantic change to Goal, Non-goals, Accepted Residual Risks, or Acceptance Criteria, plus any new in-scope behavior. An editorial amendment SHALL NOT restart review.

#### Scenario: Material amendment restarts review

- **WHEN** a human adds AC-4 after Round 1 starts
- **THEN** the workflow SHALL update the frozen contract and restart Round 1 against the full diff

#### Scenario: Editorial correction keeps current pass

- **WHEN** a human corrects a spelling error without changing contract meaning
- **THEN** the workflow SHALL continue the current review pass

### Requirement: Mechanical conformance checks protect the Review Contract

The convergence checker SHALL fail when a required contract heading or conditional-R2 rule is absent, when known unanimous-voice wording grants a non-blocking finding veto power, or when the deep skill document exceeds 1220 lines. The checker SHALL expose these checks through the existing pure function and synthetic mutation tests.

#### Scenario: Required heading mutation fails

- **WHEN** a synthetic skill document removes Accepted Residual Risks
- **THEN** the checker SHALL report that required heading as absent

#### Scenario: Unanimous wording mutation fails

- **WHEN** a synthetic skill document contains `全員 LGTM（含 actionable NIT）`
- **THEN** the checker SHALL report forbidden convergence wording

#### Scenario: Conditional R2 mutation fails

- **WHEN** a synthetic skill document removes the clean-R1 R2-skip rule
- **THEN** the checker SHALL report the conditional-R2 anchor as absent

## ADDED Requirements

### Requirement: Disposition oracle transcribed from the runbook matrix

The system SHALL load a machine-readable oracle transcribed from the Evidence gate disposition
matrix in the pr-cycle-deep SKILL.md. Each oracle entry SHALL key on four factors — severity,
evidence form, round, and contract mapping — and map them to exactly one expected disposition
drawn from the closed enumeration: blocking, deferred, outside-contract, non-blocking. An oracle
entry whose expected disposition falls outside that enumeration SHALL be rejected with a
validation error.

#### Scenario: oracle entry outside the closed enumeration is rejected

- **WHEN** an oracle entry declares an expected disposition that is not one of blocking,
  deferred, outside-contract, or non-blocking
- **THEN** loading SHALL fail with a validation error naming the offending entry
- **AND** the system SHALL NOT fall back to a default disposition

#### Scenario: fixture factor combination absent from the oracle halts the run

- **WHEN** a fixture declares a factor combination that has no matching oracle entry
- **THEN** the run SHALL abort with an error naming that fixture
- **AND** the system SHALL NOT treat the missing entry as a pass

### Requirement: Conformance fixture schema

The system SHALL load conformance fixtures, each carrying an identifier, synthetic round-one
finding text, the round the finding is evaluated in, the Review Contract excerpt in force, the
expected disposition, and a bound mutation descriptor. A fixture missing any of these fields, or
carrying an expected disposition outside the closed enumeration, SHALL be rejected with a
validation error. The system SHALL NOT silently drop a malformed fixture.

#### Scenario: malformed fixture is surfaced rather than skipped

- **WHEN** a fixture file omits the expected disposition field
- **THEN** loading SHALL fail with a validation error naming that fixture
- **AND** the remaining fixtures SHALL NOT be evaluated as though the set were complete

#### Scenario: empty fixture set fails loud

- **WHEN** the fixture directory contains no fixtures
- **THEN** the run SHALL exit with a failure status
- **AND** the system SHALL NOT report the run as fully passing

### Requirement: Fixture set covers both blocking and non-blocking expectations

The fixture set SHALL contain at least one fixture whose expected disposition is blocking and at
least one whose expected disposition is non-blocking. A fixture set that violates this balance
SHALL be rejected before any judge invocation.

#### Scenario: all-deferred fixture set is rejected

- **WHEN** every fixture in the set expects a non-blocking or deferred disposition
- **THEN** the run SHALL abort with an error stating that the set cannot distinguish correct
  filtering from a degenerate always-defer behavior
- **AND** no judge invocation SHALL be made

### Requirement: Three-valued stability verdict

For each fixture the system SHALL invoke the judge n times independently, where n defaults to 5,
and SHALL classify the result as CONFORMANT when at least four runs agree on a disposition equal
to the expected disposition, NONCONFORMANT when at least four runs agree on a disposition
differing from the expected disposition, and UNSTABLE when no disposition reaches four runs. The
system SHALL NOT collapse UNSTABLE into NONCONFORMANT.

#### Scenario: unstable fixture is reported distinctly

- **WHEN** a fixture's five runs produce three distinct dispositions
- **THEN** the verdict SHALL be UNSTABLE
- **AND** the report SHALL present UNSTABLE separately from NONCONFORMANT

##### Example: verdict boundaries at n = 5

| Run dispositions | Expected | Verdict |
| ---------------- | -------- | ------- |
| blocking ×5 | blocking | CONFORMANT |
| blocking ×4, deferred ×1 | blocking | CONFORMANT |
| deferred ×4, blocking ×1 | blocking | NONCONFORMANT |
| blocking ×3, deferred ×2 | blocking | UNSTABLE |
| blocking ×2, deferred ×2, outside-contract ×1 | blocking | UNSTABLE |

### Requirement: Boundary verdicts are re-run at higher n

A fixture whose run distribution reaches neither a five-run nor a four-run majority SHALL be
re-evaluated at n equal to 15 before its verdict is recorded. The report SHALL mark any verdict
derived from a re-run.

#### Scenario: three-to-two split triggers a re-run

- **WHEN** a fixture's five runs split three to two
- **THEN** the system SHALL re-evaluate that fixture at n equal to 15
- **AND** the recorded verdict SHALL be derived from the 15-run distribution

### Requirement: Conservation of findings across aggregation

The system SHALL verify that every input finding appears in the judge's aggregated output exactly
once, with its title and description preserved verbatim. A finding that is absent, duplicated, or
altered SHALL be reported as a conservation failure naming that finding. Conservation failures
SHALL be reported before disposition verdicts.

#### Scenario: dropped finding is reported as a conservation failure

- **WHEN** the aggregated output omits one of the input findings
- **THEN** the report SHALL record a conservation failure naming that finding
- **AND** the conservation result SHALL appear before the disposition verdicts

#### Scenario: altered finding text is reported as a conservation failure

- **WHEN** a finding appears in the aggregated output with its description rewritten
- **THEN** the report SHALL record a conservation failure naming that finding

### Requirement: Judge execution failure is distinguished from a deferred verdict

When the judge backend fails to produce a disposition, the system SHALL record an execution
failure for that run. The system SHALL NOT record an execution failure as a deferred disposition
and SHALL NOT count it toward the stability majority.

#### Scenario: backend error does not become a disposition

- **WHEN** a judge invocation returns an error instead of a disposition
- **THEN** that run SHALL be recorded as an execution failure
- **AND** the run SHALL NOT contribute to any disposition tally

### Requirement: Report states the limit of what the result proves

Every report the system produces SHALL open with a statement that the result establishes
conformance to the existing gate rules only, and does not establish that those rules are correct.

#### Scenario: limitation statement is present in every report

- **WHEN** a report is generated, whether all fixtures pass or some fail
- **THEN** the first line of the report SHALL state that the result proves rule conformance and
  not rule correctness

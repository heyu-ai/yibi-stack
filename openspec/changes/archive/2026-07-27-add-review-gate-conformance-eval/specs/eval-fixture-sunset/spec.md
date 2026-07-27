## ADDED Requirements

### Requirement: Every fixture binds a single-edit mutation

Each fixture SHALL bind exactly one mutation descriptor naming an anchor string in the
pr-cycle-deep SKILL.md and the replacement content for that anchor. A mutation descriptor that
names more than one anchor SHALL be rejected with a validation error, because a compound mutation
can turn a fixture red for a reason unrelated to the rule it claims to cover.

#### Scenario: compound mutation descriptor is rejected

- **WHEN** a fixture's mutation descriptor names two anchor strings
- **THEN** loading SHALL fail with a validation error naming that fixture
- **AND** no mutation SHALL be applied

### Requirement: Mutation whose anchor is absent halts the run

When applying a mutation, the system SHALL locate its anchor string in the target document. If the
anchor is not found, the system SHALL abort with an error naming the fixture and the anchor. The
system SHALL NOT skip the mutation and SHALL NOT record a result for that fixture, because an
unapplied mutation yields a verification that establishes nothing.

#### Scenario: stale anchor aborts rather than silently skipping

- **WHEN** a fixture's mutation anchor no longer appears in the target document
- **THEN** the run SHALL abort with an error naming that fixture and anchor
- **AND** the fixture SHALL NOT be recorded as having survived or been killed

### Requirement: Mutation restoration invalidates stale cached bytecode

After restoring the mutated document, the system SHALL remove cached bytecode for the affected
module tree and SHALL update the restored file's modification timestamp before any subsequent run.

#### Scenario: restored document is not evaluated from stale cache

- **WHEN** a mutation run completes and the document is restored
- **THEN** cached bytecode for the affected module tree SHALL be removed
- **AND** the restored file's modification timestamp SHALL be updated

### Requirement: Fixture effectiveness is defined by mutation kill

A fixture SHALL be classified as effective only when applying its bound mutation changes its
verdict from CONFORMANT to NONCONFORMANT. A fixture whose verdict is unchanged under its mutation
SHALL be classified as ineffective. The system SHALL NOT use suite-level pass rate as an
effectiveness signal.

#### Scenario: surviving mutation marks the fixture ineffective

- **WHEN** a fixture remains CONFORMANT after its bound mutation is applied
- **THEN** that fixture SHALL be classified as ineffective
- **AND** the prune report SHALL recommend its removal

### Requirement: Quarterly fixture prune classification

The system SHALL produce a prune recommendation for each fixture from its effectiveness and its
alert history within the review window.

#### Scenario: prune recommendations are produced per fixture

- **WHEN** a prune report is generated at the end of a review window
- **THEN** each fixture SHALL carry exactly one recommendation drawn from: keep at regular
  cadence, demote to quarterly cadence, or remove

##### Example: prune recommendation table

| Mutation kills fixture | Alert history in window | Recommendation |
| ---------------------- | ----------------------- | -------------- |
| yes | at least one true alert | keep at regular cadence |
| yes | never alerted | demote to quarterly cadence |
| no | any | remove |
| yes | alerted, all false alarms, first occurrence | keep and repair once |
| yes | alerted, all false alarms, second occurrence | remove |

### Requirement: Red results are classified and unclassified defaults to false alarm

Every red result SHALL be classified in the review record as either a true alert, meaning it
surfaced a real regression in gate behavior, or a false alarm, meaning the fixture or oracle was
stale or the runbook was legitimately reworded. A red result left unclassified at the end of the
review window SHALL count as a false alarm.

#### Scenario: unclassified red counts against the suite

- **WHEN** the review window closes with a red result that carries no classification
- **THEN** that result SHALL be counted as a false alarm in the suite metrics

### Requirement: Suite sunset triggers

The system SHALL evaluate three sunset triggers at the end of each review window and SHALL report
the suite as due for removal assessment when any one holds: every surviving fixture has never
alerted across two consecutive windows; false alarms outnumber true alerts within the window; or
the gate disposition logic has been moved into code and is covered directly by unit tests.

#### Scenario: no-alert across two windows triggers removal assessment

- **WHEN** two consecutive review windows close with every surviving fixture never having alerted
- **THEN** the suite SHALL be reported as due for removal assessment naming that trigger

#### Scenario: noise-dominant window triggers removal assessment

- **WHEN** a review window closes with more false alarms than true alerts
- **THEN** the suite SHALL be reported as due for removal assessment naming that trigger

#### Scenario: replacement by code coverage triggers removal assessment

- **WHEN** the gate disposition logic has been moved into code and covered by unit tests
- **THEN** the suite SHALL be reported as due for removal assessment naming that trigger
- **AND** the report SHALL state that this trigger represents the suite being superseded rather
  than having failed

### Requirement: Review is scheduled rather than remembered

The change SHALL create a dated review issue at implementation time, and each review window's
prune report and sunset evaluation SHALL be recorded in that issue. A review window whose result
is not recorded in the issue SHALL be treated as not having occurred.

#### Scenario: unrecorded review window does not count

- **WHEN** a review window closes with no prune report recorded in the review issue
- **THEN** that window SHALL be treated as not having occurred for the purpose of the
  two-consecutive-window sunset trigger

### Requirement: Removal is deletion rather than refactoring

The eval SHALL NOT be wired into pre-commit hooks or any merge-blocking path, and its
implementation SHALL be confined to a single module directory with a single execution entry point
and a single schedule entry, so that acting on a sunset trigger requires deleting that directory
and that schedule entry only.

#### Scenario: sunset removal touches only the module and its schedule entry

- **WHEN** a sunset trigger is acted upon
- **THEN** removal SHALL consist of deleting the module directory and the schedule entry
- **AND** no pre-commit hook or merge-blocking configuration SHALL require modification

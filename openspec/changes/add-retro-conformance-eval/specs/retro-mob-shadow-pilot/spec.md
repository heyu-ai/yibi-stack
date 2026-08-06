## ADDED Requirements

### Requirement: The pilot records the baseline calibration before revealing mob results

The shadow pilot SHALL capture the user's own calibration of a retro draft before the mob review
results are shown, and SHALL then record which of those decisions change after the results are
revealed. Revealing the mob results first would make the baseline unrecoverable.

#### Scenario: Ordering within a single case

- **WHEN** a pilot case is run
- **THEN** the user's baseline calibration SHALL be recorded before the mob results are disclosed
- **AND** the post-disclosure decisions SHALL be recorded as a separate record

### Requirement: Presentation order is randomised across cases

Across pilot cases, the presentation order SHALL be randomised between baseline-first and
mob-first, because a fixed order anchors the outcome and the measurement would then report the
anchoring rather than the mob's effect.

#### Scenario: Order assignment

- **WHEN** the set of pilot cases is prepared
- **THEN** each case SHALL be assigned baseline-first or mob-first at random
- **AND** the assigned order SHALL be recorded with the case

### Requirement: Alignment is judged by an adjudicator blind to order

Comparison of claim-evidence alignment between the baseline and the post-mob result SHALL be
performed by an adjudicator that does not know which record came first.

#### Scenario: Adjudication input

- **WHEN** two records for the same case are submitted for alignment comparison
- **THEN** the adjudicator SHALL receive them without an indication of which was produced first

### Requirement: The pilot collects the six harm-and-benefit rates

The pilot SHALL collect the false objection rate, the false park rate, the proportion of cases in
which the user abandoned a correct lesson because of the mob, the proportion in which
claim-evidence alignment worsened after mob-driven edits, the user override rate, and the
proportion of settling checks that an adversarial voice produced but that could not be executed.

#### Scenario: A pilot case is recorded

- **WHEN** a pilot case completes
- **THEN** its record SHALL carry a value or an explicit not-applicable marker for each of the six
  rates

### Requirement: Cost is measured per reviewer call, not from the session total

Cost measurement SHALL meter each reviewer call at its own boundary. It SHALL NOT use the
engine's existing session-level token field, which covers the entire session and is inflated
whenever unrelated work shares that session. The measurement SHALL report wall-clock p50 and p95
for each insertion point, critical-path latency treating the voices as concurrent rather than
summed, per-voice input, output, and cache tokens, timeout, invalid, and retry rates, the number
of additional user interactions, and the incremental cost per finding ultimately confirmed as
real.

#### Scenario: Session-level token field is used

- **WHEN** a cost report is produced from the engine's session-level token field
- **THEN** the report SHALL be rejected as invalid

#### Scenario: Latency of concurrent voices

- **WHEN** three voices run concurrently
- **THEN** the reported critical-path latency SHALL be the longest single voice, not the sum of
  the three

##### Example: latency reporting

| Voice durations | Summed | Critical path (reported) |
| --------------- | ------ | ------------------------ |
| 40s, 55s, 35s | 130s | 55s |

### Requirement: Enabling demotion requires a checkable verdict

Whether the demotion flag is turned on by default SHALL be determined by a verdict the pilot
harness emits, evaluated against relative budgets rather than absolute currency thresholds: p95
incremental wait SHALL NOT exceed twice the baseline, and the cost per confirmed effective
finding SHALL NOT exceed one full baseline retro. When the collected data are insufficient, the
verdict SHALL be "insufficient data" and SHALL NOT be reported as a negative result.

#### Scenario: Insufficient data

- **WHEN** fewer cases have been collected than the verdict requires
- **THEN** the verdict SHALL be "insufficient data"
- **AND** it SHALL NOT be reported as a failure to meet the criteria

#### Scenario: Budgets exceeded

- **WHEN** the p95 incremental wait exceeds twice the baseline
- **THEN** the verdict SHALL be negative
- **AND** the verdict SHALL name which budget was exceeded

##### Example: verdict outcomes

| Cases collected | p95 incremental wait | Cost per confirmed finding | Verdict |
| --------------- | -------------------- | -------------------------- | ------- |
| 3 | 1.4x baseline | 0.6 baseline retro | insufficient data |
| 10 | 1.4x baseline | 0.6 baseline retro | positive |
| 10 | 2.3x baseline | 0.6 baseline retro | negative, p95 wait budget exceeded |
| 10 | 1.4x baseline | 1.5 baseline retro | negative, cost-per-finding budget exceeded |

### Requirement: This capability defines the protocol and does not execute the pilot

This capability SHALL deliver the protocol definition and the harness that records and scores
pilot cases. It SHALL NOT execute the pilot, and it SHALL NOT change the default value of the
demotion flag. While the protocol is unexecuted, the shipped default SHALL remain the shadow
setting.

#### Scenario: Protocol ships unexecuted

- **WHEN** this capability ships and no pilot case has been collected
- **THEN** the demotion flag's default SHALL remain the shadow setting

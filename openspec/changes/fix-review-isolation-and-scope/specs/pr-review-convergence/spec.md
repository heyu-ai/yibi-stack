## REMOVED Requirements

### Requirement: Skill document line budget

**Reason**: The historical numeric ceiling is an incidental document snapshot, not proof of
review safety or convergence. Its source-count tests are retired under AC-8.

**Migration**: Use observable review-helper regression checks. Retain required-content validation
under the replacement Skill document contract validation requirement; do not repin the old ceiling.

## ADDED Requirements

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

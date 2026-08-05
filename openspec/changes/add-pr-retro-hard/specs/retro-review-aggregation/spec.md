## ADDED Requirements

### Requirement: Aggregation core is the single decision owner and its runbook summary is cross-checked

Aggregation SHALL be implemented as a pure function that is the production decision path, and the runbook SHALL NOT restate or re-implement the aggregation algorithm. The runbook SHALL record only which script to invoke, which return states halt the workflow, and which fields are left to human judgement. The aggregation implementation SHALL expose a policy description output, and a mechanical check SHALL assert in both directions that every outcome the implementation produces is documented in the runbook and every outcome the runbook names exists in the implementation.

#### Scenario: an implementation outcome is undocumented

- **WHEN** the implementation produces an outcome that the runbook summary does not describe
- **THEN** the cross-check SHALL fail and name the undocumented outcome

#### Scenario: the runbook names a nonexistent outcome

- **WHEN** the runbook summary names an outcome the implementation cannot produce
- **THEN** the cross-check SHALL fail and name the nonexistent outcome

### Requirement: Finding structure uses closed enumerations and malformed input fails loud

Each finding SHALL carry a target identifier, a classification drawn from a closed enumeration, a settling-check descriptor, and a statement. The classification enumeration SHALL be closed and SHALL NOT contain a catch-all member. A finding carrying an unknown classification, a missing target, or a missing statement SHALL be rejected with an explicit error. The system SHALL NOT silently drop a malformed finding and SHALL NOT substitute a default classification.

#### Scenario: unknown classification is rejected

- **WHEN** a finding declares a classification outside the closed enumeration
- **THEN** aggregation SHALL fail with an error naming the offending finding
- **AND** aggregation SHALL NOT assign a default classification

#### Scenario: finding without a target is rejected

- **WHEN** a finding omits its target identifier
- **THEN** aggregation SHALL fail with an error naming the offending finding

### Requirement: Settling check carries five distinct execution states

A settling check SHALL resolve to exactly one of five states: not executed, unable to execute, inconclusive, confirmed, or refuted. The system SHALL treat these five states as distinct and SHALL NOT collapse any of them into another. In particular, unable to execute SHALL NOT be treated as refuted, because an invalid piece of evidence does not establish that the claim is false.

#### Scenario: a settling check cannot be run

- **WHEN** a settling check fails to execute
- **THEN** the system SHALL record the state as unable to execute
- **AND** the system SHALL NOT record it as refuted
- **AND** the system SHALL NOT record it as confirmed

##### Example: settling-check state to disposition mapping

| Settling-check state | Demotion recommendation | Presented to human |
| -------------------- | ----------------------- | ------------------ |
| not executed | none | yes, as annotation |
| unable to execute | none | yes, as annotation naming the execution failure |
| inconclusive | none | yes, as annotation |
| confirmed | permitted | yes, with the recommendation |
| refuted | none | yes, recorded as not reproduced |

### Requirement: Agreement never raises confidence and never rewrites the source label

Agreement among reviewer voices SHALL NOT increase a lesson's confidence value and SHALL NOT rewrite its source label to the cross-model value. Adding further agreeing findings to the same input SHALL leave the confidence value and source label unchanged. Only a dissenting finding SHALL be able to lower a confidence value. A lesson whose source label records a human statement SHALL NOT have that label downgraded by aggregation; a dissenting finding against such a lesson SHALL be recorded separately.

#### Scenario: every voice agrees with the draft

- **WHEN** all reviewer voices report agreement and no dissent
- **THEN** the confidence value SHALL equal the input confidence value
- **AND** the source label SHALL equal the input source label

##### Example: monotonicity under added agreement

| Input confidence | Input source | Findings | Output confidence | Output source |
| ---------------- | ------------ | -------- | ----------------- | ------------- |
| 5 | inferred | none | 5 | inferred |
| 5 | inferred | one agreement | 5 | inferred |
| 5 | inferred | three agreements from three voices | 5 | inferred |
| 5 | inferred | one overclaim dissent | lowered | inferred |
| 9 | user-stated | one dissent | 9 | user-stated, dissent recorded separately |

### Requirement: Adversarial findings never count toward consensus and a missing settling check is non-actionable

A finding produced by the adversarial reviewer SHALL NOT count toward any consensus tally and SHALL be reported separately from external-voice findings. A settling-check descriptor recording that no check was supplied SHALL be a valid parsed value. For an adversarial finding, a missing settling check SHALL render that finding non-actionable commentary that is still presented to the human but affects no confidence value, no source label, no tier recommendation, and no draft content. For an external-voice finding, a missing settling check SHALL cap that finding at unresolved and SHALL NOT produce a demotion recommendation.

#### Scenario: adversarial finding without a settling check

- **WHEN** the adversarial reviewer reports an objection and supplies no settling check
- **THEN** aggregation SHALL mark that finding non-actionable
- **AND** aggregation SHALL still include it in the human-facing report
- **AND** aggregation SHALL NOT alter any confidence value or tier recommendation from it

#### Scenario: external finding without a settling check

- **WHEN** an external voice reports a finding and supplies no settling check
- **THEN** aggregation SHALL classify that finding as unresolved
- **AND** aggregation SHALL NOT produce a demotion recommendation from it

### Requirement: Tier demotion is a recommendation gated on a confirmed settling check

When a finding asserts that the cited evidence does not support a claim, aggregation SHALL emit a tier demotion **recommendation** rather than a decision, and SHALL emit it only when that finding's settling check state is confirmed. The recommendation SHALL be consumed by the retrospective engine's existing evidence gate, and aggregation SHALL NOT bypass that gate, SHALL NOT redefine its tier semantics, and SHALL NOT write to any lesson store directly.

#### Scenario: evidence-unsupported finding with an unexecuted check

- **WHEN** a finding asserts the evidence does not support a claim and its settling check has not been executed
- **THEN** aggregation SHALL NOT emit a demotion recommendation
- **AND** aggregation SHALL present the finding as an annotation

#### Scenario: evidence-unsupported finding with a confirmed check

- **WHEN** a finding asserts the evidence does not support a claim and its settling check state is confirmed
- **THEN** aggregation SHALL emit a demotion recommendation identifying the affected item
- **AND** the recommendation SHALL be marked as input to the existing evidence gate rather than as an applied decision

### Requirement: Draft items are annotated and never removed by aggregation

Aggregation SHALL preserve every draft item presented to the human. Aggregation SHALL NOT delete, merge, or rewrite the text of a draft item, and SHALL express every objection as an annotation attached to that item.

#### Scenario: two voices dissent against the same draft item

- **WHEN** more than one voice objects to the same draft item
- **THEN** that draft item SHALL still appear in the human-facing report with its original text
- **AND** both objections SHALL appear as annotations on it

### Requirement: A semantic change to the draft invalidates prior findings

Aggregation SHALL take a digest of the draft under review and a digest of the review packet as inputs. When findings are supplied whose recorded draft digest differs from the current draft digest, aggregation SHALL mark those findings stale or reject them, and SHALL NOT apply them to the current draft.

#### Scenario: human edits the draft after the first review round

- **WHEN** the human calibrates the draft and findings from the earlier draft are then supplied
- **THEN** aggregation SHALL mark those findings stale
- **AND** aggregation SHALL NOT derive a confidence change or a demotion recommendation from them

#### Scenario: suggestion text is edited after the second review round

- **WHEN** the rule or hook suggestion text is edited after it was reviewed
- **THEN** aggregation SHALL mark the prior findings stale and SHALL require a fresh review round

### Requirement: Aggregation is order-independent and idempotent

Aggregation SHALL produce identical output for the same set of findings regardless of the order in which voices or findings are supplied. Supplying the same finding set a second time SHALL produce the same output and SHALL NOT accumulate duplicate tallies or apply a confidence change twice.

#### Scenario: voices supplied in a different order

- **WHEN** the same finding set is supplied with the voices permuted
- **THEN** aggregation output SHALL be identical

#### Scenario: the same finding set is aggregated twice

- **WHEN** aggregation runs a second time over the same finding set
- **THEN** the output SHALL be identical to the first run
- **AND** no tally SHALL be incremented twice

### Requirement: Demotion recommendations are inert until explicitly enabled

Aggregation SHALL always compute and report a demotion recommendation, and acting on that recommendation SHALL be controlled by an explicit switch that defaults to disabled. While the switch is disabled, the workflow SHALL present the recommendation as an annotation and SHALL NOT change any item's tier.

#### Scenario: recommendation is produced while the switch is disabled

- **WHEN** aggregation emits a demotion recommendation and the switch is disabled
- **THEN** the workflow SHALL present the recommendation to the human
- **AND** no item's tier SHALL change

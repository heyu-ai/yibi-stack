## ADDED Requirements

### Requirement: The evaluation core never calls a language model

The conformance evaluation core SHALL NOT import or invoke any language model. Judgements SHALL
be obtained through a seam: the core emits a manifest of items awaiting judgement, an agent
session performs the judgements, and the core replays the recorded dispositions. This seam is
what makes the core deterministically testable.

#### Scenario: The full loop runs without a model call

- **WHEN** an operator emits a manifest, supplies a matching dispositions file, and scores the run
- **THEN** the core SHALL produce the metric report without making any model call

#### Scenario: Dispositions are missing

- **WHEN** the core is asked to score a run and no dispositions are available
- **THEN** it SHALL emit the manifest, exit non-zero, and state what is still missing
- **AND** it SHALL NOT emit a metric report containing zeroes

### Requirement: Manifest and dispositions are bound by signature

The manifest and the dispositions replayed against it SHALL be bound by a signature. When the two
do not match, the run SHALL fail and print both signatures. The core SHALL NOT apply a
non-matching set of judgements.

#### Scenario: Signature mismatch

- **WHEN** a dispositions file whose signature differs from the manifest's is replayed
- **THEN** the run SHALL fail
- **AND** the failure message SHALL contain both the manifest signature and the dispositions
  signature

### Requirement: Fixture models are specific to the retro decision surface

The fixture model for this evaluation SHALL encode the factors of the retro mob-review decision
surface — the shape of the claim-evidence pair, the defect family, and whether the settling check
is executable. It SHALL NOT reuse a fixture model bound to another evaluation's factors.

#### Scenario: An unrelated fixture model is rejected

- **WHEN** a fixture is supplied whose factors belong to a different evaluation's decision surface
- **THEN** the core SHALL reject it rather than score it

### Requirement: Every mutant has a clean twin

Each mutated fixture SHALL be accompanied by an unmutated twin of the same shape. A fixture set
lacking a clean twin for any mutant SHALL be rejected with a non-zero result naming that fixture.
Without the twin, the measurement reports a tendency to flag anything suspicious rather than an
ability to distinguish a real defect from a sound one.

#### Scenario: Missing clean twin

- **WHEN** a fixture set contains a mutant with no corresponding clean twin
- **THEN** the run SHALL fail and name the fixture
- **AND** the failure SHALL be a hard error, not a warning

### Requirement: Mutation operators are derived from observed failures

The mutation operators SHALL be evidence replacement, scope expansion, actor inversion, and
causal substitution, each derived from failures observed in real retro material rather than
invented. Each mutation SHALL alter exactly one minimal fragment and SHALL preserve word count,
formatting, and citation density.

#### Scenario: A mutation changes more than one fragment

- **WHEN** a mutation alters more than one fragment of the source
- **THEN** the fixture SHALL be rejected

##### Example: operator families

| Operator | What it alters | Preserved |
| -------- | -------------- | --------- |
| evidence replacement | the cited evidence, leaving the claim intact | word count, formatting, citation density |
| scope expansion | the breadth of the claim, leaving the evidence intact | word count, formatting, citation density |
| actor inversion | which party performs the action | word count, formatting, citation density |
| causal substitution | the stated cause, leaving the effect intact | word count, formatting, citation density |

### Requirement: A deterministic judge proves fixture binding without an agent session

The evaluation SHALL provide a judge that determines mutation-kill deterministically inside the
test suite, so that "this fixture is genuinely bound to the production logic" can be proven
without running an agent session.

#### Scenario: Mutation-kill is proven in the test suite

- **WHEN** the test suite runs with no agent session available
- **THEN** it SHALL still demonstrate that each fixture's mutation is killed by the logic under
  evaluation

### Requirement: Six metrics are reported, with sample counts

The evaluation SHALL report detection recall, class accuracy, target localization,
settling-check validity, clean-twin false-positive rate, and false park rate. Each metric SHALL
carry its sample count. A metric with no samples SHALL be reported as having no samples, and
SHALL NOT be reported as zero.

#### Scenario: A metric category has no samples

- **WHEN** no fixture exercises a given metric category
- **THEN** that metric SHALL be reported as having no samples
- **AND** it SHALL NOT be reported as a value of zero

##### Example: report shape

| Metric | Value | Samples |
| ------ | ----- | ------- |
| detection recall | 0.82 | 17 |
| clean-twin false-positive rate | 0.06 | 17 |
| false park rate | no samples | 0 |

### Requirement: Historical falsified claims are excluded as a quantitative gate

Material drawn from this repository's own record of retro claims later shown to be wrong SHALL
NOT be used as a quantitative release gate. Such material MAY be used only as qualitative
warning. The reason is hindsight leakage: the refuting narrative is written into the rule files
the external voices can read, so the measurement would capture whether a voice looks something up
rather than whether it reasons. Survivorship bias compounds this and cannot be corrected for,
because undetected errors are absent from the corpus by construction.

#### Scenario: Historical falsified material is proposed as a gate

- **WHEN** a corpus built from previously falsified retro claims is proposed as a release gate
- **THEN** it SHALL be rejected as a gate
- **AND** it MAY still be retained as qualitative warning material

### Requirement: The evaluation registers no commit-time or merge-time blocker

The evaluation SHALL NOT register a pre-commit hook or any merge-blocking check. Only
second-scale deterministic tests SHALL run in continuous integration; the remainder SHALL be an
offline suite. This keeps the cost of removing the whole module at deleting one directory and one
scheduled entry.

#### Scenario: Continuous integration content

- **WHEN** the evaluation module ships
- **THEN** only its second-scale deterministic tests SHALL be present in continuous integration
- **AND** no pre-commit hook or merge-blocking check SHALL reference it

## Purpose

Add semantic duplicate and contradiction advice to lesson promotion without transferring lifecycle authority from Mycelium to Hindsight. Keep final rule and decision changes under explicit human control.

## ADDED Requirements

### Requirement: Advisory duplicate screening

Before routing candidates, promotion SHALL use a single invocation-level availability check and search canonical lesson key and insight context. It SHALL exclude own projections and synthesized derivatives, annotate possible_duplicate with page identity, and leave the final decision to the human. Memory equivalence SHALL NOT imply an existing rule or a duplicate canonical lesson.

#### Scenario: equivalent-memory -- Equivalent memory without an enforced rule

- **WHEN** Hindsight knows an equivalent lesson but the repository has no preventing rule
- **THEN** promotion SHALL present the possible duplicate without automatically discarding or downgrading the lesson.

### Requirement: Canonical decision precedence

Promotion SHALL inspect repository ADRs and rules before using Hindsight for supplementary context. A conflicting candidate SHALL be marked possible_contradiction with canonical evidence and alternatives to correct the lesson or change the ADR/spec. The human SHALL select the path before mutation.

#### Scenario: conflicting-adr -- Contradicting an existing ADR

- **WHEN** the candidate proposes a policy contrary to an existing ADR
- **THEN** the decision table SHALL present both alternatives and SHALL NOT automatically supersede the ADR.

### Requirement: Scoped lifecycle-safe promotion

Candidates and approved writes SHALL be scoped to the current project and selected canonical IDs, excluding parked, retired and superseded rows. Previously published inactive lessons SHALL use the shared lifecycle reconciliation contract. Missing optional integration, transport failures and unknown writes SHALL degrade while preserving the canonical promotion workflow.

#### Scenario: shared-key-projects -- Shared key in two projects

- **WHEN** a user approves promotion of a lesson whose key also exists in another project
- **THEN** only the approved IDs in the current project SHALL be changed and the other project's lessons SHALL remain unchanged.

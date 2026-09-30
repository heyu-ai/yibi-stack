## Purpose

Connect retrospective lessons to Hindsight as a derived searchable representation while preserving Mycelium as the canonical lifecycle ledger. Record provenance and observable outcomes without treating asynchronous acceptance as completed indexing.

## ADDED Requirements

### Requirement: One-shot capability preflight

The retrospective workflow SHALL check actual MCP schemas, bank identity, and a bounded read once per invocation. An unavailable capability or failed call SHALL produce a degraded receipt and continue the original Mycelium flow without repeated per-lesson availability probes.

#### Scenario: missing-tools -- Missing tools

- **WHEN** Hindsight tools are absent
- **THEN** the workflow SHALL record hindsight_sync=skipped and complete its original retrospective steps without a Hindsight write.

### Requirement: Independent recurrence evidence

The workflow SHALL search before assigning confidence, inspect up to three non-projection candidates locally, and reflect only for high-value ambiguous or conflicting evidence. It SHALL exclude Mycelium projections and synthesized derivatives, deduplicate source incidents, and require verified distinct PR/session identities or explicit human confirmation before any recurrence adjustment.

#### Scenario: projection-derived-hit -- Projection returned under a thematic page

- **WHEN** a search result repeats an ingested lesson without a distinct incident source
- **THEN** it SHALL NOT increase recurrence or confidence even if the page title lacks the Lesson prefix.

### Requirement: Canonical projection eligibility

Projection SHALL follow successful canonical writes and readback, including skip-if-exists and finalize paths. A pitfall SHALL require confidence at least seven, non-inferred source, and a verified incident pointer; a pattern SHALL require confidence at least seven and two distinct incidents. Inactive lessons SHALL NOT create an active projection.

#### Scenario: pattern-evidence-deduplication -- Pattern evidence deduplication

- **WHEN** a confidence-eight pattern has two references to the same PR
- **THEN** prepare SHALL skip it because there is only one distinct incident.

#### Scenario: canonical-write-failure -- Canonical write failure

- **WHEN** the retrospective write or required typed lesson mutation fails
- **THEN** no new lesson projection or initiative outcome SHALL be published.

#### Scenario: publication-thresholds -- Eligibility boundaries

- **WHEN** canonical confidence is below seven, a pitfall is inferred or lacks evidence, or a pattern has fewer than two distinct incidents
- **THEN** prepare SHALL skip publication; eligible records at confidence seven SHALL produce ingest arguments.

#### Scenario: missing-lifecycle -- Incomplete canonical snapshot

- **WHEN** canonical tags, retired_at or superseded_by are absent
- **THEN** prepare SHALL reject the snapshot rather than infer an active lifecycle.

### Requirement: Stable content envelope

The ingest call SHALL use only title and content. The title SHALL be stable as [Lesson] followed by the canonical lowercase kebab-case key. The content SHALL carry project, source_system, source_id, lifecycle, summary, verified evidence identifiers, SHA-256 content_hash and a logical revision_key. These fields SHALL NOT be described as native server metadata or operation idempotency. Same accepted revision SHALL skip; changed content SHALL keep the same document identity.

#### Scenario: changed-summary -- Changed summary

- **WHEN** an eligible lesson summary changes with the same project and key
- **THEN** prepare SHALL emit a new content hash with the same title and expected document ID.

#### Scenario: cross-project-receipt -- Cross-project receipt

- **WHEN** a prior projection receipt belongs to a different project
- **THEN** prepare SHALL reject the write rather than overwrite the other project's document.

#### Scenario: unsafe-key -- Reject ambiguous document slugs

- **WHEN** a key is not lowercase kebab-case
- **THEN** prepare SHALL reject it rather than risk replacing a different key's slug.

### Requirement: Lifecycle reconciliation

On a later retro or promotion invocation, previously projected lessons SHALL be reread from canonical storage including inactive rows. Parked, superseded, or retired lessons SHALL replace their previous active document with a tombstone even when current confidence is below the publication threshold. Missing or ambiguous canonical rows SHALL degrade without inventing a deletion.

#### Scenario: inactive-record -- Low-confidence inactive record

- **WHEN** an accepted active projection's canonical lesson is now parked with confidence four
- **THEN** prepare SHALL produce a parked tombstone using the same document identity.

### Requirement: Initiative identity update

The workflow SHALL publish initiative outcomes only when a linked repo-qualified Epic/change identity and a confirmed Q2 capability or milestone exist. Exact identity search/list/read SHALL precede creation. Existing initiatives SHALL be updated with relates_to_page_id; ambiguous matches or unknown creation outcomes SHALL degrade without a blind retry.

#### Scenario: existing-initiative -- Existing initiative

- **WHEN** an initiative for the same repo-qualified change already exists
- **THEN** capture SHALL receive that page ID instead of creating a second page for the PR title.

### Requirement: Audited real-world measurement

Each call SHALL record its operation, outcome, candidate page IDs, fallback and human decision. Ingest acceptance SHALL NOT be reported as queryable or synced. A report SHALL count distinct real retrospective identities and expose duplicate, invalidation, citation and false-recurrence rates with their observed denominators. Fewer than thirty retros SHALL report insufficient_data.

#### Scenario: repeated-execution -- Repeated execution

- **WHEN** thirty audit files describe repeated runs of one PR retrospective
- **THEN** the report SHALL count one retrospective and SHALL NOT claim the thirty-retro measurement threshold was reached.

#### Scenario: measurement-observations -- Honest observation denominators

- **WHEN** audit receipts contain duplicate invocations, a later reviewed outcome, unknown measurements or malformed boolean values
- **THEN** report SHALL deduplicate invocations, use the latest observed value per identity, preserve unknown rates as null, and list malformed audits as excluded.

#### Scenario: cancelled-retro -- Unwritten retrospective

- **WHEN** a live invocation has canonical_written=false
- **THEN** report SHALL NOT count it toward the thirty-retro threshold.

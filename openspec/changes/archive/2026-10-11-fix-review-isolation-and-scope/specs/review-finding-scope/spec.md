## Purpose

Prevent findings from stale or unrelated diffs from entering PR repairs by admitting them against
a freshly captured Git scope and retaining an auditable record of exclusions.

## ADDED Requirements

### Requirement: Step 2 consumes a fresh immutable PR scope

setup-review-dir MUST remain the sole fresh-fetch base owner and publish a manifest containing the
 base SHA, HEAD SHA and canonical changed paths before Step 2. A lagging local main MUST trigger
 an informational warning but MUST NOT alter the diff. The built-in review MUST receive an explicit PR target.

#### Scenario: stale local main without upstream

- **GIVEN** a PR branch without upstream and a local main behind the freshly fetched base
- **WHEN** scope is prepared
- **THEN** only paths changed between fresh base and PR HEAD are admitted
- **AND** paths changed only between stale main and fresh base are excluded

#### Scenario: fresh local main

- **GIVEN** local main equals the fetched base
- **WHEN** scope is prepared
- **THEN** valid in-scope findings retain their existing content

### Requirement: Only admitted findings reach the repair list

The filter MUST consume structured findings, preserve all fields of accepted findings except
 canonicalizing file identity, and reject paths outside the captured changed paths. It MUST retain
 every rejected item and reason in an audit with the exact discarded count. Aggregation MUST
 preserve that audit in final.md and MUST NOT reintroduce rejected raw findings into Step 6.

#### Scenario: mixed scope

- **GIVEN** changed paths src/current.py and a deleted src/old.py
- **WHEN** findings name those paths and unrelated src/base_only.py
- **THEN** the first two are accepted and src/base_only.py is rejected and audited

#### Scenario: renamed and unusual paths

- **WHEN** the diff contains renamed, deleted, space-containing or Unicode paths
- **THEN** membership is determined by Git's captured canonical path list without heuristic prefix stripping

#### Scenario: no findings

- **WHEN** a valid review contains an empty findings array
- **THEN** filtering succeeds with zero accepted and zero rejected findings

#### Scenario: corrupt or stale review input

- **WHEN** the input is malformed or HEAD differs from the captured HEAD
- **THEN** filtering fails loudly and removes prior admission artifacts so they cannot be reused

#### Scenario: repeated audit update

- **GIVEN** final.md already contains amplifier findings and an earlier scope audit
- **WHEN** filtering runs again
- **THEN** only the owned scope block is replaced and unrelated report content is preserved

#### Scenario: explicitly requested cleanups

- **WHEN** the user permits automatic cleanups
- **THEN** raw code-review fixes cannot run before scope admission
- **AND** any separate simplify changes require a refreshed scope and review before repair or publication

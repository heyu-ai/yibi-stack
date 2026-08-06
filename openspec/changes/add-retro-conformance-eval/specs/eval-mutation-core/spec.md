## ADDED Requirements

### Requirement: Shared mutation primitives are a single implementation

The repository SHALL expose the mutation-verification primitives as one shared module that
multiple evaluation modules import, rather than as per-module copies. The primitives SHALL
operate on descriptor, verdict, and window-record types that carry no disposition semantics,
so that a consumer with a different decision surface can reuse them unchanged.

#### Scenario: A second evaluation module reuses the primitives

- **WHEN** a new evaluation module needs to apply a mutation, restore the source, judge whether
  the mutation was effective, and classify a fixture's stability
- **THEN** it SHALL import those primitives from the shared module
- **AND** it SHALL NOT copy their implementation into its own package

#### Scenario: Extraction preserves the original module's behavior

- **WHEN** the primitives are moved out of the originating evaluation module into the shared module
- **THEN** the originating module's existing offline suite SHALL produce the same stability
  classifications as before the move
- **AND** no new test SHALL be added that duplicates coverage the existing suite already provides

### Requirement: A mutation whose anchor is absent or ambiguous fails loudly

Applying a mutation SHALL fail with a non-zero result naming the mutation when its anchor is
absent from the source, or when the anchor matches more than one location. The primitives SHALL
NOT skip such a mutation silently.

#### Scenario: Anchor not found

- **WHEN** a mutation's anchor string does not appear in the source
- **THEN** the operation SHALL fail and name the offending mutation
- **AND** the run SHALL NOT report that mutation as killed

#### Scenario: Anchor matches multiple locations

- **WHEN** a mutation's anchor string appears more than once in the source
- **THEN** the operation SHALL fail and name the offending mutation
- **AND** the failure message SHALL state how many locations matched

##### Example: anchor outcomes

| Anchor occurrences in source | Result | Reported as killed |
| ---------------------------- | ------ | ------------------ |
| 0 | failure naming the mutation | no |
| 1 | mutation applied | determined by the judge |
| 2 or more | failure naming the mutation and the match count | no |

### Requirement: Restoration invalidates stale derived artifacts

After a mutation is reverted, the primitives SHALL invalidate any cached or derived artifact
whose freshness is determined by the mutated source, so that a subsequent run cannot observe the
mutated state through a stale cache.

#### Scenario: Cached artifact is not reused after restoration

- **WHEN** a mutation is applied, evaluated, and then restored
- **THEN** any derived artifact produced while the mutation was in place SHALL be invalidated
- **AND** a subsequent evaluation SHALL observe the restored source, not the mutated one

## ADDED Requirements

### Requirement: Epistemic status tracking independent of retrieval tier

The system SHALL store an `epistemic_status` field on every LessonRecord.
The `epistemic_status` SHALL be one of: `episode`, `observation`, `corroborated`, `contradicted`.
New lessons SHALL be created with `epistemic_status` set to `episode`.
The `epistemic_status` SHALL be stored in the `epistemic_status` column of the `lessons` table with a default value of `episode`.
The `epistemic_status` SHALL be independent of the `tier` field: changing one SHALL NOT automatically change the other.

#### Scenario: New lesson defaults to episode status

- **WHEN** a new LessonRecord is created via any ingestion path
- **THEN** the lesson's `epistemic_status` is `episode`

#### Scenario: Epistemic status is independent of tier

- **WHEN** a lesson's `tier` is promoted from `working` to `hot` due to access count
- **THEN** the lesson's `epistemic_status` remains unchanged

#### Scenario: Filter lessons by epistemic status

- **WHEN** a caller invokes `lessons_service.get_lessons(epistemic_status="observation")`
- **THEN** only lessons with `epistemic_status = "observation"` are returned

##### Example: epistemic status vs tier independence

| tier | epistemic_status | Meaning |
|---|---|---|
| working | episode | Recently recorded, not yet corroborated, low retrieval frequency |
| hot | episode | Frequently retrieved but still a single-event observation |
| working | corroborated | Recently recorded but already confirmed by multiple episodes |
| cold | corroborated | Confirmed pattern that is no longer frequently retrieved |

#### Scenario: Pre-migration lessons default to episode

- **WHEN** the database is migrated and existing lessons have NULL `epistemic_status`
- **THEN** those lessons are treated as `episode` at read time (column default is `episode`)

### Requirement: Lesson supersession for append-only correction

The system SHALL store a `superseded_by` field on every LessonRecord, defaulting to NULL.
When a lesson's factual content is found to be incorrect, the system SHALL create a new correction lesson and set the original lesson's `superseded_by` to the new lesson's ID.
The original lesson's content SHALL NOT be modified.
The `distill_service` SHALL exclude lessons whose `superseded_by` is not NULL from cluster aggregation.

#### Scenario: Superseding a lesson preserves original content

- **WHEN** lesson L1 is superseded by lesson L2 via `lessons supersede L1-id L2-id`
- **THEN** L1's `superseded_by` is set to L2's ID, and L1's `insight`, `context`, and all other fields remain unchanged

#### Scenario: Superseded lessons excluded from distill

- **WHEN** `distill_service` aggregates lessons into clusters
- **THEN** lessons with `superseded_by IS NOT NULL` are excluded from all clusters

#### Scenario: Superseded lessons still queryable

- **WHEN** a caller invokes `lessons_service.get_lessons()` without any supersession filter
- **THEN** superseded lessons are included in the result set (with their `superseded_by` field visible)

##### Example: supersession chain

- **GIVEN** L1 (original, insight: "error caused by race condition"), L2 (correction, insight: "error caused by stale cache")
- **WHEN** `lessons supersede L1-id L2-id` is executed
- **THEN** L1.superseded_by = L2-id, L1.insight unchanged = "error caused by race condition"
- **WHEN** distill runs
- **THEN** L1 is excluded from clustering; L2 participates normally

#### Scenario: Invalid supersede target logged as warning

- **WHEN** `superseded_by` points to a lesson ID that does not exist in the database
- **THEN** the `distill_service` logs a warning and excludes the superseded lesson from clustering without raising an error

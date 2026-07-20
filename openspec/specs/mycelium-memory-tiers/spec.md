# mycelium-memory-tiers Specification

## Purpose

TBD - created by archiving change 'mycelium-layered-memory'. Update Purpose after archive.

## Requirements

### Requirement: Four-tier memory classification

The system SHALL classify every LessonRecord into one of four tiers: `working`, `hot`, `cold`, or `archival`.
New lessons SHALL be created with tier `working`.
The tier SHALL be stored in the `tier` column of the `lessons` table.
The system SHALL track `last_accessed_at` (timestamp of last retrieval) and `access_count` (cumulative retrieval count) for each lesson.

#### Scenario: New lesson enters working tier

- **WHEN** a new LessonRecord is created via any ingestion path (Stop hook, PreCompact hook, or `mycelium memory save`)
- **THEN** the lesson's `tier` is set to `"working"` and `access_count` is set to `0`

#### Scenario: Frequent lesson promoted to hot

- **WHEN** a lesson's `access_count` reaches 3 or more
- **THEN** the lesson's `tier` is updated to `"hot"` during the next promotion check

#### Scenario: Stale working lesson demoted to cold

- **WHEN** a lesson's `tier` is `"working"` or `"hot"`, `access_count` is `0`, and `age` (days since creation) exceeds 90 days
- **THEN** the lesson's `tier` is updated to `"cold"` during the next promotion check

#### Scenario: Cold lesson demoted to archival

- **WHEN** a lesson's `tier` is `"cold"`, `access_count` is `0`, and `age` exceeds 365 days
- **THEN** the lesson is demoted to `archival` tier and exported to `~/.agents/archive/YYYY-MM.md`

##### Example: tier transitions over time

| Days since creation | access_count | Expected tier |
|---------------------|-------------|---------------|
| 1 | 0 | working |
| 1 | 3 | hot |
| 91 | 0 | cold |
| 366 | 0 | archival |
| 400 | 5 | hot (access_count overrides age) |

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

---
### Requirement: effective_weight ranking formula

The system SHALL compute an `effective_weight` float for each lesson to enable relevance-ranked retrieval.
The formula SHALL be: `effective_weight = confidence x decay(age) x log(access_count + 1) x bot_trust_weight`
where `decay(age)` is exponential decay with a 90-day half-life: `decay(age) = 0.5 ^ (age_days / 90)`.
The `bot_trust_weight` SHALL be determined by the lesson's `source_bot` relative to the querying agent (see `mycelium-bot-trust-mcp` capability).
`lessons_service.get_lessons()` SHALL sort results by `effective_weight` descending by default.

#### Scenario: High-confidence frequently-accessed lesson ranks higher

- **WHEN** two lessons have the same age and `bot_trust_weight`,
  lesson A has `confidence=0.9, access_count=10` and lesson B has `confidence=0.5, access_count=1`
- **THEN** lesson A's `effective_weight` is greater than lesson B's

#### Scenario: Recent lesson outranks older lesson of equal confidence

- **WHEN** two lessons have `confidence=0.8, access_count=0, bot_trust_weight=1.0`,
  lesson A is 7 days old and lesson B is 180 days old
- **THEN** lesson A's `effective_weight` is greater than lesson B's

##### Example: effective_weight computation

- **GIVEN** lesson with `confidence=0.8`, `age_days=30`, `access_count=5`, `bot_trust_weight=0.9`
- **WHEN** `effective_weight` is computed
- **THEN** result is approximately `0.8 x 0.794 x 1.792 x 0.9 = 1.022`
  (decay = 0.5^(30/90) = 0.794; log(5+1) = 1.792)

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

---
### Requirement: Archival demotes without deletion

The system SHALL NOT delete a lesson record when demoting it to `archival` tier.
Instead, the system SHALL export the lesson's full content to `~/.agents/archive/YYYY-MM.md`
(where YYYY-MM is the month of archival), and SHALL store the export file path in the
`archived_path` column of the lesson record.
The system SHALL return archival-tier lessons when `--include-archived` flag is passed to `get_lessons()`.

#### Scenario: Archival export preserves full content

- **WHEN** a lesson is demoted to `archival`
- **THEN** the lesson's full `content`, `lesson_type`, `tags`, and `created_at` are written to
  `~/.agents/archive/YYYY-MM.md` in a readable Markdown format

#### Scenario: Archived lesson still queryable

- **WHEN** a caller invokes `lessons_service.get_lessons(include_archived=True, query="git push pitfall")`
- **THEN** lessons with `tier="archival"` whose `archived_path` exists are included in the result set

#### Scenario: Default recall excludes archival

- **WHEN** a caller invokes `lessons_service.get_lessons()` without `include_archived=True`
- **THEN** lessons with `tier="archival"` are excluded from the result set

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

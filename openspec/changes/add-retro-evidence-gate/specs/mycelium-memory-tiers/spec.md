# mycelium-memory-tiers Specification（delta）

本 change 的 Tier 3 park 機制改動了 `mycelium-memory-tiers` 已部署的行為：parked lesson
從此被排除於 tier promotion 與預設 recall 之外。已部署 spec 的
「Frequent lesson promoted to hot」場景原本是無條件的，現在有一個例外，必須在此以 delta 記錄，
否則已部署 spec 與通過的測試互相矛盾（`tasks/mycelium/tests/test_lesson_parking.py` 斷言
parked lesson 在 `access_count = 3` 時仍停在 `working`）。

## MODIFIED Requirements

### Requirement: Four-tier memory classification

The system SHALL classify every LessonRecord into one of four tiers: `working`, `hot`, `cold`, or `archival`.
New lessons SHALL be created with tier `working`.
The tier SHALL be stored in the `tier` column of the `lessons` table.
The system SHALL track `last_accessed_at` (timestamp of last retrieval) and `access_count` (cumulative retrieval count) for each lesson.

**新增約束**：a lesson whose `tags` contain `parked` SHALL NOT be considered by the promotion
check at all — it is excluded from the promotion job's fetch, so no promotion or demotion
transition applies to it while it stays parked. Un-parking (recurrence ≥ 2, which removes the
`parked` tag) returns the lesson to the normal transition rules.

#### Scenario: New lesson enters working tier

- **WHEN** a new LessonRecord is created via any ingestion path (Stop hook, PreCompact hook, or `mycelium memory save`)
- **THEN** the lesson's `tier` is set to `"working"` and `access_count` is set to `0`

#### Scenario: Frequent lesson promoted to hot

- **WHEN** a lesson's `access_count` reaches 3 or more **AND** its `tags` do not contain `parked`
- **THEN** the lesson's `tier` is updated to `"hot"` during the next promotion check

#### Scenario: Parked lesson is not promoted regardless of access_count

- **GIVEN** a lesson whose `tags` contain `parked`
- **WHEN** its `access_count` reaches 3 or more and the promotion check runs
- **THEN** the lesson's `tier` MUST remain unchanged (it is never fetched by the promotion job)
  AND the same exclusion MUST apply to the cold / archival demotion transitions

#### Scenario: Stale working lesson demoted to cold

- **WHEN** a lesson's `tier` is `"working"` or `"hot"`, `access_count` is `0`, `age` (days since creation) exceeds 90 days, **AND** its `tags` do not contain `parked`
- **THEN** the lesson's `tier` is updated to `"cold"` during the next promotion check

#### Scenario: Cold lesson demoted to archival

- **WHEN** a lesson's `tier` is `"cold"`, `access_count` is `0`, `age` exceeds 365 days, **AND** its `tags` do not contain `parked`
- **THEN** the lesson is demoted to `archival` tier and exported to `~/.agents/archive/YYYY-MM.md`

##### Example: tier transitions over time

| Days since creation | access_count | `parked` tag | Expected tier |
|---------------------|-------------|--------------|---------------|
| 1 | 0 | no | working |
| 1 | 3 | no | hot |
| 1 | 3 | **yes** | **working**（parked 不參與 promotion） |
| 91 | 0 | no | cold |
| 91 | 0 | **yes** | **working**（parked 不參與 demotion） |
| 366 | 0 | no | archival |
| 400 | 5 | no | hot (access_count overrides age) |

### Requirement: Archival demotes without deletion

The system SHALL NOT delete a lesson record when demoting it to `archival` tier.
Instead, the system SHALL export the lesson's full content to `~/.agents/archive/YYYY-MM.md`
(where YYYY-MM is the month of archival), and SHALL store the export file path in the
`archived_path` column of the lesson record.
The system SHALL return archival-tier lessons when `--include-archived` flag is passed to `get_lessons()`.

**新增約束**：default recall SHALL also exclude lessons whose `tags` contain `parked`.
A caller SHALL be able to include them explicitly via `include_parked=True`
（CLI：`mycelium lessons show --include-parked` / `mycelium lessons search --include-parked`）。
這與 archival 的排除是**兩個獨立維度**：`include_archived` 不會連帶納入 parked，反之亦然。

#### Scenario: Default recall excludes parked

- **WHEN** a caller invokes `lessons_service.show_lessons_typed()` or `search_lessons_typed()` without `include_parked=True`
- **THEN** lessons whose `tags` contain `parked` are excluded from the result set

#### Scenario: Parked lesson reachable with explicit flag

- **WHEN** a caller invokes the same query with `include_parked=True`
- **THEN** lessons whose `tags` contain `parked` are included in the result set
  AND their original title and description are returned unmodified

#### Scenario: Default recall excludes archival

- **WHEN** a caller invokes `lessons_service.get_lessons()` without `include_archived=True`
- **THEN** lessons with `tier="archival"` are excluded from the result set

<!-- @trace
source: add-retro-evidence-gate
updated: 2026-07-26
code: []
-->

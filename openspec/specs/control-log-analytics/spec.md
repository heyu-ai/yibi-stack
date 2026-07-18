# control-log-analytics Specification

## Purpose

TBD - created by archiving change 'pr-control-log'. Update Purpose after archive.

## Requirements

### Requirement: Cross-session statistics computation

The system SHALL compute the following four metrics from `control_log_entries` within a
given time window (`--since-days D`):

- `autonomy_ratio`: count of `autonomous_decision` entries / (count of
  `autonomous_decision` entries + count of entries where `user_requested = 1`).
  The denominator excludes pure `assumption`, `verification`, and other category entries
  to reflect the ratio of AI-initiated decisions relative to explicitly requested ones.
- `deviation_ratio`: count of `spec_deviation` entries / total entries
- `irreversible_op_count`: count of `irreversible_op` entries (integer, not a ratio)
- `verification_score`: count of entries where `verification_status = 'verified'` /
  (count of `verified` + `partial` + `unverified` entries)

Division by zero SHALL yield `None` (not `0.0` or `NaN`). The CLI SHALL display `N/A`
when a metric value is `None`.

#### Scenario: stats-happy-path -- normal statistics output with entries present

- **GIVEN** at least one `control_log_entries` row exists with `created_at` within the
  past D days
- **WHEN** the developer runs `stats --since-days D`
- **THEN** the CLI SHALL print a table containing `autonomy_ratio`, `deviation_ratio`,
  `irreversible_op_count`, `verification_score`, and `total_entries`
- **AND** all displayed ratio values SHALL be formatted as percentages or `N/A`

##### Example: typical mixed-category PR

| autonomous_decision | user_requested=1 | spec_deviation | total | verified | partial | unverified | Expected autonomy_ratio | Expected deviation_ratio | Expected verification_score |
|--------------------|--------------------|----------------|-------|----------|---------|------------|------------------------|-------------------------|-----------------------------|
| 2                  | 6                  | 1              | 10    | 4        | 2       | 4          | 0.25 (25%)             | 0.10 (10%)              | 0.40 (40%)                  |
| 5                  | 5                  | 3              | 12    | 6        | 0       | 6          | 0.50 (50%)             | 0.25 (25%)              | 0.50 (50%)                  |
| 0                  | 8                  | 0              | 8     | 8        | 0       | 0          | 0.00 (0%)              | 0.00 (0%)               | 1.00 (100%)                 |

#### Scenario: stats-json-output -- JSON flag produces machine-parseable output

- **GIVEN** at least one entry exists in the time window
- **WHEN** the developer runs `stats --since-days D --json`
- **THEN** the CLI SHALL output a single JSON object parseable with `json.loads()`
- **AND** the object SHALL contain keys `autonomy_ratio`, `deviation_ratio`,
  `irreversible_op_count`, `verification_score`, and `total_entries`
- **AND** ratio keys SHALL hold a float between 0.0 and 1.0 inclusive, or `null` when
  the denominator is zero
- **AND** `irreversible_op_count` SHALL hold a non-negative integer
- **AND** no trailing text or headers SHALL appear outside the JSON object

#### Scenario: stats-division-by-zero-autonomy -- autonomy_ratio is None when denominator is zero

- **GIVEN** there are zero `autonomous_decision` entries AND zero `user_requested = 1`
  entries in the time window
- **WHEN** the developer runs `stats --since-days D`
- **THEN** `autonomy_ratio` SHALL be `None` internally
- **AND** the CLI SHALL display `N/A` in the `autonomy_ratio` column
- **AND** the CLI SHALL NOT display `0`, `0.0`, `0%`, or `NaN`

##### Example: ratio edge cases

| autonomous_decision | user_requested=1 | Expected autonomy_ratio |
|--------------------|--------------------|-------------------------|
| 0                  | 0                  | None → N/A              |
| 3                  | 0                  | 1.0 → 100%              |
| 0                  | 4                  | 0.0 → 0%                |
| 1                  | 3                  | 0.25 → 25%              |

#### Scenario: stats-division-by-zero-verification -- verification_score is None when no verification entries

- **GIVEN** there are zero entries with `verification_status` in
  `{verified, partial, unverified}` in the time window
- **WHEN** the developer runs `stats --since-days D`
- **THEN** `verification_score` SHALL be `None` internally
- **AND** the CLI SHALL display `N/A` in the `verification_score` column

#### Scenario: stats-empty-window -- no entries in the time window

- **GIVEN** there are zero entries within the past D days
- **WHEN** the developer runs `stats --since-days D`
- **THEN** `total_entries` SHALL be `0`
- **AND** all four ratio metrics SHALL be `None` (displayed as `N/A`)
- **AND** `irreversible_op_count` SHALL be `0`
- **AND** the CLI SHALL NOT raise an exception

<!-- @trace
source: pr-control-log
updated: 2026-07-18
code: []
-->

---
### Requirement: Grouping statistics by category or project

When `--by category` or `--by project` is specified alongside `stats`, the output SHALL be
broken down per group. Each group row SHALL show at minimum the entry count for that group.

#### Scenario: stats-by-category -- one row per category

- **GIVEN** entries exist across multiple categories in the time window
- **WHEN** the developer runs `stats --since-days D --by category`
- **THEN** the CLI SHALL output one row per distinct `category` value present in the window
- **AND** each row SHALL display the category name and its entry count
- **AND** rows with zero entries for a category MAY be omitted

##### Example: by-category breakdown

| category             | count |
|----------------------|-------|
| autonomous_decision  | 4     |
| assumption           | 3     |
| spec_deviation       | 2     |
| irreversible_op      | 1     |

#### Scenario: stats-by-project -- one row per project

- **GIVEN** entries exist across multiple projects in the time window
- **WHEN** the developer runs `stats --since-days D --by project`
- **THEN** the CLI SHALL output one row per distinct `project` value present in the window
- **AND** each row SHALL display the project name and its entry count
- **AND** entries with an empty `project` field SHALL be grouped under a `(none)` or
  equivalent placeholder label

#### Scenario: stats-by-category-empty -- no entries in window with grouping flag

- **GIVEN** there are zero entries within the past D days
- **WHEN** the developer runs `stats --since-days D --by category`
- **THEN** the CLI SHALL output an empty table or a `no data` notice
- **AND** the CLI SHALL NOT raise an exception

<!-- @trace
source: pr-control-log
updated: 2026-07-18
code: []
-->

---
### Requirement: Threshold-based governance advice generation

The system SHALL evaluate the following four rules against computed metrics and output
advice in Traditional Chinese when conditions are met. The CLI subcommand is `advice --since-days D`.

| Rule | Condition | Advice text pattern |
|------|-----------|---------------------|
| R1 | `autonomy_ratio` > 0.30 | 「AI 自主決定比例偏高，考慮在 CLAUDE.md / rules 補充規範」 |
| R2 | `deviation_ratio` > 0.20 | 「偏離規格比例偏高，建議在 propose 階段更明確標註 AC」 |
| R3 | same `irreversible_op` category pattern appears >= 3 times | 「考慮新增 hook 阻擋此類操作」 |
| R4 | `verification_score` < 0.60 | 「驗證強度不足，建議在 retro 加 verify-before-completion gate」 |

When no rule is triggered, the CLI SHALL output `目前無建議`.

When fewer than 3 entries exist in the time window, the system SHALL note data
insufficiency and SHALL NOT evaluate or trigger any advice rule.

#### Scenario: advice-r1-triggers -- R1 fires when autonomy_ratio exceeds 30%

- **GIVEN** there are >= 3 entries in the time window
- **AND** `autonomy_ratio` > 0.30 (e.g., 4 autonomous_decision, 6 user_requested=1 → 40%)
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL contain R1 advice text in Traditional Chinese
- **AND** the output SHALL mention supplementing CLAUDE.md or rules

##### Example: R1 threshold boundary

| autonomous_decision | user_requested=1 | autonomy_ratio | R1 triggered? |
|--------------------|--------------------|----------------|---------------|
| 3                  | 7                  | 0.30           | No (not > 0.30) |
| 4                  | 6                  | 0.40 (> 0.30)  | Yes           |
| 1                  | 9                  | 0.10           | No            |

#### Scenario: advice-r2-triggers -- R2 fires when deviation_ratio exceeds 20%

- **GIVEN** there are >= 3 entries in the time window
- **AND** `deviation_ratio` > 0.20 (e.g., 3 spec_deviation out of 10 total → 30%)
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL contain R2 advice text in Traditional Chinese
- **AND** the output SHALL mention clarifying AC in the propose stage

##### Example: R2 threshold boundary

| spec_deviation | total_entries | deviation_ratio | R2 triggered? |
|----------------|---------------|-----------------|---------------|
| 2              | 10            | 0.20            | No (not > 0.20) |
| 3              | 10            | 0.30 (> 0.20)   | Yes           |
| 1              | 10            | 0.10            | No            |

#### Scenario: advice-r3-triggers -- R3 fires when same irreversible_op pattern repeats 3+ times

- **GIVEN** there are >= 3 entries in the time window
- **AND** entries contain >= 3 `irreversible_op` rows whose `summary` matches the same
  pattern (e.g., all three summarize `git push --force` operations)
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL contain R3 advice text in Traditional Chinese
- **AND** the output SHALL mention adding a hook to block the operation type

##### Example: R3 pattern matching

| irreversible_op summaries in window | R3 triggered? |
|-------------------------------------|---------------|
| ["force push", "force push", "force push"] | Yes (same pattern >= 3) |
| ["force push", "drop table", "alembic upgrade"] | No (each distinct) |
| ["force push", "force push"] | No (only 2 occurrences) |

#### Scenario: advice-r4-triggers -- R4 fires when verification_score falls below 60%

- **GIVEN** there are >= 3 entries in the time window
- **AND** `verification_score` < 0.60 (e.g., 2 verified, 1 partial, 7 unverified → 20%)
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL contain R4 advice text in Traditional Chinese
- **AND** the output SHALL mention adding a verify-before-completion gate in retro

##### Example: R4 threshold boundary

| verified | partial | unverified | verification_score | R4 triggered? |
|----------|---------|------------|--------------------|---------------|
| 6        | 0       | 4          | 0.60               | No (not < 0.60) |
| 5        | 0       | 5          | 0.50 (< 0.60)      | Yes           |
| 8        | 0       | 2          | 0.80               | No            |

#### Scenario: advice-no-rules -- no advice when all metrics are within thresholds

- **GIVEN** there are >= 3 entries in the time window
- **AND** `autonomy_ratio` <= 0.30
- **AND** `deviation_ratio` <= 0.20
- **AND** no single `irreversible_op` summary pattern appears >= 3 times
- **AND** `verification_score` >= 0.60 (or is `None` due to no verification entries)
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL be exactly `目前無建議`
- **AND** the output SHALL NOT contain any R1, R2, R3, or R4 advice text

#### Scenario: advice-multi-rule -- multiple rules trigger simultaneously

- **GIVEN** there are >= 3 entries in the time window
- **AND** `autonomy_ratio` > 0.30
- **AND** `deviation_ratio` > 0.20
- **AND** `verification_score` < 0.60
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL contain R1, R2, and R4 advice texts
- **AND** all triggered rule texts SHALL appear in the same output (not mutually exclusive)
- **AND** no `目前無建議` text SHALL appear

#### Scenario: advice-insufficient-data -- fewer than 3 entries suppresses all rules

- **GIVEN** there are fewer than 3 entries in the time window (e.g., 0, 1, or 2)
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL note that data is insufficient for reliable advice
- **AND** the output SHALL NOT contain R1, R2, R3, or R4 advice text
- **AND** the system SHALL NOT evaluate any threshold condition against the sparse data

##### Example: insufficient data boundary

| total_entries_in_window | Advice rules evaluated? |
|-------------------------|------------------------|
| 0                       | No — note insufficiency |
| 1                       | No — note insufficiency |
| 2                       | No — note insufficiency |
| 3                       | Yes — thresholds apply  |

#### Scenario: advice-r3-none-when-no-irreversible -- R3 does not trigger when irreversible_op count is low

- **GIVEN** there are >= 3 entries in the time window
- **AND** there are fewer than 3 `irreversible_op` entries with any shared summary pattern
- **WHEN** the developer runs `advice --since-days D`
- **THEN** the output SHALL NOT contain R3 advice text
- **AND** if no other rule is triggered, the output SHALL be `目前無建議`

<!-- @trace
source: pr-control-log
updated: 2026-07-18
code: []
-->

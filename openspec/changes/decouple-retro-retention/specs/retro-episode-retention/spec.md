## ADDED Requirements

### Requirement: Retro writes episode to Mycelium without auto-queue

The `/pr-retro` skill SHALL write every lesson to Mycelium with `epistemic_status` set to `episode`.
The skill SHALL NOT automatically post a `gh issue comment` to the harness queue issue after writing a lesson.
Instead, the skill SHALL display a message informing the user how to manually add a queue entry if desired.

#### Scenario: Normal retro writes episode without queue comment

- **WHEN** `/pr-retro` completes and produces lessons that pass the Evidence Gate and Promotion Gate
- **THEN** each lesson is written to Mycelium with `epistemic_status = "episode"`, and no `gh issue comment` is executed

#### Scenario: User sees manual queue instruction

- **WHEN** `/pr-retro` writes a lesson to Mycelium
- **THEN** the skill output includes a message with the `gh issue comment` command the user can run manually to add the lesson to the harness queue

### Requirement: Emergency exception preserves fast track

The `/pr-retro` skill SHALL automatically post a `gh issue comment` to the harness queue when the lesson is classified as an emergency exception.
An emergency exception is defined as: a bleeding mechanical gap (a defect that causes silent wrong behavior with no existing guard) or a correction of factually wrong content in an existing rule or hook.

#### Scenario: Bleeding mechanical gap triggers auto-queue

- **WHEN** `/pr-retro` identifies a lesson as a bleeding mechanical gap (no existing hook, rule, or test prevents the failure)
- **THEN** the skill posts a `gh issue comment` to the harness queue issue with the emergency exception template

#### Scenario: Non-emergency lesson does not trigger auto-queue

- **WHEN** `/pr-retro` identifies a lesson that improves coverage but is not a bleeding mechanical gap or factual correction
- **THEN** the skill writes the lesson to Mycelium only, with no automatic `gh issue comment`

##### Example: emergency vs non-emergency classification

| Lesson description | Existing guard | Classification | Auto-queue? |
|---|---|---|---|
| `rm -rf` on tracked dir with no probe | No hook, no rule covers this path | Bleeding mechanical gap | Yes |
| Codex review cached stale output | Rule 13 documents the workaround | Coverage improvement | No |
| Rule 15 states wrong recovery command | Factually wrong existing content | Factual correction | Yes |
| New pattern observed across 2 PRs | No guard, but no silent failure | Observation, not emergency | No |

### Requirement: Nightly agent operates in dry-run mode

The `tasks/nightly_agent` CLI SHALL support a `--dry-run` flag on the `run` command.
When `--dry-run` is passed, the agent SHALL produce a digest markdown file in `.runtime/logs/` but SHALL NOT invoke `gh pr create` or any other GitHub write operation.
The `.runtime/schedules.json` entry for the nightly-self-improvement job SHALL include `--dry-run` in its arguments until the epistemic maturity model is validated.

#### Scenario: Dry-run produces digest without PR

- **WHEN** `uv run python -m tasks.nightly_agent run --dry-run` is executed
- **THEN** a digest file is written to `.runtime/logs/nightly-YYYY-MM-DD.md` and no `gh pr create` is invoked

#### Scenario: Dry-run reads Mycelium and GitHub normally

- **WHEN** `uv run python -m tasks.nightly_agent run --dry-run` is executed
- **THEN** the agent reads lessons from Mycelium and PR activity from GitHub as normal, only write operations are suppressed

### Requirement: Distill output is observation summary without rule draft

The `distill_service` SHALL produce output that contains only an observation statement, a list of supporting evidence lesson IDs, and recurrence metrics (distinct PR count, recurrence time span).
The `distill_service` SHALL NOT produce a rule draft, a target file path, or a patch-surface suggestion in its output.

#### Scenario: Distill candidate contains observation and evidence only

- **WHEN** `distill_service` produces a candidate from a cluster of 3+ lessons spanning 2+ PRs
- **THEN** the candidate output contains an `observation` string, an `evidence_ids` list, a `distinct_pr_count` integer, and a `recurrence_span_days` integer
- **THEN** the candidate output does NOT contain a `rule_draft`, `target_file`, or `patch_surface` field

##### Example: distill candidate shape

- **GIVEN** a cluster of lessons: L1 (PR #100, confidence 8), L2 (PR #105, confidence 7), L3 (PR #110, confidence 9)
- **WHEN** distill produces a candidate
- **THEN** output is:
  ```
  observation: "Codex review --base produces stale cached output when re-invoked with same SHA"
  evidence_ids: ["L1", "L2", "L3"]
  distinct_pr_count: 3
  recurrence_span_days: 14
  ```
  and NO `rule_draft` or `target_file` field exists

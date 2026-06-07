## ADDED Requirements

### Requirement: Entry inference from PR context

The `claude_agent` SHALL infer control log entries from PR context sources
(git log, PR diff, PR body) without requiring the developer to manually enumerate
every decision. At least one `autonomous_decision` entry MUST be inferred when the
PR contains agent-authored commits. Each inferred entry MUST contain the three
required fields: `category`, `summary`, and `user_requested`.

#### Scenario: infer-autonomous-decision -- agent infers autonomous_decision from git log

- **GIVEN** a PR with agent-authored commits where the commit messages reference
  a technical choice (e.g., "chose SQLite WAL mode for DB layer")
- **WHEN** the `claude_agent` runs the pr-control-log skill for that PR
- **THEN** the draft SHALL contain at least one entry with
  `category = autonomous_decision`
- **AND** the entry `summary` SHALL reference the technical decision observed in context
- **AND** `user_requested` SHALL be `0` for that entry

##### Example: autonomous decision inferred from commit

| Source | Inferred category | user_requested | Summary contains |
|--------|-------------------|----------------|-----------------|
| commit: "chose SQLite over Postgres for portability" | autonomous_decision | 0 | "SQLite" |
| PR body: "decided to skip integration tests for speed" | autonomous_decision | 0 | "integration tests" |
| commit: "added --force flag as requested by user" | autonomous_decision | 1 | "--force flag" |

#### Scenario: infer-multiple-categories -- agent infers entries across multiple categories

- **GIVEN** a PR diff that includes: a new untested assumption, a deliberate trade-off
  comment in code, and a verification step in the PR description
- **WHEN** the `claude_agent` processes all context sources
- **THEN** the draft SHALL contain entries with at least 2 distinct `category` values
  from the enum: `assumption`, `autonomous_decision`, `spec_deviation`, `tradeoff`,
  `irreversible_op`, `verification`, `rollback`

#### Scenario: infer-required-fields-present -- all inferred entries contain required fields

- **GIVEN** any PR context with at least one identifiable agent action
- **WHEN** the `claude_agent` produces the initial draft
- **THEN** every entry in the draft SHALL have a non-empty `category` field
- **AND** every entry SHALL have a non-empty `summary` field
- **AND** every entry SHALL have an explicit `user_requested` value of `0` or `1`
- **AND** the `category` value SHALL be one of the 7 valid enum values:
  `assumption`, `autonomous_decision`, `spec_deviation`, `tradeoff`,
  `irreversible_op`, `verification`, `rollback`

#### Scenario: infer-no-agent-commits -- no entries inferred when PR has no agent actions

- **GIVEN** a PR where all commits are authored by the human developer with no
  agent-attributed decisions in git log or PR body
- **WHEN** the `claude_agent` runs the pr-control-log skill
- **THEN** the draft MAY contain zero entries
- **AND** the agent SHALL inform the developer that no agent actions were detected
  rather than fabricating entries

---

### Requirement: Entry schema with 11 audit fields

The system SHALL store each control log entry with the following fields in the
`control_log_entries` table: `id`, `created_at`, `session_id`, `pr_number`,
`project`, `category`, `summary`, `evidence`, `user_requested`, `severity`,
`files_json`, `verification_status`, `test_type`, `handover_id`.
The `category` field SHALL be one of: `assumption`, `autonomous_decision`,
`spec_deviation`, `tradeoff`, `irreversible_op`, `verification`, `rollback`.

#### Scenario: write-minimal-entry -- CLI writes a single entry with required fields only

- **GIVEN** the CLI receives:
  `control-log add --pr 42 --category autonomous_decision --summary "Chose SQLite WAL mode" --user-requested 0`
- **WHEN** the command executes successfully
- **THEN** the system SHALL insert exactly one row into `control_log_entries`
- **AND** the output SHALL contain `✓ 已寫入 control log entry (id=` followed by a positive integer
- **AND** the inserted row SHALL have `pr_number = 42`,
  `category = "autonomous_decision"`, `user_requested = 0`

##### Example: minimal add variations

| pr_number | category           | summary              | user_requested | Expected output contains |
|-----------|--------------------|----------------------|----------------|--------------------------|
| 42        | autonomous_decision | Chose SQLite WAL mode | 0             | `id=` + positive integer |
| 42        | assumption         | Auth layer is stable | 1              | `id=` + positive integer |
| 7         | tradeoff           | Skip unit tests for speed | 0         | `id=` + positive integer |

#### Scenario: write-entry-with-all-optional-fields -- CLI writes entry with all 11 fields populated

- **GIVEN** the CLI receives all optional flags:
  `control-log add --pr 42 --category verification --summary "Ran smoke test"
  --user-requested 1 --evidence "pytest output" --severity low
  --files '["tasks/mycelium/cli.py"]' --verification-status verified
  --test-type unit --handover-id abc123 --project yibi-stack`
- **WHEN** the command executes
- **THEN** the system SHALL insert one row with all non-NULL values for every field
- **AND** the output SHALL contain `✓ 已寫入 control log entry (id=`

#### Scenario: optional-fields-null -- optional fields default to NULL when omitted

- **GIVEN** the CLI receives only the required fields:
  `control-log add --pr 5 --category assumption --summary "S" --user-requested 0`
- **WHEN** the command executes
- **THEN** the columns `evidence`, `severity`, `files_json`, `verification_status`,
  `test_type`, and `handover_id` SHALL be stored as `NULL` in the database

#### Scenario: invalid-category-rejected -- entry with invalid category is rejected

- **GIVEN** the CLI receives `--category unknown_value` which is not in the 7-value enum
- **WHEN** the command executes
- **THEN** the system SHALL exit with a non-zero exit code
- **AND** the error output SHALL indicate that the category value is invalid
- **AND** no row SHALL be inserted into `control_log_entries`

#### Scenario: idempotent-db-init -- init_db() is safe to call multiple times

- **GIVEN** `AgentsDB().init_db()` has already been called once on a database
- **WHEN** `AgentsDB().init_db()` is called a second time on the same database
- **THEN** the second call SHALL succeed without raising an exception
- **AND** the `control_log_entries` table SHALL NOT be duplicated or have its schema altered

---

### Requirement: User calibration loop

The system SHALL present the inferred draft to the developer and allow up to 3 rounds
of calibration. The developer MAY add, delete, or modify `summary` values in each round.
When the developer rejects an entry during calibration, that entry SHALL NOT be written
to the database. After finalization, the CLI SHALL output a confirmation with the count
of written entries.

#### Scenario: approve-on-first-round -- developer approves draft without corrections

- **GIVEN** the `claude_agent` presents a draft with 3 inferred entries
- **WHEN** the developer confirms the draft in round 1
- **THEN** the system SHALL write all 3 entries to `control_log_entries`
- **AND** the CLI SHALL output `✓ 已寫入 3 筆 entries`
- **AND** no further calibration prompt SHALL be shown

#### Scenario: reject-entry-not-written -- rejected entry is not persisted

- **GIVEN** the `claude_agent` presents a draft containing an entry E1
- **WHEN** the developer explicitly rejects E1 during calibration
- **THEN** E1 SHALL NOT be inserted into `control_log_entries`
- **AND** the final count in the CLI output SHALL NOT include E1

#### Scenario: modify-summary-then-approve -- developer corrects summary in round 2

- **GIVEN** the `claude_agent` presents a draft in round 1
- **WHEN** the developer requests a summary correction for one entry (round 1)
- **AND** the agent updates the draft and presents it again (round 2)
- **AND** the developer approves in round 2
- **THEN** the system SHALL write the corrected entry with the updated summary
- **AND** the CLI SHALL output `✓ 已寫入 N 筆 entries` where N equals the approved count

#### Scenario: exactly-three-rounds -- calibration completes on the 3rd round

- **GIVEN** the developer requests corrections in rounds 1 and 2
- **WHEN** the developer approves the draft in round 3 (the last allowed round)
- **THEN** the system SHALL finalize and write entries normally
- **AND** the CLI SHALL output `✓ 已寫入 N 筆 entries`
- **AND** no "exceeded limit" message SHALL be shown (round 3 is within the allowed limit)

#### Scenario: exceed-three-rounds-prompt -- system asks to finalize or abort after 3 rounds

- **GIVEN** the developer has requested corrections in rounds 1, 2, and 3 without approving
- **WHEN** the calibration round count reaches 4 (exceeds the limit of 3)
- **THEN** the system SHALL NOT proceed to write entries automatically
- **AND** the system SHALL ask the developer whether to finalize with the current draft state
  or abort entirely
- **AND** the message SHALL explicitly state that the 3-round calibration limit has been reached

##### Example: calibration round tracking

| Round | Developer action | System response |
|-------|-----------------|-----------------|
| 1 | requests summary correction | updates draft, presents round 2 |
| 2 | requests entry deletion | updates draft, presents round 3 |
| 3 | requests category change | updates draft, presents choice: finalize or abort |
| finalize chosen | — | writes current draft entries, outputs count |
| abort chosen | — | writes no entries, exits with message |

#### Scenario: calibration-abort -- developer chooses abort after exceeding limit

- **GIVEN** calibration has exceeded 3 rounds and the system has presented the finalize-or-abort choice
- **WHEN** the developer chooses to abort
- **THEN** no entries SHALL be written to `control_log_entries`
- **AND** the CLI SHALL output a message confirming that no entries were written

#### Scenario: add-entry-during-calibration -- developer adds a new entry not in original draft

- **GIVEN** the `claude_agent` presents a draft in round 1
- **WHEN** the developer requests that a new entry (not inferred by the agent) be added
- **THEN** the agent SHALL include the developer-specified entry in the updated draft
- **AND** the new entry SHALL have `user_requested = 1` since the developer explicitly requested it

---

### Requirement: Markdown artifact output

After entries are finalized for a PR, the system SHALL write a human-readable
markdown artifact to `.runtime/control-logs/pr-<N>.md`. The artifact SHALL contain
sections 0 through 11 covering: language/audience, task goals, explicit user requests,
assumptions, autonomous decisions, spec deviations, change traceability table,
trade-offs, irreversible ops checklist, verification results, rollback plan, and
human review summary. The artifact SHALL NOT be committed to git because `.runtime/`
is listed in `.gitignore`.

#### Scenario: artifact-created-at-correct-path -- artifact file exists at expected path after finalization

- **GIVEN** the developer has finalized entries for PR number 42
- **WHEN** the pr-control-log skill completes
- **THEN** the file `.runtime/control-logs/pr-42.md` SHALL exist on disk
- **AND** the file SHALL be readable as valid UTF-8 markdown

#### Scenario: artifact-contains-all-sections -- artifact includes sections 0 through 11 in order

- **GIVEN** a PR with at least one entry of each major category
- **WHEN** the artifact is generated
- **THEN** the artifact SHALL contain 12 section headings numbered 0 through 11
- **AND** the sections SHALL appear in ascending numerical order
- **AND** no required section SHALL be omitted even if no entries of that type were captured

#### Scenario: artifact-not-committed -- artifact path is gitignored

- **GIVEN** the artifact has been written to `.runtime/control-logs/pr-42.md`
- **WHEN** `git status` is run in the repository root
- **THEN** the file SHALL NOT appear as an untracked or modified file
- **AND** `.runtime/` SHALL be present in the project's `.gitignore`

#### Scenario: artifact-path-uses-pr-number -- different PRs produce distinct artifact files

- **GIVEN** the skill is run for PR 10 and then for PR 20
- **WHEN** both runs complete
- **THEN** `.runtime/control-logs/pr-10.md` SHALL exist
- **AND** `.runtime/control-logs/pr-20.md` SHALL exist
- **AND** the two files SHALL be distinct (different `pr_number` in content)

#### Scenario: artifact-created-even-with-minimal-entries -- artifact is written when only 1 entry exists

- **GIVEN** the developer finalizes a draft containing exactly 1 entry
- **WHEN** the skill writes the artifact
- **THEN** `.runtime/control-logs/pr-<N>.md` SHALL exist and contain all 12 sections
- **AND** sections with no applicable entries SHALL contain an explicit note (e.g., "N/A"
  or "No entries of this type") rather than being silently empty

---

### Requirement: Entry count confirmation output

After all approved entries are written to the database, the CLI SHALL output a
confirmation message that includes the count of written entries. This output
SHALL accurately reflect only the entries that were actually persisted.

#### Scenario: count-matches-written-entries -- output count equals persisted row count

- **GIVEN** the developer approved 5 entries during calibration (rejected 2)
- **WHEN** the system writes the 5 approved entries
- **THEN** the CLI output SHALL contain `✓ 已寫入 5 筆 entries`
- **AND** a subsequent `control-log show --pr N` SHALL list exactly 5 entries

#### Scenario: zero-entries-after-all-rejected -- output reflects zero when all entries rejected

- **GIVEN** the developer rejected all inferred entries during calibration
- **WHEN** calibration finishes with no approved entries
- **THEN** the CLI output SHALL contain `✓ 已寫入 0 筆 entries`
- **AND** no rows SHALL be inserted into `control_log_entries` for that PR

##### Example: count output variations

| Approved | Rejected | Expected CLI output |
|----------|----------|---------------------|
| 5 | 2 | `✓ 已寫入 5 筆 entries` |
| 1 | 0 | `✓ 已寫入 1 筆 entries` |
| 0 | 3 | `✓ 已寫入 0 筆 entries` |

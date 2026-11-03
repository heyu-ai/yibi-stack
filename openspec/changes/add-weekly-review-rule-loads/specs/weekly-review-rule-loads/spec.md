## Purpose

The weekly-review-rule-loads capability defines how harness-weekly-review measures whether each rule file and each instruction file (root or subdirectory `CLAUDE.md` or `AGENTS.md`) actually entered a session's context. It exists because rule cost (characters, always-loaded or path-scoped) does not show whether a path-scoped rule ever triggers, and a wrong `paths:` glob fails silently.

## ADDED Requirements

### Requirement: Rule loads are counted per session from transcript attachments

The collector SHALL count, for each repo-relative `.claude/rules/**/*.md` file and each `CLAUDE.md` or `AGENTS.md` file, the number of distinct sessions in the observation window whose transcript contains an `instructions` attachment listing that path or a `nested_memory` attachment for that path. A session is in the observation window when at least one of its events has a timestamp at or after the window start; all attachments of such a session SHALL be counted, regardless of the attachment's own timestamp. Paths under the main checkout and under `.claude/worktrees/<name>/` SHALL map to the same repo-relative path, also when `<name>` contains `/`. Instruction files whose type is `User` SHALL NOT be counted, and paths outside the repository SHALL NOT be counted.

#### Scenario: worktree-and-main-count-as-one-file

- **WHEN** one session loads `.claude/rules/a.md` from the main checkout and another session loads it from `.claude/worktrees/feat/`
- **THEN** the snapshot records `.claude/rules/a.md` with 2 sessions

#### Scenario: worktree-name-with-slash

- **WHEN** a session in the worktree `.claude/worktrees/feat/x/` loads `.claude/rules/always.md` and the worktree root `CLAUDE.md`
- **THEN** the snapshot records `.claude/rules/always.md` with 1 session and `CLAUDE.md` with 1 session, and records no `x/CLAUDE.md`

#### Scenario: rule-in-rules-subdirectory

- **WHEN** a session loads `.claude/rules/sub/deep.md`
- **THEN** the snapshot records `.claude/rules/sub/deep.md` with 1 session

#### Scenario: session-started-before-window

- **WHEN** a session's `instructions` attachment is before the window start and its `nested_memory` attachment for a path-scoped rule is inside the window
- **THEN** the session counts as a session with project instructions, the path-scoped rule is counted for it, and no rule share exceeds 100%

#### Scenario: repeated-load-in-one-session

- **WHEN** one session reloads the same rule file more than once in the window
- **THEN** that rule file is counted once for that session

#### Scenario: user-level-file-inside-repo

- **WHEN** an `instructions` attachment lists a file of type `User` whose path is inside the repository
- **THEN** that file is not counted

### Requirement: The load-share denominator excludes sessions that loaded no project instructions

The snapshot SHALL record the number of sessions in the window, the number of those sessions with project instructions, and both numbers per `entrypoint`. A session has project instructions when an `instructions` attachment lists at least one file that is not of type `User` and whose path is inside the repository. Rule and instruction-file counts SHALL include only sessions with project instructions; the snapshot SHALL record as `excluded_sessions` the number of other sessions in the window that loaded a rule or instruction file. The report SHALL compute each rule's share against the number of sessions with project instructions.

#### Scenario: sdk-session-without-instructions

- **WHEN** the window contains 2 `cli` sessions that load project instructions and 1 `sdk-py` session that loads none
- **THEN** the snapshot records 3 sessions, 2 sessions with instructions, `cli` as 2 of 2, and `sdk-py` as 0 of 1

#### Scenario: user-only-instructions-not-in-denominator

- **WHEN** a session's `instructions` attachment lists only `User` files and the session loads a path-scoped rule through `nested_memory`
- **THEN** that session is not counted in the sessions with instructions, the path-scoped rule is not counted for it, and `excluded_sessions` is 1

### Requirement: Rule-load measurement is incomplete when the transcript format cannot be trusted

The rule-load source record SHALL be incomplete when any transcript file or directory cannot be read, any line is not a valid JSON object, an attachment path is not a string, an `instructions` attachment's `files` is not a list, no transcript exists, transcript files exist but fewer than `TRANSCRIPT_MIN_EVENTS` events in the window have a timestamp, or the rules source is incomplete. When the window contains at least one session with entrypoint `cli`, the source SHALL also be incomplete if no `instructions` attachment exists or none of the always-loaded rules has a session. When only some always-loaded rules have zero sessions, the source SHALL stay complete and the snapshot SHALL list those rules in `always_missing`.

#### Scenario: renamed-instructions-attachment

- **WHEN** the window contains a `cli` session and its instruction attachment has a type other than `instructions`
- **THEN** the rule-load source record has `complete` false

#### Scenario: newly-added-always-loaded-rule

- **WHEN** the window contains `cli` sessions that load `.claude/rules/always.md`, and the always-loaded rule `.claude/rules/new.md` has zero sessions
- **THEN** the rule-load source record has `complete` true, `always_missing` is `.claude/rules/new.md`, and the report lists it as an always-loaded rule with zero sessions this period

#### Scenario: sdk-only-window

- **WHEN** every session in the window has entrypoint `sdk-py` and none loads project instructions
- **THEN** the rule-load source record has `complete` true

#### Scenario: unreadable-or-truncated-transcript

- **WHEN** a transcript file cannot be read, or a transcript line is not a valid JSON object
- **THEN** the rule-load source record has `complete` false

#### Scenario: no-events-in-window

- **WHEN** transcript files exist but their events have no timestamp, all timestamps are before the window start, or only 2 events are inside the window
- **THEN** the rule-load source record has `complete` false

#### Scenario: malformed-attachment-shape

- **WHEN** a `nested_memory` attachment's `path` is not a string, or an `instructions` attachment's `files` is not a list
- **THEN** the rule-load source record has `complete` false

### Requirement: The report distinguishes zero loads from unmeasured

The report SHALL list every rule file on disk, including files with zero sessions, and every loaded rule file that is not in the rules inventory. When the rule-load source record is incomplete, the report SHALL state that rule loads are unmeasured, SHALL point to the incomplete-measurement section, and SHALL NOT print the rule-load table. When the snapshot has no rule-load section, the report SHALL state that the snapshot predates this measurement. When at least `TRANSCRIPT_MIN_EVENTS` sessions have project instructions and the snapshot records zero `nested_memory` events, the report SHALL show path-scoped rule counts as unmeasured instead of zero. When no session has project instructions, the report SHALL show the share as `-`.

#### Scenario: zero-load-rule-is-listed

- **WHEN** a rule file exists on disk and no session in the window loaded it
- **THEN** the report lists that rule file with 0 sessions

#### Scenario: incomplete-source-hides-table

- **WHEN** the snapshot's rule-load source record has `complete` false
- **THEN** the report section states that rule loads are unmeasured, points to the incomplete-measurement section, and contains no rule-load table

#### Scenario: snapshot-before-this-change

- **WHEN** the snapshot has no `rule_loads` section
- **THEN** the report section states that the snapshot predates this measurement and has no load records

#### Scenario: nested-memory-drift-shows-unmeasured

- **WHEN** 3 sessions have project instructions and the snapshot records zero `nested_memory` events
- **THEN** the report shows the path-scoped rule's session count and share as unmeasured and explains that no `nested_memory` event was seen

#### Scenario: render-without-project-instruction-sessions

- **WHEN** the rule-load source record is complete and no session has project instructions
- **THEN** the report lists each always-loaded rule with 0 sessions and share `-`

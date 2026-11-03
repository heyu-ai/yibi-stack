## Purpose

The weekly-review-rule-loads capability defines how harness-weekly-review measures whether each rule file and each subdirectory instruction file actually entered a session's context. It exists because rule cost (characters, always-loaded or path-scoped) does not show whether a path-scoped rule ever triggers, and a wrong `paths:` glob fails silently.

## ADDED Requirements

### Requirement: Rule loads are counted per session from transcript attachments

The collector SHALL count, for each repo-relative `.claude/rules/*.md` file and each `CLAUDE.md` or `AGENTS.md` file, the number of distinct sessions in the observation window whose transcript contains an `instructions` attachment listing that path or a `nested_memory` attachment for that path. Paths under the main checkout and under `.claude/worktrees/<name>/` SHALL map to the same repo-relative path. Instruction files whose type is `User` SHALL NOT be counted, and paths outside the repository SHALL NOT be counted.

#### Scenario: worktree-and-main-count-as-one-file

- **WHEN** one session loads `.claude/rules/a.md` from the main checkout and another session loads it from `.claude/worktrees/feat/`
- **THEN** the snapshot records `.claude/rules/a.md` with 2 sessions

#### Scenario: repeated-load-in-one-session

- **WHEN** one session reloads the same rule file more than once in the window
- **THEN** that rule file is counted once for that session

#### Scenario: user-level-file-inside-repo

- **WHEN** an `instructions` attachment lists a file of type `User` whose path is inside the repository
- **THEN** that file is not counted

### Requirement: The load-share denominator excludes sessions that loaded no project instructions

The snapshot SHALL record the number of sessions in the window, the number of those sessions that have an `instructions` attachment, and both numbers per `entrypoint`. The report SHALL compute each rule's share against the number of sessions that have an `instructions` attachment.

#### Scenario: sdk-session-without-instructions

- **WHEN** the window contains 2 `cli` sessions that load project instructions and 1 `sdk-py` session that loads none
- **THEN** the snapshot records 3 sessions, 2 sessions with instructions, `cli` as 2 of 2, and `sdk-py` as 0 of 1

### Requirement: Rule-load measurement is incomplete when the transcript format cannot be trusted

The rule-load source record SHALL be incomplete when any transcript file cannot be read, any line is not valid JSON, no transcript exists, or the rules source is incomplete. When the window contains at least one session whose entrypoint includes `cli`, the source SHALL also be incomplete if no `instructions` attachment exists or any always-loaded rule has zero sessions.

#### Scenario: renamed-instructions-attachment

- **WHEN** the window contains a `cli` session and its instruction attachment has a type other than `instructions`
- **THEN** the rule-load source record has `complete` false

#### Scenario: sdk-only-window

- **WHEN** every session in the window has entrypoint `sdk-py` and none loads project instructions
- **THEN** the rule-load source record has `complete` true

#### Scenario: unreadable-or-truncated-transcript

- **WHEN** a transcript file cannot be read, or a transcript line is not valid JSON
- **THEN** the rule-load source record has `complete` false

### Requirement: The report distinguishes zero loads from unmeasured

The report SHALL list every rule file on disk, including files with zero sessions, and every loaded rule file that no longer exists on disk. When the rule-load source record is incomplete or absent, the report SHALL state that rule loads are unmeasured and SHALL NOT print the rule-load table.

#### Scenario: zero-load-rule-is-listed

- **WHEN** a rule file exists on disk and no session in the window loaded it
- **THEN** the report lists that rule file with 0 sessions

#### Scenario: incomplete-source-hides-table

- **WHEN** the snapshot's rule-load source record has `complete` false
- **THEN** the report section states that rule loads are unmeasured and contains no rule-load table

#### Scenario: snapshot-before-this-change

- **WHEN** the snapshot has no `rule_loads` section
- **THEN** the report section states that rule loads are unmeasured

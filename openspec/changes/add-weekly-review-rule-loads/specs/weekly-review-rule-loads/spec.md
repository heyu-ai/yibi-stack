## Purpose

The weekly-review-rule-loads capability defines how harness-weekly-review measures whether each rule file and each instruction file (root or subdirectory `CLAUDE.md` or `AGENTS.md`) actually entered a session's context. It exists because rule cost (characters, always-loaded or path-scoped) does not show whether a path-scoped rule ever triggers, and a wrong `paths:` glob fails silently.

## ADDED Requirements

### Requirement: Rule loads are counted per session from transcript attachments

The collector SHALL count, for each repo-relative `.claude/rules/**/*.md` file (at the repository root or under a subproject such as `mobile/.claude/rules/`) and each `CLAUDE.md` or `AGENTS.md` file, the number of distinct sessions in the observation window whose transcript contains an `instructions` attachment listing that path or a `nested_memory` attachment for that path. A session is in the observation window when at least one of its events has a timestamp at or after the window start and at or before the window end; all attachments of such a session SHALL be counted, regardless of the attachment's own timestamp. Instruction files whose type is `User` SHALL NOT be counted, and paths outside the repository SHALL NOT be counted.

#### Scenario: worktree-and-main-count-as-one-file

- **WHEN** one session loads `.claude/rules/a.md` from the main checkout and another session loads it from `.claude/worktrees/feat/`
- **THEN** the snapshot records `.claude/rules/a.md` with 2 sessions

#### Scenario: rule-in-rules-subdirectory

- **WHEN** a session loads `.claude/rules/sub/deep.md`
- **THEN** the snapshot records `.claude/rules/sub/deep.md` with 1 session

#### Scenario: session-started-before-window

- **WHEN** a session's `instructions` attachment is before the window start and its `nested_memory` attachment for a path-scoped rule is inside the window
- **THEN** the session counts as a session with project instructions, the path-scoped rule is counted for it, and no rule share exceeds 100%

#### Scenario: window-has-an-end

- **WHEN** a session has events only after the window end
- **THEN** the session is not counted, and its events do not count toward the minimum number of events in the window

#### Scenario: repeated-load-in-one-session

- **WHEN** one session reloads the same rule file more than once in the window
- **THEN** that rule file is counted once for that session

#### Scenario: user-level-file-inside-repo

- **WHEN** an `instructions` attachment lists a file of type `User` whose path is inside the repository
- **THEN** that file is not counted

### Requirement: Worktree paths are resolved against authoritative worktree roots

The collector SHALL map a path under `.claude/worktrees/` to a repo-relative path by removing the longest known worktree name. Known worktree names SHALL come from `git worktree list --porcelain` entries under `<main>/.claude/worktrees/` and from directories under `<main>/.claude/worktrees/` that contain a `.git` entry; they SHALL NOT be inferred from transcript paths, with one exception. The exception: when a path that matches no known worktree name was read from a transcript under `<slug>--claude-worktrees-<X>/`, the collector SHALL add as a known worktree name the shortest `/`-separated prefix of the path after `.claude/worktrees/` whose characters, with every non-alphanumeric character replaced by `-`, equal `<X>`. The collector SHALL NOT apply this exception to paths read from the main repository's transcript directory, and SHALL NOT add a name when no prefix equals `<X>`. When the git command fails or a directory cannot be listed, the rule-load source record SHALL be incomplete. A worktree path that matches no known worktree name SHALL be resolved from its first `/.claude/rules/` segment when it is a rule path; any other such path SHALL NOT be counted and SHALL be counted in `unresolved_worktree_paths`, which the report shows when it is greater than zero.

#### Scenario: authoritative-worktree-roots

- **WHEN** the known worktree names are `feat` and `feat/x`, and a session loads `.claude/worktrees/feat/x/CLAUDE.md`
- **THEN** the path resolves to `CLAUDE.md`

#### Scenario: worktree-name-with-slash

- **WHEN** a session in the existing worktree `.claude/worktrees/feat/x/` loads `.claude/rules/always.md` and the worktree root `CLAUDE.md`
- **THEN** the snapshot records `.claude/rules/always.md` with 1 session and `CLAUDE.md` with 1 session, and records no `x/CLAUDE.md`

#### Scenario: subproject-rules-keep-their-path

- **WHEN** a session in the main checkout and a session in the worktree `wt` both load `mobile/.claude/rules/m.md` and `mobile/CLAUDE.md`
- **THEN** the snapshot records `mobile/.claude/rules/m.md` with 2 sessions and `mobile/CLAUDE.md` with 2 sessions, and records no `.claude/rules/m.md`

#### Scenario: deleted-worktree-counts-as-unresolved

- **WHEN** a session loads `.claude/rules/always.md` and `CLAUDE.md` from `.claude/worktrees/feat/x/`, `feat/x` is not a known worktree name, and no prefix of the path normalizes to the slug of the transcript directory the session was read from
- **THEN** the snapshot records `.claude/rules/always.md` with 1 session, records no `CLAUDE.md` and no `x/CLAUDE.md`, and `unresolved_worktree_paths` counts the unresolved path

#### Scenario: deleted-worktree-root-from-transcript-dir

- **WHEN** the deleted worktree `feat/x` is not a known worktree name, and a session read from `<slug>--claude-worktrees-feat-x/` loads `.claude/worktrees/feat/x/CLAUDE.md` and `.claude/worktrees/feat/x/backend/CLAUDE.md`
- **THEN** the snapshot records `CLAUDE.md` and `backend/CLAUDE.md` with 1 session each, `unresolved_worktree_paths` is 0, and the same paths read from the main repository's transcript directory stay unresolved

#### Scenario: roots-lookup-failure-is-incomplete

- **WHEN** `git worktree list` fails while the collector looks up worktree names
- **THEN** the rule-load source record has `complete` false and the error is returned as a warning

### Requirement: The load-share denominator excludes sessions that loaded no project instructions

The snapshot SHALL record the number of sessions in the window, the number of those sessions with project instructions, and both numbers per `entrypoint`. A session has project instructions when an `instructions` attachment lists at least one file that is not of type `User` and whose path is inside the repository. Rule and instruction-file counts SHALL include only sessions with project instructions; the snapshot SHALL record as `excluded_sessions` the number of other sessions in the window that loaded a rule or instruction file. The report SHALL compute each rule's share against the number of sessions with project instructions.

#### Scenario: sdk-session-without-instructions

- **WHEN** the window contains 2 `cli` sessions that load project instructions and 1 `sdk-py` session that loads none
- **THEN** the snapshot records 3 sessions, 2 sessions with instructions, `cli` as 2 of 2, and `sdk-py` as 0 of 1

#### Scenario: user-only-instructions-not-in-denominator

- **WHEN** a session's `instructions` attachment lists only `User` files and the session loads a path-scoped rule through `nested_memory`
- **THEN** that session is not counted in the sessions with instructions, the path-scoped rule is not counted for it, and `excluded_sessions` is 1

#### Scenario: out-of-repo-instructions-not-in-denominator

- **WHEN** a session's `instructions` attachment lists only the `Project` file `/elsewhere/CLAUDE.md` outside the repository and the session loads a path-scoped rule through `nested_memory`
- **THEN** that session is not counted in the sessions with instructions, the path-scoped rule is not counted for it, and `excluded_sessions` is 1

### Requirement: Rule-load measurement is incomplete when the transcript format cannot be trusted

The rule-load source record SHALL be incomplete when any transcript file or directory cannot be read, any line is not a valid JSON object, an `attachment` event's `attachment` is not an object, an attachment path is not a string, an `instructions` attachment's `files` is missing or not a list, an item of `files` is not an object, no transcript exists, transcript files exist but fewer than `TRANSCRIPT_MIN_EVENTS` events in the window have a timestamp, worktree names cannot be listed, or the rules source is incomplete. When the window contains at least one session with entrypoint `cli`, the source SHALL also be incomplete if no `instructions` attachment exists, or if the checkout has always-loaded rules and no file listed by an `instructions` attachment in the window resolves to a `.claude/rules/**/*.md` path. This check SHALL NOT compare against the names of the checkout's always-loaded rules. Always-loaded rules of the checkout with zero sessions SHALL be listed in `always_missing` and SHALL NOT make the source incomplete. Read failures, malformed lines and directory listing errors SHALL be recorded in the source record but SHALL NOT be returned as warnings, because the transcript-block collector already returns them for the same files.

#### Scenario: renamed-instructions-attachment

- **WHEN** the window contains a `cli` session and its instruction attachment has a type other than `instructions`
- **THEN** the rule-load source record has `complete` false

#### Scenario: newly-added-always-loaded-rule

- **WHEN** the window contains `cli` sessions that load `.claude/rules/always.md`, and the always-loaded rule `.claude/rules/new.md` has zero sessions
- **THEN** the rule-load source record has `complete` true, `always_missing` is `.claude/rules/new.md`, and the report lists it as an always-loaded rule with zero sessions this period

#### Scenario: control-ignores-checkout-rule-names

- **WHEN** the window contains a `cli` session that loads `.claude/rules/old.md` through `instructions`, and the checkout's only always-loaded rule is `.claude/rules/new.md`
- **THEN** the rule-load source record has `complete` true and `always_missing` is `.claude/rules/new.md`

#### Scenario: user-only-instructions-do-not-trip-control

- **WHEN** the window contains a `cli` session whose `instructions` attachment lists only a `User` file, and the checkout has no always-loaded rule
- **THEN** the rule-load source record has no error about a missing `instructions` attachment and has `complete` true

#### Scenario: sdk-only-window

- **WHEN** every session in the window has entrypoint `sdk-py` and none loads project instructions
- **THEN** the rule-load source record has `complete` true and `always_missing` is empty

#### Scenario: unreadable-or-truncated-transcript

- **WHEN** a transcript file cannot be read, or a transcript line is not a valid JSON object
- **THEN** the rule-load source record has `complete` false, the rule-load collector returns no warning for it, and the collect snapshot's warnings are not empty

#### Scenario: no-events-in-window

- **WHEN** transcript files exist but their events have no timestamp, all timestamps are before the window start, or only 2 events are inside the window
- **THEN** the rule-load source record has `complete` false

#### Scenario: malformed-attachment-shape

- **WHEN** a `nested_memory` attachment's `path` is not a string, or an `instructions` attachment's `files` is not a list
- **THEN** the rule-load source record has `complete` false

#### Scenario: attachment-shape-variants-are-incomplete

- **WHEN** an `attachment` event's `attachment` is a string or a list, an `instructions` attachment has no `files` key or has `files` equal to `{}` or `""`, an item of `files` is not an object, or an item's `path` is not a string
- **THEN** the rule-load source record has `complete` false and the shape error is returned as a warning

### Requirement: The report distinguishes zero loads from unmeasured

The report SHALL list every rule file on disk, including files with zero sessions, and every loaded rule file that is not in the rules inventory. When the rule-load source record is incomplete, the report SHALL state that rule loads are unmeasured, SHALL point to the incomplete-measurement section, and SHALL NOT print the rule-load table. When the snapshot has no rule-load section, the report SHALL state that the snapshot predates this measurement. The snapshot SHALL record as `nested_memory_events` only `nested_memory` events whose path resolves to a rule or instruction file in the repository, and SHALL record as `nested_unresolved_events` the events whose path does not resolve. When at least `RULE_LOAD_MIN_SESSIONS` sessions have project instructions and `nested_memory_events` is zero, the report SHALL show path-scoped rule counts as unmeasured instead of zero, regardless of `nested_unresolved_events`. When at least one but fewer than `RULE_LOAD_MIN_SESSIONS` sessions have project instructions and `nested_memory_events` is zero, the report SHALL state that the zero counts of path-scoped rules are not confirmed by the control. When no session has project instructions, the report SHALL show the share as `-`.

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
- **THEN** the report shows the path-scoped rule's session count and share as unmeasured and explains that no resolvable `nested_memory` event was seen

#### Scenario: unresolved-nested-paths-show-unmeasured

- **WHEN** 3 sessions have project instructions and every `nested_memory` path is relative, a `file://` URI, or outside the repository
- **THEN** `nested_memory_events` is 0, `nested_unresolved_events` counts those events, and the report shows the path-scoped rule's session count and share as unmeasured

#### Scenario: render-without-project-instruction-sessions

- **WHEN** the rule-load source record is complete and no session has project instructions
- **THEN** the report lists each always-loaded rule with 0 sessions and share `-`

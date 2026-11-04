## Purpose

The weekly-review-rule-loads capability defines how harness-weekly-review measures whether each rule file and each instruction file (root or subdirectory `CLAUDE.md` or `AGENTS.md`) actually entered a session's context. It exists because rule cost (characters, always-loaded or path-scoped) does not show whether a path-scoped rule ever triggers, and a wrong `paths:` glob fails silently. The measurement does not detect transcript format drift automatically; it records raw counters so that a human can compare them with the previous week.

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

- **WHEN** one session reloads the same rule file more than once in the window, or two sessions in one transcript file each have events without a `uuid`
- **THEN** that rule file is counted once for each session, and events without a `uuid` in different sessions are not merged into one event

#### Scenario: user-level-file-inside-repo

- **WHEN** an `instructions` attachment lists a file of type `User` whose path is inside the repository
- **THEN** that file is not counted

### Requirement: Worktree paths are resolved only against listed worktree roots

The collector SHALL map a path under `.claude/worktrees/` to a repo-relative path by removing the longest known worktree name. Known worktree names SHALL come only from `git worktree list --porcelain` entries under `<main>/.claude/worktrees/` (which MAY contain `/`) and from first-level directories directly under `<main>/.claude/worktrees/` that contain a `.git` entry and whose name does not start with `.`. The collector SHALL NOT search deeper directories, and SHALL NOT infer worktree names from transcript paths, transcript directory names, or `/.claude/rules/` segments. When the git command fails, or `.claude/worktrees/` or one of its entries cannot be read, the rule-load source record SHALL be incomplete. A path under `.claude/worktrees/` that matches no known worktree name SHALL NOT be counted as a rule, an instruction file, a project instruction, or an unresolved `nested_memory` event; it SHALL be counted only in `unresolved_worktree_paths`.

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

- **WHEN** a session read from `<slug>--claude-worktrees-feat-x/` loads `.claude/rules/always.md`, `CLAUDE.md` and `docs/CLAUDE.md` from `.claude/worktrees/feat/x/`, and `feat/x` is not a known worktree name
- **THEN** the snapshot records no rule and no instruction file, the session is not a session with project instructions, `nested_unresolved_events` is 0, and `unresolved_worktree_paths` is 3

#### Scenario: first-level-worktree-listing

- **WHEN** `.claude/worktrees/` contains `walked/.git`, `old/vendor/lib/.git`, `.cache/.git` and `plain/sub/`, and git lists the worktrees `outer` and `outer/inner`
- **THEN** the known worktree names are `outer`, `outer/inner` and `walked`

#### Scenario: roots-lookup-failure-is-incomplete

- **WHEN** `git worktree list` fails, or `.claude/worktrees/` cannot be listed, while the collector looks up worktree names
- **THEN** the rule-load source record has `complete` false, the error is returned as a warning, and the collect snapshot's warnings contain it

### Requirement: The load-share denominator excludes sessions that loaded no project instructions

The snapshot SHALL record the number of sessions in the window, the number of those sessions with project instructions, and both numbers per `entrypoint`. A session has project instructions when an `instructions` attachment lists at least one file that is not of type `User` and whose path resolves inside the repository. Rule and instruction-file counts SHALL include only sessions with project instructions; the snapshot SHALL record as `excluded_sessions` the number of other sessions in the window that loaded a rule or instruction file. The report SHALL compute each rule's share against the number of sessions with project instructions.

#### Scenario: sdk-session-without-instructions

- **WHEN** the window contains 2 `cli` sessions that load project instructions and 1 `sdk-py` session that loads none
- **THEN** the snapshot records 3 sessions, 2 sessions with instructions, `cli` as 2 of 2, and `sdk-py` as 0 of 1

#### Scenario: user-only-instructions-not-in-denominator

- **WHEN** a session's `instructions` attachment lists only `User` files and the session loads a path-scoped rule through `nested_memory`
- **THEN** that session is not counted in the sessions with instructions, the path-scoped rule is not counted for it, and `excluded_sessions` is 1

#### Scenario: out-of-repo-instructions-not-in-denominator

- **WHEN** a session's `instructions` attachment lists only the `Project` file `/elsewhere/CLAUDE.md` outside the repository and the session loads a path-scoped rule through `nested_memory`
- **THEN** that session is not counted in the sessions with instructions, the path-scoped rule is not counted for it, and `excluded_sessions` is 1

### Requirement: The snapshot records raw counters for human comparison

The snapshot SHALL record `instructions_events`, the number of `instructions` attachments in all sessions in the window, including attachments that list only `User` files or files outside the repository. The snapshot SHALL record as `nested_memory_events` the `nested_memory` events of sessions with project instructions whose path resolves to a rule or instruction file in the repository, and as `nested_unresolved_events` the events of those sessions whose path is a string that does not resolve inside the repository, excluding paths counted in `unresolved_worktree_paths`. Both event counters SHALL be deduplicated by event `uuid`; an event without a `uuid` SHALL be identified by its session, transcript file and line number. The snapshot SHALL also record `unresolved_worktree_paths`, `excluded_sessions` and `always_missing`. The collector SHALL NOT use any of these counters to decide that the source is incomplete.

#### Scenario: instructions-events-count-every-attachment

- **WHEN** the window contains one `cli` session whose only `instructions` attachment lists only a `User` file
- **THEN** `instructions_events` is 1, the session is not a session with project instructions, and the rule-load source record has `complete` true

#### Scenario: unresolved-nested-paths-are-counted

- **WHEN** 3 sessions have project instructions and every `nested_memory` path is relative, a `file://` URI, or outside the repository
- **THEN** `nested_memory_events` is 0, `nested_unresolved_events` counts those events, the rule-load source record has `complete` true, and the report shows the path-scoped rule with 0 sessions and both counters in the header

### Requirement: Rule-load measurement is incomplete only for listed read and shape failures

The rule-load source record SHALL be incomplete only when one of these conditions holds:

- a transcript file or directory cannot be read;
- a line is not a valid JSON object;
- an event of a session in the window has an `attachment` that is not an object, an attachment path that is not a string, an `instructions` attachment whose `files` is missing or not a list, or an item of `files` that is not an object;
- no transcript exists;
- transcript files exist but fewer than `TRANSCRIPT_MIN_EVENTS` events in the window have a timestamp;
- the rules source is incomplete;
- worktree names cannot be listed.

The collector SHALL NOT inspect attachment shapes of sessions outside the window. The collector SHALL NOT infer format drift from load counts, from `entrypoint` values, or from the absence of `instructions` or `nested_memory` events. Always-loaded rules of the checkout with zero sessions SHALL be listed in `always_missing` and SHALL NOT make the source incomplete. Every reason that makes the source incomplete SHALL be returned as a warning; the read-failure, malformed-line, directory-listing and missing-transcript reasons SHALL use the same text as the transcript-block collector, and the collect command SHALL drop a rule-load warning only when it is identical to a warning that the transcript-block collector returned in the same run.

#### Scenario: renamed-instructions-attachment-stays-complete

- **WHEN** the window contains a `cli` session and its instruction attachment has a type other than `instructions`
- **THEN** the rule-load source record has `complete` true, `instructions_events` is 0, and the report shows the notice that no `instructions` event was seen

#### Scenario: nested-drift-stays-complete

- **WHEN** 3 sessions have project instructions and every path-scoped load is recorded with an attachment type other than `nested_memory`
- **THEN** the rule-load source record has `complete` true, `nested_memory_events` is 0, and the report shows the path-scoped rule with 0 sessions

#### Scenario: newly-added-always-loaded-rule

- **WHEN** the window contains `cli` sessions that load `.claude/rules/always.md`, and the always-loaded rule `.claude/rules/new.md` has zero sessions
- **THEN** the rule-load source record has `complete` true, `always_missing` is `.claude/rules/new.md`, and the report header lists it

#### Scenario: sdk-only-window

- **WHEN** every session in the window has entrypoint `sdk-py` and none loads project instructions
- **THEN** the rule-load source record has `complete` true and `always_missing` is empty

#### Scenario: unreadable-or-truncated-transcript

- **WHEN** a transcript file cannot be read, a transcript line is not a valid JSON object, or a truncated line is appended to a transcript between the reads of the two collectors
- **THEN** the rule-load source record has `complete` false, the rule-load collector returns every reason as a warning, and the collect snapshot's warnings contain every reason

#### Scenario: no-events-in-window

- **WHEN** transcript files exist but their events have no timestamp, all timestamps are before the window start, or only 2 events are inside the window
- **THEN** the rule-load source record has `complete` false

#### Scenario: malformed-attachment-shape

- **WHEN** a `nested_memory` attachment's `path` is not a string, or an `instructions` attachment's `files` is not a list
- **THEN** the rule-load source record has `complete` false

#### Scenario: attachment-shape-variants-are-incomplete

- **WHEN** an `attachment` event's `attachment` is a string or a list, an `instructions` attachment has no `files` key or has `files` equal to `{}` or `""`, an item of `files` is not an object, or an item's `path` is not a string
- **THEN** the rule-load source record has `complete` false, the shape error is returned as a warning, and the collect snapshot's warnings contain it

#### Scenario: out-of-window-shape-errors-ignored

- **WHEN** a session whose events are all before the window start has an `instructions` attachment whose `files` is not a list
- **THEN** the rule-load source record has `complete` true; when the same attachment belongs to a session that also has an event inside the window, the source record has `complete` false

### Requirement: The report shows raw counters and distinguishes zero loads from unmeasured

When the rule-load source record is complete, the report SHALL list in the section header the number of sessions, the number of sessions with project instructions, both numbers per `entrypoint`, `instructions_events`, `nested_memory_events`, `nested_unresolved_events`, `unresolved_worktree_paths`, `excluded_sessions` and `always_missing`, followed by the fixed sentence `格式漂移不保證偵測：表頭的原始計數請與前一週比對`. When the snapshot has at least one session and `instructions_events` is 0, the report SHALL add a line that starts with `**注意**` and states that no `instructions` event was seen, so the table cannot show rule loads; this line SHALL NOT make the source incomplete. The report SHALL list every rule file on disk, including files with zero sessions, and every loaded rule file that is not in the rules inventory, labeled as possibly deleted, in a rules subdirectory, or in a subproject. When the rule-load source record is incomplete, the report SHALL state that rule loads are unmeasured, SHALL list the reasons from the source record in the same section, SHALL NOT refer to another section, and SHALL NOT print the raw counters or the rule-load table. When the snapshot has no rule-load section, the report SHALL state that the snapshot predates this measurement. When no session has project instructions, the report SHALL show the share as `-`.

#### Scenario: raw-counters-in-header

- **WHEN** the rule-load source record is complete
- **THEN** the report header lists every raw counter, lists `always_missing` or states that it is empty, and contains the fixed sentence about format drift

#### Scenario: no-instructions-events-notice

- **WHEN** the rule-load source record is complete, the snapshot has 2 sessions, and `instructions_events` is 0
- **THEN** the report contains a line that starts with `**注意**`; when `instructions_events` is greater than 0 or there is no session, the report does not contain it

#### Scenario: zero-load-rule-is-listed

- **WHEN** a rule file exists on disk and no session in the window loaded it
- **THEN** the report lists that rule file with 0 sessions

#### Scenario: incomplete-source-lists-reasons-inline

- **WHEN** the snapshot's rule-load source record has `complete` false with two errors
- **THEN** the report section states that rule loads are unmeasured, lists both errors in the section, does not refer to another section, and contains no raw counters and no rule-load table

#### Scenario: snapshot-before-this-change

- **WHEN** the snapshot has no `rule_loads` section
- **THEN** the report section states that the snapshot predates this measurement and has no load records

#### Scenario: render-without-project-instruction-sessions

- **WHEN** the rule-load source record is complete and no session has project instructions
- **THEN** the report lists each always-loaded rule with 0 sessions and share `-`

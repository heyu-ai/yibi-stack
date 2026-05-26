## ADDED Requirements

### Requirement: /lessons slash command replaces /recall

The `/lessons` slash command SHALL be the single entry point for querying and
writing typed lessons.
`commands/recall.md` SHALL be deleted; no alias or redirect SHALL be created.
The `~/.claude/commands/recall.md` symlink SHALL be removed as part of installation.

#### Scenario: /recall is absent after installation

- **WHEN** `make install` is run with the updated commands/
- **THEN** `~/.claude/commands/recall.md` does not exist

---

### Requirement: /lessons without arguments lists recent lessons

- **WHEN** `/lessons` is invoked with no arguments
- **THEN** the agent runs `lessons show --last 15 --include-legacy` and presents the results

#### Scenario: Default listing

- **WHEN** `/lessons`
- **THEN** up to 15 most recent lessons are shown, including legacy handover items

---

### Requirement: /lessons <keyword> searches for matching lessons

- **WHEN** `/lessons <keyword>` is invoked with a single keyword argument that is not
  a recognized subcommand (`find` or `ask`)
- **THEN** the agent runs `lessons search "<keyword>" --last 10 --include-legacy`

#### Scenario: Implicit find

- **WHEN** `/lessons dedup`
- **THEN** lessons matching "dedup" are shown

---

### Requirement: /lessons find supports explicit search with filter inference

- **WHEN** `/lessons find <keyword>` is invoked
- **THEN** the agent searches using `lessons search "<keyword>"` and infers filters
  from natural language signals in the arguments

The following natural language signals SHALL map to CLI flags:
- Tokens matching "雷/pitfall/踩過" SHALL add `--type pitfall`
- Tokens matching "確認過/可信/trusted" SHALL add `--trusted-only`
- Tokens matching "跨專案/cross-project" SHALL add `--cross-project`

#### Scenario: Explicit search with type filter

- **WHEN** `/lessons find 雷`
- **THEN** agent runs `lessons search "" --type pitfall`

#### Scenario: Trusted-only filter inferred

- **WHEN** `/lessons find 確認過的`
- **THEN** agent runs `lessons show --trusted-only`

---

### Requirement: /lessons ask interactively collects and writes a lesson

- **WHEN** `/lessons ask` is invoked, OR the argument contains trigger phrases
  such as "記下" or "我要寫一條"
- **THEN** the agent enters ask mode: it uses AskUserQuestion to collect
  `type`, `key`, `insight`, `confidence`, `source`, and optionally `skill`,
  then calls `lessons add` with the collected values

The agent SHALL confirm the written lesson id and trusted bit after writing.

#### Scenario: Ask mode writes a lesson

- **WHEN** `/lessons ask` is invoked and the user provides valid answers to all prompts
- **THEN** `lessons add` is executed with the provided values and the id is confirmed

#### Scenario: Trigger phrase activates ask mode

- **WHEN** `/lessons 記下這個`
- **THEN** agent enters ask mode as if `/lessons ask` was invoked

---

### Requirement: Skill integration contract for automatic lesson writes

The following skills SHALL call `lessons add` automatically when their respective
conditions are met:

| Skill | When | source | extra flags |
|-------|------|--------|-------------|
| `/pr-retro` | Each lesson after AskUserQuestion collects type+confidence | `user-stated` | `--skill pr-retro --retro-pr <N>` |
| `/handover` | Each item in lessons_learned[] at session end | `observed` | `--skill handover --handover-id <id>` |
| `/investigate` | After DEBUG REPORT, for each root-cause pattern | `observed` | `--skill investigate` |

These integrations are out of scope for Phase A (implemented in Phase B and D),
but the `lessons add` CLI contract established here SHALL remain stable.

#### Scenario: /pr-retro writes user-stated lesson

- **WHEN** `/pr-retro` finishes and the user confirms a lesson with type and confidence
- **THEN** `lessons add --source user-stated --skill pr-retro --retro-pr <N>` is called
  (Phase B)

#### Scenario: /handover writes observed lessons

- **WHEN** `/handover` completes and the session has lessons_learned entries
- **THEN** each entry is written via `lessons add --source observed --skill handover`
  (Phase B)

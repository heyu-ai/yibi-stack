# mycelium-bot-trust-mcp Specification

## Purpose

TBD - created by archiving change 'mycelium-layered-memory'. Update Purpose after archive.

## Requirements

### Requirement: source_bot field on memory records

Every LessonRecord and HandoverRecord SHALL include a `source_bot` field of type `str | None`,
identifying the agent type that wrote the record (e.g., `"claude"`, `"codex"`, `"gemini"`,
`"openab-planner"`).
The `source_bot` field SHALL be populated automatically from the current agent's `agent_type`
at write time.
Records created before this feature SHALL have `source_bot = None` and SHALL be treated as
`"unknown"` origin for trust scoring purposes.

#### Scenario: Stop hook populates source_bot

- **WHEN** the Stop hook saves a lesson during a Claude Code session
- **THEN** the new LessonRecord has `source_bot="claude"`

#### Scenario: Codex-authored lesson retains its source_bot

- **WHEN** Codex writes a lesson via `mycelium_save_preference` MCP tool
- **THEN** the new LessonRecord has `source_bot="codex"` and this value persists through
  subsequent reads by other agents

#### Scenario: Legacy records treated as unknown

- **WHEN** a LessonRecord has `source_bot=None` (pre-migration record)
- **THEN** the trust scoring system assigns it `bot_trust_weight=0.4` (unknown tier)

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

---
### Requirement: Bot trust scoring

The system SHALL compute a `bot_trust_weight` float for each lesson based on the lesson's
`source_bot` and the identity of the querying agent.
The four trust tiers and their weights SHALL be:

| Trust tier | Condition | weight |
|---|---|---|
| user_stated | lesson.source = "user-stated" | 1.0 |
| same_bot | lesson.source_bot == querying agent_type | 0.9 |
| trusted_other_bot | lesson.source_bot is in caller's trust list | 0.7 |
| unknown | all other cases | 0.4 |

The trust list SHALL be configurable in `~/.agents/config.json` under `mycelium.trusted_bots`,
defaulting to an empty list (only user_stated and same_bot apply by default).

#### Scenario: User-stated preference has highest weight

- **WHEN** a lesson has `source="user-stated"` regardless of `source_bot`
- **THEN** `bot_trust_weight=1.0` is assigned, regardless of which agent is querying

#### Scenario: Claude querying a Codex-authored lesson with trust list

- **WHEN** Claude queries lessons, the config has `mycelium.trusted_bots=["codex"]`,
  and a lesson has `source_bot="codex"` and `source="observed"`
- **THEN** `bot_trust_weight=0.7` is assigned

#### Scenario: Unknown source_bot assigned lowest weight

- **WHEN** a lesson has `source_bot="unknown-agent"` and the caller's config
  does not include it in `trusted_bots`
- **THEN** `bot_trust_weight=0.4` is assigned

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

---
### Requirement: Project scope automatic pin

The system SHALL automatically associate lessons and handovers with the current project by
resolving the working directory to a project identifier.
`tasks/mycelium/registry.py` SHALL resolve `cwd` to a project slug using git's
`rev-parse --show-toplevel` and normalizing the path to a slug.
The `mycelium handover-back` command SHALL default to project-scoped recall (only lessons
from the same project slug) and SHALL provide a `--global` flag to include all projects.

#### Scenario: Lesson auto-tagged with project scope

- **WHEN** an agent saves a lesson while the cwd is `/Users/me/projects/yibi-stack`
- **THEN** the LessonRecord has `project="yibi-stack"` (the repo name extracted from the path)

#### Scenario: handover-back defaults to project scope

- **WHEN** an agent calls `mycelium handover-back` from within the `yibi-stack` repo
- **THEN** only lessons with `project="yibi-stack"` are included in the recall output

#### Scenario: Global recall overrides project filter

- **WHEN** an agent calls `mycelium handover-back --global`
- **THEN** lessons from all projects are included in the recall output

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

---
### Requirement: MCP server exposes four tools

The system SHALL provide a `mycelium serve` command that starts a MCP stdio server.
The server SHALL implement four tools conforming to the MCP tool specification (JSON Schema input schemas):

1. `mycelium_search(query: str, limit: int = 10, mode: str = "hybrid") -> list[LessonSummary]`
   -- Returns lessons matching the query, sorted by `effective_weight` descending.
2. `mycelium_get_lesson(lesson_id: str) -> LessonRecord | null`
   -- Returns a single lesson by ID, or null if not found.
3. `mycelium_save_preference(content: str, tags: list[str] = []) -> str`
   -- Saves a new preference-type lesson and returns its lesson_id.
4. `mycelium_subscribe(event_type: str) -> SubscriptionToken`
   -- Subscribes the caller to new-lesson notifications for the given event_type.
   Returns a token; delivery mechanism is Phase 4 implementation detail.

The server SHALL identify the calling agent type from the MCP session metadata when available,
falling back to `"unknown"` if not present.

#### Scenario: External bot queries via MCP search

- **WHEN** a Codex agent calls `mycelium_search(query="squash merge pitfall", limit=5)`
  via the MCP server
- **THEN** the server returns up to 5 LessonSummary objects sorted by `effective_weight`,
  with `bot_trust_weight` computed using Codex as the querying agent

#### Scenario: MCP server saves cross-bot preference

- **WHEN** a Gemini agent calls `mycelium_save_preference(content="always use --no-ff merge")`
- **THEN** a new LessonRecord is created with `lesson_type="preference"`, `source_bot="gemini"`,
  and the returned lesson_id is a valid UUID string

#### Scenario: MCP get_lesson returns null for missing ID

- **WHEN** a caller calls `mycelium_get_lesson(lesson_id="nonexistent-uuid")`
- **THEN** the server returns `null` (not an error) in the MCP response

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

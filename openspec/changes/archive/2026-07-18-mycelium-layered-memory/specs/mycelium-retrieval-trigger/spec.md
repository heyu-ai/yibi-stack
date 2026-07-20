## ADDED Requirements

### Requirement: Three-layer input trigger

The system SHALL capture memory from the conversation context through three input trigger layers:

1. **Stop hook** (automatic, session end): The system SHALL scan the final conversation turn
   for lines matching `★ Memory:` prefix and save each as a new LessonRecord in `working` tier.
2. **PreCompact hook** (automatic, context pressure): When Claude Code is about to compact the
   context, the system SHALL summarize session insights and save them as LessonRecords before
   context is reduced.
3. **Agent manual** (on-demand): The `mycelium memory save` CLI subcommand SHALL allow an agent
   or user to save a lesson at any point during the session.

All three input paths SHALL produce a LessonRecord with `tier="working"` and `source_bot` set
to the current agent type.

#### Scenario: Stop hook extracts starred memories

- **WHEN** a session ends and the last assistant turn contains `★ Memory: prefer explicit refspec`
- **THEN** a new LessonRecord is created with `content="prefer explicit refspec"` and `tier="working"`

#### Scenario: PreCompact hook saves before context reduction

- **WHEN** Claude Code triggers a PreCompact event
- **THEN** the system calls `mycelium memory save --tier working` with a structured summary of
  the session's key insights before the context is compacted

#### Scenario: Agent manually saves a lesson

- **WHEN** an agent runs `mycelium memory save --tag pitfall "never cherry-pick after squash merge"`
- **THEN** a new LessonRecord is created with the given content, `tags=["pitfall"]`,
  and `tier="working"`

### Requirement: Five-pattern output trigger

The system SHALL surface stored memories to the agent through five output trigger patterns.
Each pattern is independently activatable; they are not mutually exclusive.

**Output pattern definitions:**

1. **Pull** (agent queries on demand): `mycelium recall` CLI returns lessons matching a query.
2. **Push by hook** (SessionStart inject): At session start, the system SHALL inject the top 3
   hot-tier lessons into the session context automatically.
3. **Push by event** (PreToolUse intercept): When a PreToolUse hook detects a high-risk operation
   (e.g., `git push`), the system SHALL surface relevant pitfall-type lessons.
4. **Dream surface** (SessionStart digest): After the dream/consolidation skill produces a digest,
   the system SHALL display it at session start. (Requires dream skill; Phase 5 activation.)
5. **Cross-bot broadcast** (MCP subscribe): Agents subscribed via `mycelium_subscribe` SHALL
   receive new relevant lessons as they are written by any bot. (Phase 4 activation.)

#### Scenario: SessionStart injects hot lessons

- **WHEN** a new Claude Code session starts and there are hot-tier lessons in the DB
- **THEN** the top 3 lessons by `effective_weight` are prepended to the session context as
  a `★ Recalled lessons:` block before the first user turn is processed

#### Scenario: PreToolUse intercepts git push

- **WHEN** an agent is about to execute a `git push` command and there are lessons with
  `lesson_type="pitfall"` and tags matching `["git", "push"]`
- **THEN** the system surfaces those pitfall lessons as a warning before the tool call proceeds

#### Scenario: Pull recall returns ranked results

- **WHEN** an agent calls `mycelium recall --query "squash merge" --token-budget 1000`
- **THEN** the system returns lessons sorted by `effective_weight` descending,
  stopping when the cumulative token estimate would exceed 1000 tokens

### Requirement: Input/output trigger symmetry

Every input trigger layer SHALL have at least one corresponding output trigger pattern.
The system MUST NOT have an input path without a read path, or a read path that can only
return empty results because the write path does not exist.

The following symmetry table SHALL hold:

| Input trigger | Corresponding output pattern |
|---|---|
| Stop hook (session summary) | Pull / Push by hook (SessionStart) |
| PreCompact hook (context pressure) | Pull / Dream surface (after consolidation) |
| Agent manual (mycelium memory save) | Pull (on demand) |

#### Scenario: Memory written via Stop hook is retrievable via recall

- **WHEN** a lesson is written by the Stop hook with content "avoid git push --force on shared branches"
- **THEN** calling `mycelium recall --query "git push force"` returns that lesson in the result set

#### Scenario: PreCompact hook content surfaces in next session

- **WHEN** the PreCompact hook saves a summary during session N
- **THEN** at the start of session N+1, `mycelium recall` returns that summary as a hot candidate

## Boundary Value Scenarios (Layer 2 QA)

### EP: SessionStart inject with zero hot lessons (edge case)

- **GIVEN** DB has lessons but all are tier="working", tier="cold", or tier="archival"
- **WHEN** SessionStart hook triggers
- **THEN** no output is produced (MUST NOT output empty block or error message)

### EP: SessionStart inject with exactly 3 hot lessons

- **GIVEN** DB has exactly 3 hot lessons
- **WHEN** SessionStart hook triggers
- **THEN** all 3 lessons are included in the output block

### EP: SessionStart inject with more than 3 hot lessons

- **GIVEN** DB has 7 hot lessons
- **WHEN** SessionStart hook triggers
- **THEN** only the top 3 by effective_weight are included; the other 4 are not shown

### BVA: PreToolUse — safe command does NOT trigger pitfall warning

- **GIVEN** a PreToolUse event with `tool_name="Bash"` and `command="git status"`
- **WHEN** the retrieval hook processes the event
- **THEN** no pitfall warning is output (git status is not a high-risk operation)

### BVA: PreToolUse — dangerous command triggers warning

- **GIVEN** a PreToolUse event with `tool_name="Bash"` and `command="git push origin main"`
  AND DB has at least one lesson with `lesson_type="pitfall"` and `tags` containing "git"
- **WHEN** the retrieval hook processes the event
- **THEN** output contains "★ Pitfall warning:" followed by the relevant lesson content

### EP: PreToolUse — no matching pitfall lessons available

- **GIVEN** a PreToolUse event with `command="git push origin main"`
  AND DB has no lessons with `lesson_type="pitfall"` matching git tags
- **WHEN** the retrieval hook processes the event
- **THEN** no output is produced (MUST NOT produce empty warning block)

### State Transition: memory save to recall lifecycle

| Phase | Action | State after |
|-------|--------|-------------|
| Write | `mycelium memory save "content"` | LessonRecord created, tier="working", access_count=0 |
| Read (first) | `mycelium recall --query "content"` | Lesson returned, access_count incremented to 1 |
| Promote | `run_promotion_check()` after 3 accesses | tier promoted to "hot" |
| Inject | SessionStart hook | Lesson appears in ★ Recalled lessons block |
| Demote | access_count=0, age>90 days | tier demoted to "cold" |

# mycelium-semantic-recall Specification

## Purpose

TBD - created by archiving change 'mycelium-layered-memory'. Update Purpose after archive.

## Requirements

### Requirement: MemoryIndex interface

The system SHALL define a `MemoryIndex` abstract interface in `tasks/mycelium/semantic_index.py`
with the following methods:

- `embed(text: str) -> list[float]` -- Converts text to a dense embedding vector.
- `upsert(lesson_id: str, text: str, metadata: dict) -> None` -- Indexes a lesson by ID.
- `search(query: str, limit: int = 10) -> list[tuple[str, float]]` -- Returns (lesson_id, score) pairs.
- `delete(lesson_id: str) -> None` -- Removes a lesson from the index.

The interface SHALL allow future adapters (e.g., pgvector, gbrain) to be registered without
modifying call sites.
The default backend SHALL be `SqliteVecIndex`, implementing the interface using SQLite FTS5
for keyword search and sqlite-vec for vector search.
If sqlite-vec is not installed, the system SHALL gracefully fall back to FTS5-only mode
without raising an exception.

#### Scenario: Index and retrieve a lesson via keyword

- **WHEN** a lesson with content "avoid git push force on shared branches" is upserted into the index
- **THEN** `search("git push force", limit=5)` returns that lesson_id in the result list

#### Scenario: FTS5 fallback when sqlite-vec unavailable

- **WHEN** sqlite-vec extension is not loadable in the current SQLite build
- **THEN** the system initializes `SqliteVecIndex` in FTS5-only mode, logs a warning,
  and `search()` operates using FTS5 keyword ranking without vector similarity

#### Scenario: MemoryIndex delete removes lesson from search

- **WHEN** `delete(lesson_id)` is called for a lesson
- **THEN** subsequent `search()` calls do not return that lesson_id

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

---
### Requirement: SQLite FTS5 and sqlite-vec backend

The default `SqliteVecIndex` implementation SHALL use SQLite's built-in FTS5 extension for
keyword search and the sqlite-vec extension for vector similarity search.
In hybrid mode, results from FTS5 and vector search SHALL be merged using reciprocal rank fusion (RRF)
with equal weight.
The embedding model SHALL be configurable; the default SHALL be a local embedding via
`sqlite-vec`'s built-in float32 vector storage (embedding generation is caller-provided).
Embeddings SHALL be stored in a `lesson_embeddings` table with schema
`(lesson_id TEXT PRIMARY KEY, embedding BLOB)`.

#### Scenario: Hybrid search merges keyword and vector results

- **WHEN** `search("squash merge", limit=10, mode="hybrid")` is called
  and both FTS5 and vector indices contain relevant lessons
- **THEN** the returned list is sorted by RRF-merged score, with lessons appearing in
  both indices ranked higher than those in only one index

#### Scenario: Keyword-only mode skips vector lookup

- **WHEN** `search("squash merge", limit=10, mode="keyword")` is called
- **THEN** only FTS5 results are returned, with no vector similarity computation

#### Scenario: Vector-only mode skips FTS5 lookup

- **WHEN** `search("squash merge", limit=10, mode="vector")` is called
- **THEN** only vector similarity results are returned, with no FTS5 computation

##### Example: RRF score computation

| lesson_id | FTS5 rank | vector rank | RRF score (k=60) |
|-----------|-----------|-------------|-----------------|
| L1 | 1 | 2 | 1/(61) + 1/(62) = 0.0164 + 0.0161 = 0.0325 |
| L2 | 3 | 1 | 1/(63) + 1/(61) = 0.0159 + 0.0164 = 0.0323 |
| L3 | 2 | not found | 1/(62) + 0 = 0.0161 |

Final order: L1 > L2 > L3

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

---
### Requirement: Context window token budget recall

The `mycelium recall` command and `lessons_service.get_lessons()` SHALL support a
`--token-budget N` parameter that limits the total estimated token count of returned lessons.
Token estimation SHALL use tiktoken with the `cl100k_base` encoding as the default.
The system SHALL stop appending lessons to the result when the next lesson would cause the
cumulative token estimate to exceed the budget, even if fewer than `limit` lessons have been returned.
A `--mode {episodic|semantic|procedural}` flag SHALL filter lessons by type before applying
the budget: `episodic` -> handover summaries, `semantic` -> patterns and architectures,
`procedural` -> tools and operational lessons.

#### Scenario: Token budget stops recall before limit

- **WHEN** `get_lessons(token_budget=500, limit=20)` is called
  and the first 3 lessons total 480 tokens, while the 4th lesson is 100 tokens
- **THEN** only the first 3 lessons are returned (adding the 4th would exceed 500)

#### Scenario: Mode filter narrows the candidate set

- **WHEN** `get_lessons(mode="procedural", token_budget=1000)` is called
- **THEN** only lessons with `lesson_type in ["tool", "operational"]` are candidates for return

#### Scenario: Budget larger than all lessons returns all lessons

- **WHEN** `get_lessons(token_budget=100000)` is called and total lesson tokens are under 100000
- **THEN** all non-archived lessons are returned (subject to tier filter)

##### Example: mode to lesson_type mapping

| mode flag | lesson_type values included |
|-----------|----------------------------|
| episodic | handover summary (from HandoverRecord summary field) |
| semantic | pattern, architecture, investigation |
| procedural | tool, operational |
| (none) | all lesson_type values |

<!-- @trace
source: mycelium-layered-memory
updated: 2026-07-18
code: []
-->

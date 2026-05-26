---
name: spectra-amplifier
type: know
scope: global
description: >
  Methodology for merging Spec Kit's five-layer deep spec expansion with the OpenSpec/Spectra
  change management framework. Trigger contexts: user mentions "write spec", "expand requirements",
  "requirements specification", "proposal", "openspec", "spectra", "spec kit", "speckit",
  "five-layer expansion", "deep spec", "change management", "delta spec", "changes folder",
  "requirements document structure". Also applies when: user says "expand this user story into
  a complete spec", "write requirements to a developable level", "design API spec",
  "create a proposal", "requirements change tracking", "write AC", "write acceptance criteria".
  Must trigger when user pastes a feature description or User Story and requests a complete
  development specification. Even if the user only says "describe this feature more clearly",
  "how do I define done criteria", "break down tasks", "how to write a spec", or
  "this requirement is too vague", this skill should trigger.
---

# Spectra Amplifier — Five-Layer Deep Spec Expansion + Change Management Framework

You are a senior systems analyst specializing in expanding vague requirements into complete
specification documents that are implementable, testable, and traceable.
You combine Spec Kit's five-layer deep expansion methodology with OpenSpec/Spectra's change
management framework, ensuring each spec has both sufficient technical depth and full change
history traceability.

## Core Philosophy

> **Spec Kit produces the most detailed specs, but they are disposable once complete;
> Spectra has the best change management, but specs are thin on content.**
> The optimal strategy is not switching tools, but porting Spec Kit's "five-layer depth"
> into Spectra's framework.
> Depth × Traceability = Truly reliable specifications.

## Output Structure

Each feature's complete specification lives at:

```text
docs/openspec/changes/[feature-name]/
├── proposal.md   # Full five-layer expansion proposal (Layers 1, 2, 4, 5)
├── design.md     # Layer 3: data model and API design
├── tasks.md      # File-level development task breakdown (Spec Kit Phase structure)
└── specs/        # Delta specs (GIVEN/WHEN/THEN + QA boundary values)
    ├── [feature-name]-core.md
    └── [feature-name]-edge.md
```

> If the `docs/openspec/` directory does not exist, create it first.
> This path is a convention and can be adjusted per project.

---

## Effort Level Strategy

Current effort: ${CLAUDE_EFFORT}

| Effort | Execution Strategy |
|--------|--------------------|
| high | Full five-layer expansion; Layer 2 runs all three QA quick-checks (Equivalence Partitioning + Boundary Value + State Transition); Layer 3 conflict detection required; tasks.md includes automatic priority derivation and `[PRIORITY-REVIEW]` prompts; specs/ produces complete boundary value scenarios |
| medium | Full five-layer expansion; Layer 2 applies 1-2 QA techniques as needed; conflict detection runs; tasks.md uses basic Phase structure |
| low | Layers 1-2 only, producing User Stories and basic FS; skip Layer 3 API/data model and Layers 4-5 detailed content |

> If `${CLAUDE_EFFORT}` is not set or is `normal`, treat it as high.

---

## Five-Layer Expansion Process

### Layer 1 — User Stories

**Goal**: Extract actionable user stories from vague descriptions; force clarification of
requirement boundaries.

#### Step 1: Four-Element Extraction (Spec Kit Method)

From the requirement description, identify:

| Element | Description | Example |
|---------|-------------|---------|
| **Actors** | Who uses this feature | General user, admin, scheduler |
| **Actions** | What operations they can perform | Create, query, delete, export |
| **Data** | What data entities are involved | Billing records, user profile, invoice |
| **Constraints** | What constraints and boundary conditions exist | Can only view own data, amount must be positive |

After extraction, check for ambiguities and mark with `[NEEDS CLARIFICATION: description]`.
**Limit: 3.** If more than 3, the requirement is not mature enough — return it for further
elaboration before expanding.

#### Step 2: Write User Stories

**Format**:

```markdown
### US-NNN: [Story Title]

**Persona**: [Role description, including background and motivation]
**Action**: [Desired operation to complete]
**Outcome**: [Expected result and value]

**Acceptance Criteria**:
- AC-NNN-1: [Verifiable condition, using Given/When/Then format]
- AC-NNN-2: [...]
- AC-NNN-3: [...]
(at least 3; each must be independently testable)
```

**Anti-Speculation Rule**: Writing any "might need" features is prohibited.
Every AC must be traceable to a clear business requirement.
Features no Actor will use are not written into the spec.

---

### Layer 2 — Functional Spec + Instant QA Check

**Goal**: Expand each AC into a complete functional spec; immediately identify test boundaries.

#### Step 1: AC → Functional Spec Expansion

Each AC expands into one FS, using the format below:

```markdown
#### FS-NNN: [Functional Spec Title]

**Traceability**: AC-MMM-X (US-MMM)

1. **Input Constraints**: MUST accept ___; value range is ___; format constraint is ___
2. **Processing Logic**: system SHALL ___; if ___ then SHALL ___
3. **Output / Side Effects**: MUST return ___; SHALL trigger ___; database SHALL ___
4. **What It Does Not Do**: MUST NOT ___; this spec does not handle ___ (reason: ___)
5. **Error Handling**: if ___ then SHALL return ___ (HTTP NNN) and SHALL log ___
```

Use RFC 2119 keywords to precisely describe obligation levels:

- `MUST` / `SHALL`: absolute requirement
- `SHOULD`: recommended but not mandatory
- `MAY`: optional
- `MUST NOT`: absolutely prohibited

#### Step 2: Instant QA Quick-Check (Three Techniques)

After completing a batch of FSs, immediately use the following three techniques from the
**`qa-test-design` Skill**:

1. **Equivalence Partitioning**: What valid and invalid partitions exist for each input field?
   Select one representative value from each partition.
2. **Boundary Value Analysis**: What are the boundaries for numbers, dates, and string lengths?
   Test `min-1, min, max, max+1`.
3. **State Transition**: Does the feature have a lifecycle state (e.g., Draft → Review → Published)?
   List all valid and invalid transitions.

> If there is no state transition, use a **Decision Table Testing** technique (multi-condition combinations)
> instead, or note "no state, N/A".

Quick-check results go into the `specs/` folder, written as GIVEN/WHEN/THEN boundary value
scenarios.

---

### Layer 3 — Data Model + API

**Goal**: Define data structures and service interfaces; confirm no conflicts with existing specs.

#### Data Model (write to `design.md`)

```markdown
## Entity: [EntityName]

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK, NOT NULL | Primary key |
| ... | ... | ... | ... |

**Indexes**:
- UNIQUE INDEX ON (...)
- INDEX ON (...) — query performance

**Relations**:
- `EntityA` 1:N `EntityB` (FK: entity_b.entity_a_id → entity_a.id)
```

#### API Schema (write to `design.md`)

````markdown
## API: [METHOD] /[path]

**Request**:

```json
{
  "field": "type and description"
}
```

**Response 200**:

```json
{
  "field": "type and description"
}
```

**Error Cases**:

| Code | Reason | Response Body |
|------|--------|---------------|
| 400  | Invalid input format | `{ "error": "..." }` |
| 404  | Resource not found | `{ "error": "..." }` |

````

#### Conflict Detection

After completing Layer 3, use the **Conflict Detection Checklist** (see below) to compare
against existing specs in `docs/openspec/specs/`, identifying naming conflicts and
dependencies. If this is the first spec (no existing specs), note "baseline, no conflict
check needed" and continue.

---

### Layer 4 — Assumptions and Constraints

**Goal**: Explicitly mark all assumptions and boundaries to prevent scope creep.

```markdown
## Assumptions

| # | Assumption | Impact if False |
|---|------------|-----------------|
| A1 | User has completed authentication | Authentication prerequisite needed; affects API design |
| A2 | ... | ... |

## Hard Constraints

| # | Constraint | Source |
|---|-----------|--------|
| C1 | Response time < 500ms | Performance SLA |
| C2 | Data retention 7 years | Regulatory requirement |

## Out of Scope

| Feature | Exclusion Reason | Future Consideration |
|---------|-----------------|----------------------|
| Batch import | Phase 1 supports single-entry only | Evaluate in Phase 2 |
| Multi-language | Chinese only in current scope | Address during internationalization |
```

Every Out of Scope item must include a reason and future consideration to prevent scope
disputes later.

---

### Layer 5 — Testability

**Goal**: Define the boundary of "done" and ensure the spec is verifiable.

```markdown
## Definition of Done

This feature is considered "done" when:
- [ ] All FS-NNN items are implemented
- [ ] All smoke tests pass
- [ ] No anomaly alerts on the monitoring dashboard
- [ ] Code has been reviewed and merged

## Smoke Test Scenarios (3–5)

**ST-001: [Happy Path]**
- GIVEN system is in normal state, and [preconditions]
- WHEN user performs [action]
- THEN system returns [expected result]

**ST-002: [Error Path]**
- GIVEN [abnormal precondition]
- WHEN user performs [action]
- THEN system returns [error message] without affecting [existing state]

## Full QA Testing Recommendations

Use the **`qa-test-design` Skill** for complete test design; recommended techniques:
- High-risk paths → **Risk-Based Testing**
- Multi-condition logic → **Decision Table Testing**
- State machines → **State Transition Testing**
```

---

## tasks.md Task Breakdown Format

**Goal**: Break down Layers 1–5 output into file-level executable development tasks.

Uses **Spec Kit's Phase structure**; priority is automatically derived from Layer 1's four
elements (adjustable afterwards).

### Automatic Priority Derivation Rules

Use the following signals to rank User Stories — no need to ask the user:

| Signal | Priority | Example |
|--------|----------|---------|
| Actor involves payments, authentication, or regulatory compliance | P1 | Payment, login, data retention |
| Constraint has SLA or deadline | P1 | Response < 500ms, regulatory requirement |
| Core path (other stories depend on it) | P1 | Create account (other features depend on this) |
| Moderate complexity, no blocking dependencies | P2 | Query reports, modify settings |
| Experience optimization, non-core features | P3 | UI details, CSV export |

After derivation, add `> [PRIORITY-REVIEW]` at the top of `tasks.md` to prompt the user
to confirm or adjust.

#### tasks.md Format

```markdown
# tasks.md — [feature-name]

> [PRIORITY-REVIEW] Priority was auto-derived; confirm and remove this line when done.
> To adjust: edit each US's (P1/P2/P3) within its Phase and re-sort.

## Phase 1: Setup
- [ ] T001 Set up directory structure and base configuration

## Phase 2: Foundational (Blocking Prerequisites)
- [ ] T002 [P] Create Entity model — target: src/models/[name].py
- [ ] T003 [P] Create DB migration — target: migrations/[timestamp]_[name].sql

## Phase 3: User Stories (P1 → P2 → P3)

### US-001: [Title] (P1 — Actor involves payments)
**Story Goal**: [one-sentence description]
**Test Criteria**: FS-001 ~ FS-003 all pass

- [ ] T010 [P] [US1] Implement Service layer — target: src/services/[name]_service.py
- [ ] T011 [US1] Implement API endpoint (depends on T010) — target: src/routes/[name].py
- [ ] T012 [P] [US1] Write unit tests — target: tests/test_[name]_service.py

## Phase 4: Polish & Cross-Cutting Concerns
- [ ] T020 [P] Add logging and monitoring instrumentation
- [ ] T021 [P] Update API documentation
```

**Marker Legend**:

- `[P]` = can run in parallel with other `[P]` tasks
- `[USn]` = corresponds to User Story n
- No marker = has sequential dependencies; must wait
- `(P1 — reason)` = derivation rationale after Story title for easy review

---

## Change Management Markers (Delta Markers)

When modifying **existing** spec documents (not initial creation), all changes must use
delta markers:

| Marker | Purpose | When to Use |
|--------|---------|-------------|
| `[ADDED]` | Newly added content | New FS, new Entity field, new API |
| `[MODIFIED]` | Modified existing content | Changed value range, updated processing logic, adjusted AC |
| `[REMOVED]` | Deleted existing content | Keep a tombstone with the reason |

**Initial creation requires no markers.** From the second revision onwards, every change
gets a corresponding marker.

```markdown
<!-- Example: revising FS-003 -->

#### FS-003: Amount Validation [MODIFIED]
<!-- Original: amount > 0 -->
<!-- Changed to: amount > 0 and <= 1,000,000 (reason: comply with regulatory limit) -->

1. **Input Constraints**: MUST accept positive integers; value range is 1 ~ 1,000,000 [MODIFIED]
```

---

## Conflict Detection Checklist

After completing Layer 3, verify each item:

- [ ] **Pre-check**: Does `docs/openspec/specs/` contain existing specs?
  If not, note "baseline, no conflict check needed" and skip the items below.
- [ ] **Entity naming**: New entity names do not duplicate or semantically overlap existing entities
- [ ] **API endpoint**: New paths do not conflict with existing routes (METHOD + path combination is unique)
- [ ] **Shared tables**: If modifying an existing table, all users of that table have been considered
- [ ] **Event / Message schema**: Event format is backward-compatible
- [ ] **Permission model**: Access control for new features is consistent with existing role definitions

If conflicts exist, document the resolution in the "Assumptions and Constraints" section of
`proposal.md` under Layer 4.

---

## Output File Templates

### `proposal.md` Skeleton

```markdown
# Proposal: [feature-name]

> Version: v1.0 | Date: [YYYY-MM-DD] | Status: Draft / Review / Approved

## Layer 1 — User Stories

[US-001 ~ US-NNN]

## Layer 2 — Functional Spec

[FS-001 ~ FS-NNN]

<!-- FS-NNN: functional spec definitions (five-dimension expansion);
     Layer 2 QA quick-check boundary scenarios saved separately in specs/. -->

## Layer 4 — Assumptions and Constraints

[Assumptions table, Hard Constraints table, Out of Scope table]

## Layer 5 — Testability

[Definition of Done, Smoke Tests, QA Recommendations]
```

### `design.md` Skeleton

```markdown
# Design: [feature-name]

> Version: v1.0 | Date: [YYYY-MM-DD]

## Layer 3 — Data Model

[Entity definitions]

## Layer 3 — API Schema

[API definitions]

## Conflict Detection Result

[Pass / Conflict items and resolutions]
```

### `specs/[feature]-core.md` Skeleton

```markdown
# Delta Specs: [feature-name]

> Corresponding spec: `docs/openspec/specs/[feature].md`
> Change type: ADDED / MODIFIED

## FS-001: [Title]

**GIVEN** [precondition]
**WHEN** [triggering action]
**THEN** [expected result]

**Boundary Value Test Scenarios** (from Layer 2 QA quick-check):
- Input = min-1 → should reject (return 400)
- Input = min → should accept
- Input = max → should accept
- Input = max+1 → should reject (return 400)
```

---

## Anti-Patterns

| Anti-Pattern | Problem | Correct Approach |
|--------------|---------|-----------------|
| **Skip-layer expansion** (jump from description directly to Layer 3) | Missing functional logic; data model is designed incorrectly | Must complete Layers 1 and 2 before entering Layer 3 |
| **Monolithic User Story** (one story covers 5+ features) | ACs cannot be independently tested; task breakdown is inaccurate | Split until each story has only 3–5 ACs |
| **Copy-paste AC as FS** (without true expansion) | No input constraints, boundaries, or error handling | Each AC must expand into five dimensions |
| **Skip QA quick-check** | Boundary bugs are not found until the development phase | Run the three quick-checks immediately after Layer 2 |
| **Skip conflict detection** | New API breaks existing features | Layer 3 must compare against existing specs |
| **Out of Scope without reason** | Future scope disputes cannot be resolved | Every Out of Scope item must include a reason + future consideration |
| **Unmarked revisions** | Change history is lost; changes cannot be tracked | From the second revision, every change gets a delta marker |
| **More than 3 NEEDS CLARIFICATION** | Forcing expansion before the requirement is mature | Return for requirement elaboration; do not continue with ambiguities |
| **Spec written after code** (write code first, then document) | Spec inherits all implementation assumptions; loses independent requirement baseline | Spec must be completed before implementation; if code already exists, use the Brownfield reverse-engineering mode in the Spectra CLI Integration section |

---

## Workflow Summary (Quick Reference)

```text
Requirement description (any format)
  │
  ▼ Layer 1
Four-element extraction (Actors / Actions / Data / Constraints)
  + User Stories (US-NNN) + AC (≥3)
  + [NEEDS CLARIFICATION] (≤3)
  │
  ▼ Layer 2
AC → Functional Spec (FS-NNN) × five dimensions (RFC 2119)
  + QA quick-check (Equivalence Partitioning / Boundary Value / State Transition)
  → write to specs/*.md
  │
  ▼ Layer 3
Data Model (Entity + Relations) + API Schema
  + Conflict Detection (compare against existing openspec)
  → write to design.md
  │
  ▼ Layer 4
Assumptions + Hard Constraints + Out of Scope (with reason and future consideration)
  → write to proposal.md
  │
  ▼ Layer 5
Definition of Done + Smoke Tests + QA technique recommendations
  → write to proposal.md
  │
  ▼ Output
docs/openspec/changes/[feature-name]/
├── proposal.md  (Layers 1, 2, 4, 5)
├── design.md    (Layer 3)
├── tasks.md     (Phase structure task breakdown)
└── specs/       (GIVEN/WHEN/THEN + QA boundary values)
```

On revision: add `[ADDED]` / `[MODIFIED]` / `[REMOVED]` markers to all changed locations.

---

## Spectra CLI Integration (Optional)

If the project has the `spectra` CLI installed and uses the `spectra-propose` workflow,
this skill acts as a post-processing amplifier for spectra-propose, filling in the spec
depth of artifacts.

### Prerequisites

- `spectra` CLI is installed (`spectra --version` works)
- A change has been created via `/spectra-propose <feature>` and its artifacts exist

### Five-Layer Expansion ↔ Spectra Artifacts Mapping

| Five-Layer | Corresponding Spectra Artifact | Action |
|------------|-------------------------------|--------|
| Layer 1: User Stories | `proposal.md` Capabilities section | For each Capability, backfill Persona, complete ACs (≥3), add `[NEEDS CLARIFICATION]` ambiguity markers |
| Layer 2: Functional Spec | `specs/*/spec.md` Requirements | Expand RFC 2119 five dimensions + `FS-NNN` traceability ID; run QA quick-checks; add boundary values to Scenarios |
| Layer 3: Data Model | `design.md` or spec's `## Data Model` | Brownfield: reverse-engineer from ORM; Greenfield: define + `[TBD]` markers |
| Layer 4: Assumptions and Constraints | `proposal.md` Non-Goals + spec's NFR | Add Assumptions table (with "impact if false") and Constraints table |
| Layer 5: Testability | spec Scenarios + `tasks.md` | Strengthen boundary values; add smoke test GIVEN/WHEN/THEN; fill QA technique recommendations |

### Brownfield vs. Greenfield Determination

Before Layer 3 and Layer 5, determine the mode:

**Brownfield** (any of the following applies):

- spec has `<!-- @trace` block containing code paths, or
- grepping the codebase for the spec's domain keywords (table names, service names) yields hits

**Greenfield** (none of the above):

- No existing code; spec is defined from scratch

| Layer | Brownfield | Greenfield |
|-------|-----------|------------|
| Layer 3 Data Model | Reverse-engineer from ORM models; mark "verify intent" | Define schema; mark unknown fields `[TBD]`; batch AskUserQuestion |
| Layer 5 Boundary Values | grep validators to confirm exact values | Mark `[boundary = TBD]`; ask in batch |

### Execution Flow

```text
/spectra-propose <feature>
  ↓ creates proposal.md, specs, design.md, tasks.md
  ↓ (Claude version: Step 11 triggers automatically; Gemini version: trigger manually)
(trigger this skill: tell Claude "use spectra-amplifier skill to expand <change-name>")
  ↓ five-layer diagnosis → mapping and filling
  ↓ spectra analyze <name> --json  (fix Critical + Warning only)
  ↓ spectra validate "<name>"
/spectra-apply <change-name>
```

### Acceptance

```bash
# after filling in
spectra analyze <change-name> --json   # fix Critical + Warning only; max 2 iterations
spectra validate <change-name>         # must pass before considered complete
```

### Coexistence with Project-Level Skill

This skill is installed at user-level (`~/.agents/skills/spectra-amplifier`) as a universal
fallback:

- **Projects with a project-level spectra-amplifier** (e.g., yibi-mvp): project-level takes
  priority; this skill is inactive
- **Projects without a project-level version**: this skill is used automatically

> To activate this skill in a specific project, confirm there is no same-named skill under
> that project's `.claude/skills/`.

## ADDED Requirements

### Requirement: LessonType classification

Each lesson record SHALL be classified with exactly one of the following types:
`pattern`, `pitfall`, `preference`, `architecture`, `tool`, `operational`, `investigation`.

#### Scenario: Valid type accepted

- **WHEN** a lesson is created with type set to one of the 7 valid values
- **THEN** the lesson is stored with that type value

#### Scenario: Invalid type rejected

- **WHEN** a lesson is created with a type not in the 7-value enum
- **THEN** the system raises a ValidationError and the lesson is not stored

##### Example: boundary cases

| Input type | Expected |
|------------|----------|
| `pitfall` | accepted |
| `pattern` | accepted |
| `bug` | ValidationError |
| `` (empty) | ValidationError |

---

### Requirement: LessonSource and trusted bit

Each lesson record SHALL carry a `source` field from:
`observed`, `user-stated`, `inferred`, `cross-model`.
When `source == "user-stated"` the `trusted` field SHALL be automatically set to `True`;
for all other sources `trusted` SHALL be `False`.
The `trusted` field MUST NOT be set independently of `source`.

#### Scenario: user-stated sets trusted automatically

- **WHEN** a lesson is created with `source="user-stated"`
- **THEN** `trusted` is `True` without any explicit flag

#### Scenario: observed source is not trusted

- **WHEN** a lesson is created with `source="observed"`
- **THEN** `trusted` is `False`

---

### Requirement: Confidence score 1-10

Each lesson SHALL carry an integer `confidence` in the range [1, 10] inclusive.
Values outside this range MUST be rejected with a ValidationError.

#### Scenario: Out-of-range confidence rejected

- **WHEN** a lesson is created with confidence 0 or 11
- **THEN** the system raises a ValidationError

##### Example: boundary values

| confidence | Expected |
|------------|----------|
| 0 | ValidationError |
| 1 | accepted |
| 10 | accepted |
| 11 | ValidationError |

---

### Requirement: Key format constraint

The `key` field SHALL match the pattern `[a-zA-Z0-9_-]+` (alphanumeric, underscore, hyphen only).
Any other character SHALL cause a ValidationError.

#### Scenario: Invalid key rejected

- **WHEN** a lesson is created with a key containing spaces or special characters
- **THEN** the system raises a ValidationError

##### Example: key patterns

| key | Expected |
|-----|----------|
| `dedup-grain` | accepted |
| `my_key_123` | accepted |
| `bad key` | ValidationError (space) |
| `bad.key` | ValidationError (dot) |

---

### Requirement: Insight injection protection

The `insight` field SHALL be validated against 10 injection-detection regexes.
If any regex matches, the record MUST be rejected with a ValidationError before storage.
The protected patterns SHALL include (case-insensitive):
`ignore.*previous.*(instructions|context|rules)`,
`you are now`,
`always output no findings`,
`skip.*(security|review|checks)`,
`override:`,
`\bsystem\s*:`,
`\bassistant\s*:`,
`\buser\s*:`,
`do not (report|flag|mention)`,
`approve (all|every|this)`.

#### Scenario: Injection attempt rejected

- **WHEN** a lesson insight contains "ignore previous instructions"
- **THEN** a ValidationError is raised and the lesson is not stored

#### Scenario: Legitimate insight accepted

- **WHEN** a lesson insight is a normal technical observation without any injection pattern
- **THEN** the lesson is stored successfully

---

### Requirement: Confidence decay for time-sensitive sources

For lessons with `source` of `observed` or `inferred`, the system SHALL compute
an `effective_confidence` by subtracting 1 for every 30 days elapsed since the lesson's `ts`.
`effective_confidence` SHALL NOT fall below 1.
For lessons with `source` of `user-stated` or `cross-model`, no decay is applied;
`effective_confidence` equals `confidence`.

#### Scenario: Decay applied after 60 days

- **WHEN** an observed lesson with confidence=8 was stored 60 days ago
- **THEN** effective_confidence = 6 (8 - floor(60/30) = 8 - 2)

#### Scenario: user-stated does not decay

- **WHEN** a user-stated lesson with confidence=9 was stored 90 days ago
- **THEN** effective_confidence = 9 (no decay)

#### Scenario: Decay floor is 1

- **WHEN** an observed lesson with confidence=2 was stored 90 days ago
- **THEN** effective_confidence = 1 (max(1, 2 - 3) = max(1, -1) = 1)

##### Example: decay table

| source | confidence | days elapsed | effective_confidence |
|--------|-----------|--------------|---------------------|
| observed | 8 | 60 | 6 |
| inferred | 5 | 30 | 4 |
| user-stated | 9 | 90 | 9 |
| cross-model | 7 | 120 | 7 |
| observed | 2 | 90 | 1 |

---

### Requirement: Key+type deduplication (latest winner)

When multiple lessons share the same `key` and `type`, the system SHALL return only
the lesson with the most recent `ts` (latest winner).
Older duplicate entries SHALL be excluded from query results but remain in the store.

#### Scenario: Latest winner returned

- **WHEN** two lessons share key="dedup-grain" and type="pitfall" with different timestamps
- **THEN** only the lesson with the newer timestamp appears in results

---

### Requirement: Legacy data merged during transition period

When `include_legacy=True` (the default), the system SHALL include lessons from
`handovers.lessons_learned` JSON array and `insights.jsonl` in query results.
Legacy items SHALL be normalized with `source="observed"` and `confidence=5`.
The `lessons` table (typed store) and legacy items SHALL be merged, deduplicated,
and sorted together by effective_confidence descending.

#### Scenario: Empty typed store still shows legacy lessons

- **WHEN** the `lessons` table is empty and `include_legacy=True`
- **THEN** results contain items from `handovers.lessons_learned`

#### Scenario: Legacy items excluded when flag off

- **WHEN** `include_legacy=False`
- **THEN** only lessons from the `lessons` table are returned

---

### Requirement: Cross-project filter returns only trusted lessons

When `cross_project=True`, the system SHALL return lessons from all projects
but restrict results to lessons where `trusted=True` (`source="user-stated"`).
Project-local results (the default) include all trust levels.

#### Scenario: Cross-project filter restricts to trusted

- **WHEN** `cross_project=True`
- **THEN** only lessons with trusted=True appear, regardless of project

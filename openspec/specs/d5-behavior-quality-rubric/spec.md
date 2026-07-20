# d5-behavior-quality-rubric Specification

## Purpose

TBD - created by archiving change 'enhance-d5-behavior-harness'. Update Purpose after archive.

## Requirements

### Requirement: D5 semantic rubric evaluates test effectiveness via three sub-items

The D5 semantic rubric SHALL award up to 5 points across three independently-scored sub-items, replacing the existing binary 5/3/0 scoring. Each sub-item SHALL be assessable independently; partial credit (e.g., 2+0+1) MUST be possible.

Sub-item definitions:
- **Meaningful assertions** (2 pts): Tests SHALL contain assertions that compare values, types, or state — not merely assert that code runs without error. Agent SHALL award 2 pts when at least one test file contains value comparison (`assert x == y`), type comparison, or state comparison assertions. Agent SHALL award 0 pts when assertions only check for absence of exceptions.
- **Factory helper pattern** (2 pts): Test files SHALL use controlled, reusable test data construction rather than hardcoded inline values. The specific pattern is language-dependent:
  - **Python**: module-level `def make_*()` functions. Agent SHALL award 2 pts when `extra["factory_helper_files"]` from the mechanical scan is non-empty OR when the agent directly observes `def make_` functions at column 0.
  - **TypeScript/JavaScript**: module-level `create*()`, `build*()`, or `make*()` helper functions that return test objects.
  - **Dart/Flutter**: `setUp()` callbacks initialising shared fixture variables, or named factory constructors used across tests.
  - **Go**: package-level test data structs or table-driven `cases` / `tests` variables that centralise test inputs.
  Agent SHALL award 2 pts when the language-appropriate pattern is present. Agent SHALL award 0 pts when test data is hardcoded inline in every test method regardless of language.
  Note: `extra["factory_helper_files"]` from the mechanical scan covers Python only; for other languages the agent SHALL judge directly from test file content.
- **Edge case coverage** (1 pt): Test suite SHALL include at least 3 distinct scenarios (success path, missing/invalid input, boundary condition) OR contain test IDs with `EG-` classification across at least 2 distinct EG categories (single happy-path `EG-` test does not qualify). Agent SHALL award 1 pt when this condition is met; 0 pts for happy-path-only suites.

#### Scenario: full score with all sub-items present

- **WHEN** test files contain value-comparison assertions, language-appropriate factory helpers (e.g. `def make_*` in Python, `create*()` in TypeScript, `setUp()` fixtures in Dart, table-driven `cases` in Go), and at least 3 scenario types
- **THEN** D5 semantic score is 5 (2+2+1)

#### Scenario: partial score with assertions and factory helpers but no edge cases

- **WHEN** tests have meaningful assertions and factory helpers but only test the happy path
- **THEN** D5 semantic score is 4 (2+2+0)

#### Scenario: zero score for assertion-only existence checks

- **WHEN** test files only assert no exception is raised (e.g., `result is not None` without value comparison)
- **THEN** D5 semantic score is 0 regardless of other sub-items

##### Example: scoring combinations (decision table)

| Assertions | Factory helpers | Edge cases | Score |
|------------|----------------|------------|-------|
| meaningful | present | >= 3 scenarios | 5 |
| meaningful | present | happy path only | 4 |
| meaningful | absent | >= 3 scenarios | 3 |
| meaningful | absent | happy path only | 2 |
| existence-only | any | any | 0 |

#### Scenario: equivalence class — assertion type boundary

- **WHEN** test contains `assert result.score == 7` (value comparison)
- **THEN** "meaningful assertions" sub-item scores 2 pts

- **WHEN** test contains `assert result is not None` (existence only, no comparison)
- **THEN** "meaningful assertions" sub-item scores 0 pts

- **WHEN** test contains `assert isinstance(result, MechanicalFinding)` (type comparison)
- **THEN** "meaningful assertions" sub-item scores 2 pts

#### Scenario: equivalence class — factory helper module-level only

- **WHEN** test file has `def make_scan_result():` at column 0 (module-level function)
- **THEN** factory helper sub-item is eligible for 2 pts

- **WHEN** test file has `    def make_scan_result(self):` (indented, inside a class — it is a method, not a factory)
- **THEN** factory helper sub-item SHALL score 0 pts; the `def make_` detector SHALL NOT match indented definitions

<!-- @trace
source: enhance-d5-behavior-harness
updated: 2026-07-18
code: []
-->

---
### Requirement: scan_testing detects factory helper functions

The `scan_testing()` function SHALL scan each discovered test file for the pattern `def make_` and return matching file paths in `MechanicalFinding.extra["factory_helper_files"]`.

The factory helper detection SHALL NOT affect the mechanical score (max 7 pts unchanged). The `factory_helper_files` list SHALL be used as a `semantic_targets` signal for the D5 semantic scoring agent.

#### Scenario: test directory contains factory helpers

- **WHEN** one or more test files contain `def make_` at the start of a line (column 0)
- **THEN** `extra["factory_helper_files"]` is a non-empty list of those file paths (relative to target_dir)
- **AND** mechanical score is unchanged

#### Scenario: test directory has no factory helpers

- **WHEN** no test files contain `def make_` at column 0
- **THEN** `extra["factory_helper_files"]` is an empty list

#### Scenario: equivalence class — valid vs invalid def make_ patterns

- **WHEN** line is `def make_scan_profile(**kwargs):` (column 0, module-level)
- **THEN** file path SHALL appear in `factory_helper_files`

- **WHEN** line is `# def make_foo()` (commented out)
- **THEN** file path SHALL NOT appear in `factory_helper_files`

- **WHEN** line is `result = make_foo()` (call expression, not definition)
- **THEN** file path SHALL NOT appear in `factory_helper_files`

##### Example: boundary — indentation

| Line content | Column 0? | In factory_helper_files? |
|--------------|-----------|--------------------------|
| `def make_profile():` | yes | yes |
| `    def make_profile(self):` | no (indented) | no |
| `# def make_profile():` | yes (but commented) | no |
| `make_profile()` | yes (but call not def) | no |

<!-- @trace
source: enhance-d5-behavior-harness
updated: 2026-07-18
code: []
-->

---
### Requirement: D5 TODO includes mutmut recommendation when score is below threshold

When the combined D5 score (mechanical + semantic) is less than 4, the Step 4 TODO output SHALL include a mutation testing recommendation entry using the following format:

```
[D5, medium-effort, high-impact] 測試套件有效性不足：考慮執行 mutation testing
  uv add --dev mutmut
  uv run mutmut run --paths-to-mutate tasks/<module>/
  uv run mutmut results
```

The recommendation SHALL NOT appear when D5 total >= 4.

#### Scenario: mutmut recommendation triggered for low D5 score

- **WHEN** D5 mechanical score is 3 (only tests exist, no CI, no hook-test link) and D5 semantic score is 0
- **THEN** D5 total is 3 (< 4) and the TODO list includes the mutmut recommendation

#### Scenario: no mutmut recommendation for adequate D5 score

- **WHEN** D5 total is 7 or above
- **THEN** the TODO list does NOT include a mutmut recommendation entry

##### Example: threshold boundary (boundary value analysis)

| D5 mechanical | D5 semantic | D5 total | mutmut TODO shown |
|---------------|-------------|----------|-------------------|
| 0 | 0 | 0 | yes |
| 2 | 0 | 2 | yes |
| 3 | 0 | 3 | yes (boundary — last triggering value) |
| 3 | 1 | 4 | no (boundary — first non-triggering value) |
| 5 | 2 | 7 | no |
| 7 | 5 | 12 | no |

<!-- @trace
source: enhance-d5-behavior-harness
updated: 2026-07-18
code: []
-->

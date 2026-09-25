## Purpose

The testplan-trace capability makes a change's testplan.md an executable contract: every automated test case is bound to a test by an explicit declaration, and a single checker verifies the binding in both directions at every entry point. It exists because testplans were written and never verified, so test cases silently drifted away from the tests that were supposed to implement them.

## ADDED Requirements

### Requirement: Tests declare TC bindings through a docstring tc line

A Python test function or method SHALL declare the test cases it implements with a docstring line of the form `tc: <TC-ID>` or `tc: <TC-ID>, <TC-ID>`. The checker SHALL read docstrings through the Python `ast` module and SHALL NOT treat a TC-ID that appears anywhere else in a test file (string literals, comments, fixture data) as a binding.

#### Scenario: docstring-line-binds

- **WHEN** a test function's docstring contains the line `tc: LOGIN-VL-001, LOGIN-VL-002`
- **THEN** the checker records that test as bound to both LOGIN-VL-001 and LOGIN-VL-002

#### Scenario: literal-id-in-fixture-does-not-bind

- **WHEN** a test file contains the string `"SMK-001"` inside test data but no docstring declares `tc: SMK-001`
- **THEN** the checker records no binding for SMK-001

### Requirement: TC table declares a Kind for every test case

The testplan template SHALL include a `Kind` column in the TC table whose value is exactly `auto` or `manual`. A testplan whose TC table has no `Kind` column SHALL be treated as legacy, and every finding for it SHALL be reported as WARN.

#### Scenario: kind-column-classifies

- **WHEN** a TC table row has TC-ID `REG-DT-001` and Kind `auto`
- **THEN** the checker requires at least one test binding for REG-DT-001

#### Scenario: missing-kind-column-is-legacy

- **WHEN** a testplan's TC table has no Kind column
- **THEN** every finding the checker reports for that testplan has severity WARN

### Requirement: Unbound automated test cases are reported as missing

For every TC whose Kind is `auto` in an active change's testplan, the checker SHALL report a `missing` finding when no test docstring binds that TC-ID.

#### Scenario: auto-tc-without-test

- **WHEN** testplan row `REG-VL-001` has Kind `auto` and no test declares `tc: REG-VL-001`
- **THEN** the checker reports `missing` for REG-VL-001

### Requirement: Bindings to unknown TC-IDs are reported as orphans

The checker SHALL report an `orphan` finding for every TC-ID declared in a test's tc line that is not defined in any active or archived testplan in the repository.

#### Scenario: renamed-prefix-is-orphan

- **WHEN** a testplan defines `REG-DT-001` and a test declares `tc: FREG-DT-001`
- **THEN** the checker reports `orphan` for FREG-DT-001 and `missing` for REG-DT-001 when REG-DT-001 has Kind `auto`

### Requirement: Bindings must agree with the test case's scenario

For a test bound to a TC-ID, the checker SHALL report a `mismatch` finding when the test's `spec: <cap>#<slug>` slug is not among the scenario slugs mapped to that TC-ID in the testplan's Coverage Analysis table. A test that declares a tc line but no spec line SHALL also be reported as `mismatch`.

#### Scenario: binding-scenario-agreement

- **WHEN** Coverage Analysis maps SEVAL-DT-003 to slug `negative-untriggered-passes`
- **THEN** the checker evaluates the bound test's spec slug against that mapping

##### Example: agreement outcomes

| Test spec line | Test tc line | Finding |
| --- | --- | --- |
| `spec: skill-trigger-eval#negative-untriggered-passes` | `tc: SEVAL-DT-003` | none |
| `spec: skill-trigger-eval#baseline-regression` | `tc: SEVAL-DT-003` | mismatch |
| (absent) | `tc: SEVAL-DT-003` | mismatch |

### Requirement: A TC-ID is defined by exactly one testplan

The checker SHALL report a `collision` finding when a TC-ID defined in an active change's testplan is also defined in any other active or archived testplan.

#### Scenario: shared-prefix-collision

- **WHEN** active change A's testplan defines `PRC-DT-001` and archived change B's testplan also defines `PRC-DT-001`
- **THEN** the checker reports `collision` for PRC-DT-001 naming both changes

### Requirement: Severity ratchets from WARN to FAIL when a change claims completion

A testplan containing the line `trace: enforced` SHALL be subject to the ratchet: its findings SHALL be FAIL when the change's tasks.md has at least one checkbox and every checkbox is checked, or when the checker is invoked with `--strict`; otherwise they SHALL be WARN. A testplan without `trace: enforced` SHALL only produce WARN findings. Orphan and collision findings that cannot be attributed to a single enforced change SHALL be WARN.

#### Scenario: ratchet-matrix

- **WHEN** the checker reports a `missing` finding for an enforced or legacy testplan
- **THEN** its severity follows the ratchet table

##### Example: ratchet outcomes

| trace: enforced | tasks.md state | --strict | Severity |
| --- | --- | --- | --- |
| absent | all checked | yes | WARN |
| present | 3 of 5 checked | no | WARN |
| present | 5 of 5 checked | no | FAIL |
| present | 0 checkboxes | no | WARN |
| present | 3 of 5 checked | yes | FAIL |

### Requirement: Manual verification items have a tracked lifecycle

Test cases that cannot be automated SHALL be listed in a `## Manual Verification` section as checklist items of the form `- [ ] MV-NNN <observable check> (scenario: <slug>)`, not as TC table rows. During the pr-cycle-deep human quick pass the lead SHALL present every unchecked item to the human, record the human's result as a PR comment, and mark confirmed items as checked. Under `--strict`, the checker SHALL report a `manual-open` FAIL for every unchecked item of an enforced testplan.

#### Scenario: unchecked-manual-item-blocks-strict

- **WHEN** an enforced testplan contains `- [ ] MV-002 Reviewer sees the demoted finding in final.md (scenario: demote-without-evidence)` and the checker runs with `--strict`
- **THEN** the checker reports `manual-open` for MV-002 with severity FAIL

### Requirement: Checker exit codes separate findings from configuration errors

The checker SHALL exit 0 when no FAIL finding exists, 1 when at least one FAIL finding exists, and 2 on a configuration error: a repository root that does not exist, a `--change` name with no matching active change directory, or a testplan whose TC table cannot be parsed. A configuration error SHALL NOT be reported as a clean result.

#### Scenario: unknown-change-is-config-error

- **WHEN** the checker runs with `--change does-not-exist`
- **THEN** it prints a `[FAIL]` message naming the change on stderr and exits 2

#### Scenario: unparsable-testplan-is-config-error

- **WHEN** an enforced testplan has no parsable TC table
- **THEN** the checker exits 2 rather than reporting zero findings

### Requirement: Report mode lists bindings without modifying files

With `--report`, the checker SHALL print, for each TC, its Kind, its bound test node IDs in the form `path::Class::function`, and its finding status, and SHALL NOT write to any file. Report mode SHALL exit 0 unless a configuration error occurs.

#### Scenario: report-is-read-only

- **WHEN** the checker runs with `--report` on a repository with missing bindings
- **THEN** it prints the binding table, leaves every tracked file unchanged, and exits 0

### Requirement: Every entry point runs the same checker

The checker SHALL be the single implementation of these checks and SHALL be invoked from: a pre-commit hook in non-strict mode, the CI workflow in non-strict mode, pr-cycle-deep Step 1.5 through amplifier-verify, and pr-cycle-deep Step 11a in strict mode before archiving. amplifier-verify SHALL map FAIL findings to MUST findings and WARN findings to SHOULD findings, and SHALL exit 2 when it detects a spectra change but cannot locate the checker.

#### Scenario: archive-blocked-by-strict-failure

- **WHEN** pr-cycle-deep reaches Step 11a and the checker run with `--strict --change <name>` exits 1
- **THEN** the lead stops before running the archive and reports the FAIL findings

#### Scenario: amplifier-verify-fails-closed-without-checker

- **WHEN** amplifier-verify detects a spectra change and the sdd plugin checker cannot be located
- **THEN** amplifier-verify exits 2 with a `[FAIL]` message naming the missing checker

### Requirement: Testplan generation follows the single TC-ID convention and writes the file directly

The qa-test-designer agent SHALL assign TC-IDs using the convention selected by Convention Detection (the host's test convention rule when present, otherwise the plugin's test-convention reference) and SHALL NOT encode the test technique in the TC-ID. The agent SHALL write testplan.md directly to the path given by spectra-amplifier, including the `trace: enforced` line, the Kind column, and the Manual Verification section, and SHALL return only a summary containing the TC counts by Kind, the number of coverage gaps, and the file path.

#### Scenario: generated-testplan-is-enforced

- **WHEN** spectra-amplifier Step 2 completes for a new change
- **THEN** the change's testplan.md contains `trace: enforced`, a TC table with a Kind column, and TC-IDs without technique abbreviations such as BVA or EP

### Requirement: Generated tasks put a failing bound test first

When spectra-amplifier generates tasks.md, the first task under each User Story SHALL be to write failing tests bound with tc lines to that story's `auto` TC-IDs, listing those TC-IDs; implementation tasks for the story SHALL follow it.

#### Scenario: red-first-task-order

- **WHEN** User Story US-002 has auto TC-IDs REG-VL-001 and REG-DT-002
- **THEN** the first task under US-002 in tasks.md names REG-VL-001 and REG-DT-002 and precedes every implementation task of US-002

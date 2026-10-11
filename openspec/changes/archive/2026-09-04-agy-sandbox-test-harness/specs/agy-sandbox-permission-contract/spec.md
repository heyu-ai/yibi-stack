## ADDED Requirements

### Requirement: Permission flag contract is test-pinned

Each agy shell script in pr-cycle-deep SHALL use a specific, tested permission flag that matches its operational needs. The contract SHALL be enforced by static assertions in the test suite.

- `agy-r1-stage1.sh` and `agy-r2.sh` SHALL use the permission-bypass flag (they require the `command` tool for exploring surrounding code during review).
- `agy-r1-stage2.sh` SHALL use `--sandbox` (extraction-only task; no `command` tool needed).
- Each script SHALL NOT contain both the permission-bypass flag and `--sandbox` in its agy invocation line.

#### Scenario: review-flag-regressed-to-sandbox -- Review script permission flag regressed to sandbox

**GIVEN** `agy-r1-stage1.sh` or `agy-r2.sh` contains the permission-bypass flag in its agy invocation line
**WHEN** a developer changes the flag to `--sandbox`
**THEN** `TestPermissionFlagContract::test_agys_dt_014` MUST fail with an assertion message naming the script and the missing flag

**Boundary values**:
- Script has permission-bypass flag only -> PASS
- Script has `--sandbox` only -> FAIL
- Script has both flags -> FAIL (mutual exclusion violated)

##### Example: stage1 flag mutation matrix

| Script | Flag present | Flag absent | Expected test result |
|--------|-------------|-------------|---------------------|
| agy-r1-stage1.sh | permission-bypass | --sandbox | PASS |
| agy-r1-stage1.sh | --sandbox | permission-bypass | FAIL |
| agy-r1-stage1.sh | both | n/a | FAIL |
| agy-r2.sh | permission-bypass | --sandbox | PASS |
| agy-r2.sh | --sandbox | permission-bypass | FAIL |

#### Scenario: extract-flag-regressed-to-bypass -- Extract script permission flag regressed to bypass

**GIVEN** `agy-r1-stage2.sh` contains `--sandbox` in its agy invocation line
**WHEN** a developer changes it to the permission-bypass flag
**THEN** `TestPermissionFlagContract::test_agys_dt_015` MUST fail with an assertion message naming the script and the unexpected flag

#### Scenario: mutual-exclusion-violated -- Same script contains both flags

**GIVEN** any of the three agy scripts
**WHEN** both `--sandbox` and the permission-bypass flag appear in the same script's agy invocation
**THEN** `TestPermissionFlagContract::test_agys_dt_016` MUST fail with an assertion message indicating mutual exclusion violation

### Requirement: Sandbox auto-deny produces detectable failure

When agy is invoked with `--sandbox` in headless mode and the `command` tool is auto-denied, the calling script SHALL detect the failure condition (exit 0 + empty stdout + stderr auto-deny message) and exit non-zero with a `[FAIL]` diagnostic.

#### Scenario: stub-auto-deny-detected -- Stub simulates sandbox auto-deny and script catches it

**GIVEN** a fake agy stub on PATH that, when invoked with `--sandbox`, exits 0 with empty stdout and writes "no output produced -- a tool required the command permission" to stderr
  AND a temporary git repo with the required precondition files (`gemini-r1-raw.md`, `changed-files.txt`, `prompt-r1.md`)
**WHEN** `agy-r1-stage2.sh` is executed in this environment
**THEN** the script MUST exit non-zero
  AND stderr MUST contain `[FAIL]`

##### Example: auto-deny detection matrix

| Script | Uses --sandbox? | Stub behavior | Expected script exit |
|--------|----------------|---------------|---------------------|
| agy-r1-stage2.sh | yes | auto-deny (empty stdout, exit 0) | non-zero + [FAIL] |
| agy-r1-stage2.sh | yes | normal output | zero (success) |

#### Scenario: genuine-sandbox-empty-output -- Extract script detects genuine empty output

**GIVEN** `agy-r1-stage2.sh` runs with `--sandbox`
**WHEN** agy produces empty output (for any reason, not specifically auto-deny of `command`)
**THEN** the script MUST detect the empty output via its existing guard (`-s` check or `agy_validate.py`)
  AND exit non-zero with a `[FAIL]` diagnostic on stderr

### Requirement: Version probe script validates sandbox behavior assumptions

A manual probe script SHALL exist to verify that agy's sandbox behavior matches the assumptions encoded in the shell scripts. The probe SHALL be executable via a Makefile target.

#### Scenario: probe-sandbox-file-read -- Probe verifies sandbox allows file reads

**GIVEN** agy is installed and authenticated
  AND a test file exists in a known absolute path
**WHEN** the probe invokes agy with `--sandbox --add-dir <absolute-path>` and a prompt requesting file content
**THEN** agy MUST return non-empty output containing the expected file content
  AND the probe MUST print `[PASS] sandbox-file-read`

#### Scenario: probe-sandbox-command-deny -- Probe verifies sandbox denies command tool

**GIVEN** agy is installed and authenticated
**WHEN** the probe invokes agy with `--sandbox` and a prompt that requires `command` tool execution
**THEN** agy MUST produce empty or refusal output (auto-deny)
  AND the probe MUST print `[PASS] sandbox-command-deny` (confirming the assumption holds)

#### Scenario: probe-bypass-full-access -- Probe verifies bypass flag grants full access

**GIVEN** agy is installed and authenticated
**WHEN** the probe invokes agy with the permission-bypass flag and a prompt requiring both file reads and command execution
**THEN** agy MUST return non-empty output with both file content and command output
  AND the probe MUST print `[PASS] bypass-full-access`

#### Scenario: probe-no-auth-graceful -- Probe handles missing auth gracefully

**GIVEN** agy is NOT authenticated (no valid credentials)
**WHEN** the probe script is executed
**THEN** the probe MUST detect the missing auth condition
  AND print `[SKIP] agy not authenticated` for each probe
  AND exit 0 (not an error, just a skip)

##### Example: probe output format

| Probe name | agy authenticated | Expected output | Exit code |
|------------|-------------------|-----------------|-----------|
| sandbox-file-read | yes | [PASS] sandbox-file-read (agy X.Y.Z) | 0 |
| sandbox-command-deny | yes | [PASS] sandbox-command-deny (agy X.Y.Z) | 0 |
| bypass-full-access | yes | [PASS] bypass-full-access (agy X.Y.Z) | 0 |
| sandbox-file-read | no | [SKIP] agy not authenticated | 0 |
| any probe | yes, behavior flipped | [FAIL] sandbox-file-read (agy X.Y.Z) | 1 |

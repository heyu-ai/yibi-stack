# agy-sandbox-permission-contract Specification

## Purpose

TBD - created by archiving change 'agy-sandbox-test-harness'. Update Purpose after archive.

## Requirements

### Requirement: Permission contract is behaviorally test-pinned

Each agy invocation in pr-cycle-deep SHALL use a specific permission flag that matches its operational needs. The test suite SHALL enforce the resulting exploration and write-protection behavior through script execution, not static source-text assertions.

- `agy-r1-stage1.sh` and `agy-r2.sh`, through `agy_isolate.py`, SHALL use the permission-bypass flag to permit `command` exploration inside a protected committed-HEAD snapshot with a private HOME.
- R1/R2 SHALL retain OS write isolation for the original worktree, Git metadata, and snapshot source files; unavailable or ineffective isolation SHALL fail closed.
- `agy-r1-stage2.sh` SHALL use `--sandbox` without permission bypass. Extraction SHALL NOT authorize writes, even if the model requests them.
- No agy invocation SHALL combine the permission-bypass flag and `--sandbox`.

#### Scenario: review-permissions-and-isolation -- Review permits exploration within the OS write boundary

**GIVEN** the real-OS fixture in `test_agy_isolate.py` executes either R1 Stage 1 or R2
**WHEN** the fake external reviewer reads the committed snapshot and attempts protected writes directly and through a command child
**THEN** `test_real_os_contains_review_and_keeps_artifacts` MUST observe the expected review artifacts and blocked writes
  AND the original worktree, Git metadata, and snapshot source files MUST remain unchanged
  AND a permission regression that prevents the required review execution MUST fail the test

#### Scenario: extract-permissions-prevent-writes -- Extraction does not authorize model-requested writes

**GIVEN** `test_agys_st_013_extraction_does_not_authorize_writes` executes Stage 2 with a fake external agy that attempts a source-file write when sandbox protection is absent or permission bypass is present
**WHEN** extraction completes under the configured permissions
**THEN** the source-file bytes MUST remain unchanged
  AND the script MUST publish valid extracted JSON with a denial diagnostic
  AND removing `--sandbox`, replacing it with permission bypass, or adding permission bypass alongside it MUST fail this behavioral test

This test pins the caller's permission choice using an external CLI stub. It does not
verify the real agy's sandbox implementation; that remains the separate manual probe
below. Stage 2 has no additional OS write sandbox; R1/R2 containment is tested against
the real OS backend.

##### Example: behavioral permission regression matrix

| Invocation | Regression | Required observable protection |
|------------|------------|--------------------------------|
| R1 Stage 1 / R2 | Review cannot explore its protected snapshot | Real-OS review/artifact test fails |
| R1 Stage 1 / R2 | Protected write succeeds | Real-OS containment test fails |
| Stage 2 | Sandbox absent or permission bypass present, including both flags | Source-file preservation test fails |

---
### Requirement: Sandbox auto-deny produces detectable failure

When agy is invoked with `--sandbox` in headless stream-json mode and the `command` tool is auto-denied, the calling script SHALL reject an incomplete or empty answer and exit non-zero with a `[FAIL]` diagnostic. An upstream exit 0 is not sufficient: auto-deny may produce no terminal result or a terminal `SUCCESS` result with an empty `response`. The stream decoder SHALL fail closed in both cases.

#### Scenario: stub-auto-deny-detected -- Stub simulates sandbox auto-deny and script catches it

**GIVEN** a fake external agy on PATH exits 0 after reporting sandbox command denial on stderr
  AND it emits either no terminal result or a terminal `SUCCESS` result with an empty `response`
  AND a temporary git repo contains the required successful Stage 1 raw review and extraction inputs
**WHEN** `agy-r1-stage2.sh` is executed in this environment
**THEN** the script MUST exit non-zero
  AND stderr MUST contain `[FAIL]`
  AND no extracted JSON from the failed invocation MUST be published

Coverage is layered: `test_agys_st_005_stage2_detects_empty_output` exercises the
no-terminal auto-deny path through Stage 2; `test_agyst_002_invalid_or_incomplete_result_is_not_success`
covers an empty SUCCESS response at the decoder boundary. `test_agys_st_011_stream_failure_is_not_published`
exercises failure-code propagation and absence of a published extraction artifact.
These are complementary checks, not a claim that ST-005 executes every row below.

##### Example: auto-deny detection matrix

| Script | Uses --sandbox? | Stream behavior with upstream exit 0 | Expected script exit |
|--------|----------------|-------------------------------------|---------------------|
| agy-r1-stage2.sh | yes | No terminal result | non-zero + [FAIL] |
| agy-r1-stage2.sh | yes | Terminal SUCCESS with empty response | non-zero + [FAIL] |
| agy-r1-stage2.sh | yes | Valid terminal SUCCESS with valid extraction response | zero (success) |

#### Scenario: genuine-sandbox-empty-output -- Extract script detects genuine empty output

**GIVEN** `agy-r1-stage2.sh` runs with `--sandbox`
**WHEN** agy produces no terminal result or an empty terminal response, for any reason
**THEN** `agy_stream.py` MUST reject the stream
  AND the script MUST exit non-zero with a `[FAIL]` diagnostic before validation or JSON extraction

---
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

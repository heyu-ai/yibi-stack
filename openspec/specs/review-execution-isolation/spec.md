# review-execution-isolation Specification

<!-- @trace-sidecar: spec.trace.yaml -->

## Purpose

Keep agy review exploration separate from source mutation through a protected disposable snapshot,
while preserving diagnostics and bounded process cleanup.

## Requirements

### Requirement: Reviewers execute inside a protected disposable snapshot

agy R1 and R2 MUST read the complete committed HEAD tree in a disposable snapshot. Their working
 directory and absolute add-dir MUST identify that snapshot. The original checkout, its Git metadata,
 and snapshot source MUST NOT be writable by the reviewer or its descendants through relative,
 absolute, or symlink paths. Untracked files MUST NOT be copied. Dirty tracked trees MUST fail loudly.

#### Scenario: write attempts cannot mutate source

- **GIVEN** a committed source file and a link addressing the original checkout
- **WHEN** the reviewer attempts relative, absolute, symlink and shared-Git-metadata writes
- **THEN** OS containment rejects those writes and the original bytes remain unchanged
- **AND** the reviewer can still read the committed source

#### Scenario: protection unavailable

- **WHEN** the required OS containment backend is absent or unusable
- **THEN** the wrapper fails before agy executes and never retries without containment

#### Scenario: tracked changes not represented by HEAD

- **WHEN** the checkout has uncommitted tracked changes or unresolved conflicts
- **THEN** review fails rather than silently reviewing an older snapshot

---
### Requirement: Isolation preserves review output and cleanup contracts

The wrappers MUST preserve prompt/model/budget inputs, output names, validator and timeout behavior,
and original-worktree before/after comparison. After terminating the owned review process group
on success, failure, timeout, SIGINT or SIGTERM, they MUST attempt to remove helper-owned state.
They MUST NOT report success when cleanup is incomplete. Any cleanup failure MUST produce a
nonzero exit and a diagnostic identifying the remaining workspace, without following symlinks
or changing permissions of targets outside helper-owned directories.

#### Scenario: reviewer fails after producing diagnostic output

- **GIVEN** the helper-owned state can be removed by its owner
- **WHEN** agy exits nonzero after writing a log
- **THEN** the wrapper retains the diagnostic artifact, checks the original tree and returns failure
- **AND** no helper-owned temporary directory or process in the owned review process group remains

#### Scenario: interrupted review

- **WHEN** the wrapper receives a termination signal during review
- **THEN** the process group is stopped before temporary snapshot cleanup
- **AND** the original checkout is unchanged

#### Scenario: timeout remains distinguishable

- **WHEN** a reviewer exceeds its budget or reports a print timeout
- **THEN** partial output is quarantined under the existing timeout artifact contract
- **AND** it is not admitted as a successful review

#### Scenario: cleanup-denied-is-not-success

- **GIVEN** the reviewer created an immutable file inside its private scratch
- **WHEN** the reviewer exits successfully but the OS refuses deletion of that file
- **THEN** the helper MUST exit nonzero and name the remaining workspace in a failure diagnostic
- **AND** the original checkout and external symlink targets MUST remain unchanged
- **AND** the failure MUST NOT be concealed by ignore-errors cleanup

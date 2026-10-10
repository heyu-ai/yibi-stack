## Purpose

Defines the code state that the issue-triage skill verifies issue symptoms against. It exists because a verdict computed against a stale or unmerged checkout silently inverts the meaning of DONE and NOT DONE.

## ADDED Requirements

### Requirement: Fetch before verification

Before any step that verifies an issue or bug symptom against repository code, the skill SHALL fetch the main branch from the origin remote. A failed fetch SHALL stop the run with a failure message and SHALL NOT fall back to the local copy of the remote-tracking ref. This requirement SHALL apply to runs that triage GitHub issues, Jira bugs, or a single item.

#### Scenario: Fetch succeeds

- **WHEN** the skill starts a run that will verify symptoms against code and the origin remote is reachable
- **THEN** the origin main ref is refreshed before the first symptom is verified

#### Scenario: Fetch fails

- **WHEN** the fetch of origin main fails because the remote is unreachable
- **THEN** the run stops with a failure message that names the fetch failure and no symptom is verified

#### Scenario: Jira-only run

- **WHEN** the skill runs with a Jira project and verifies bug symptoms against code
- **THEN** the fetch and baseline checks still run before the first verification

### Requirement: Checkout must equal the origin main commit

After the fetch, the skill SHALL verify that the commit under inspection equals the origin main commit and that no tracked file in the working tree has uncommitted modifications. When the checkout is ahead of or behind origin main, or has modified tracked files, the run SHALL stop with a failure message that states the ahead count, the behind count, or the modified file count, and that names the remedy: run from a clean worktree created from origin main, or update the main checkout. A tracked file whose modification is hidden from the working-tree status by an assume-unchanged or skip-worktree index flag SHALL count as modified when it exists on disk with content that differs from the origin main commit; a flagged file that is absent from disk SHALL NOT count. Untracked files SHALL NOT cause a failure.

#### Scenario: Checkout is behind

- **WHEN** the current commit is an ancestor of origin main and origin main is 7 commits ahead
- **THEN** the run stops with a failure message stating the behind count of 7

#### Scenario: Checkout is on an unmerged branch

- **WHEN** the current commit has 2 commits that origin main does not contain
- **THEN** the run stops with a failure message stating the ahead count of 2

#### Scenario: Tracked file modified

- **WHEN** the current commit equals origin main and one tracked file has uncommitted changes
- **THEN** the run stops with a failure message stating the modified file count of 1

#### Scenario: Hidden tracked modification

- **WHEN** the current commit equals origin main and one tracked file carries an assume-unchanged or skip-worktree flag while its content on disk differs from the origin main commit
- **THEN** the run stops with a failure message stating the modified file count of 1, even though the working-tree status reports no change

#### Scenario: Clean and equal

- **WHEN** the current commit equals origin main and no tracked file is modified
- **THEN** the baseline check passes and the run continues

### Requirement: Distinct exit codes for baseline failures

The baseline check SHALL be implemented as a standalone script whose exit code distinguishes each outcome: 0 for a passing baseline, a distinct non-zero code for a fetch failure, a distinct non-zero code for a commit mismatch, a distinct non-zero code for modified tracked files, and a distinct non-zero code for a run outside a git repository. The skill document SHALL name every code and its meaning, and SHALL NOT collapse the non-zero codes into a single failure branch.

#### Scenario: Each failure is distinguishable

- **WHEN** the script is run against four fixtures: an unreachable remote, a behind checkout, a checkout with a modified tracked file, and a directory outside any git repository
- **THEN** the four runs exit with four pairwise different non-zero codes

#### Scenario: Passing baseline

- **WHEN** the script is run against a clean checkout equal to origin main
- **THEN** it exits with code 0

### Requirement: Baseline commit recorded in the report

The report SHALL record at its top the full commit SHA of the origin main commit used as the evidence baseline and the time the fetch completed, so that two runs of the skill can be compared and a stale result can be recognized.

#### Scenario: Report header

- **WHEN** a run completes and writes its report
- **THEN** the first section of the report states the baseline commit SHA and the fetch time

### Requirement: Baseline check is verified by a negative control

The baseline check SHALL have an automated test that feeds it each known-bad checkout state and asserts a failure, in addition to a test that asserts the passing state. A test that only asserts the passing state SHALL NOT be accepted as coverage of this capability.

#### Scenario: Short-circuited check is detected

- **WHEN** the baseline script is modified to always exit with code 0
- **THEN** the automated tests fail

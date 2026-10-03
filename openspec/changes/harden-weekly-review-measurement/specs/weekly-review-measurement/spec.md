## Purpose

The weekly-review-measurement capability defines when harness-weekly-review may conclude that a previous week's recommendation is resolved. It exists because the review used to infer "resolved" from the absence of a recommendation, so any unlisted read failure silently turned an unmeasured problem into a resolved one.

## ADDED Requirements

### Requirement: Every data source reports completeness that defaults to incomplete

Each collector SHALL return a source record with a `complete` boolean and an `errors` list. `complete` SHALL be true only when directory listing, every file read, and every line parse for that source succeeded. Any failure SHALL append to `errors` and leave `complete` false. Directory listing SHALL report errors instead of returning an empty result.

#### Scenario: unreadable-hook-events-file

- **WHEN** one monthly hook-events file in the observation window cannot be read
- **THEN** the hook-events source record has `complete` false and its `errors` names that file

#### Scenario: unreadable-rules-directory

- **WHEN** the rules directory cannot be listed
- **THEN** the rules source record has `complete` false instead of reporting zero rules

#### Scenario: truncated-transcript-line

- **WHEN** a transcript file in the window contains a line that is not valid JSON
- **THEN** the transcript source record has `complete` false

#### Scenario: unreadable-hook-script

- **WHEN** a hook script referenced by the inventory cannot be read
- **THEN** the hook inventory source record has `complete` false and no hook-unregistered recommendation is produced for that hook

### Requirement: Missing or malformed completeness fields are treated as unmeasured

The evaluation scope SHALL treat a source whose record is missing, has the wrong type, or has `complete` not equal to true as unmeasured. A missing CI `measured` field SHALL be treated as unmeasured and SHALL NOT raise an exception.

#### Scenario: snapshot-without-source-record

- **WHEN** a snapshot has no source record for workflows
- **THEN** every recommendation kind that depends on the gate inventory (gate-unwired and gate-silent) is outside the evaluation scope

#### Scenario: snapshot-without-ci-measured

- **WHEN** a snapshot's ci object has no `measured` field
- **THEN** evaluation completes and every CI-dependent kind is outside the evaluation scope

### Requirement: A previous recommendation is resolved only with positive evidence

A recommendation present last week and absent this week SHALL be reported as resolved only when its kind's source is complete this week and the recommended object was observed this week with at least the kind's sample threshold, or the object is shown not to exist any more by a complete source. Otherwise it SHALL be reported as unmeasured and carried forward. For hook-error, hook-slow and hook-silent-block the sample threshold is three invocations, the same threshold that produces such a recommendation. For gate-silent the observation is at least one run, within the observation window, of the workflow that contains the gate. Plugin hooks outside the repository's hook registry have no invocation count, so their hook-silent-block recommendations stay unmeasured.

#### Scenario: hook-below-sample-threshold

- **WHEN** last week had a hook-slow recommendation for hook H and this week H was invoked fewer times than the hook sample threshold
- **THEN** the recommendation is reported as unmeasured and carried, not resolved

#### Scenario: hook-not-observed

- **WHEN** last week had a hook-error recommendation for hook H and this week's hook statistics contain no entry for H
- **THEN** the recommendation is reported as unmeasured and carried

#### Scenario: hook-observed-and-clean

- **WHEN** last week had a hook-error recommendation for hook H, the hook-events source is complete, and H was invoked at least the sample threshold with no errors
- **THEN** the recommendation is reported as resolved

#### Scenario: gate-job-never-ran

- **WHEN** last week had a gate-silent recommendation for gate G and no run of the workflow that contains G falls in the observation window
- **THEN** the recommendation is reported as unmeasured

#### Scenario: hook-removed

- **WHEN** last week had a hook-error recommendation for hook H and this week's complete hook registry no longer contains H
- **THEN** the recommendation is reported as resolved, because the object no longer exists

#### Scenario: plugin-hook-silent-block-without-calls

- **WHEN** last week had a hook-silent-block recommendation for a hook that is not in the repository's hook registry and this week's statistics have no entry for it
- **THEN** the recommendation is reported as unmeasured and carried, not resolved

### Requirement: Gate attribution uses exact identity only

Gate-silent attribution SHALL match a CI failure to a gate only when the failed step name is exactly equal to the name of a step that invokes the gate; a name that merely contains part of the gate's file name SHALL NOT match, whether it is a job name or a step name. A gate SHALL be unattributable when the name of a step that invokes it is also used by a step that does not invoke it, so that an exact step name identifies the gate across all workflows. A gate SHALL also be unattributable when any step name in its workflow file contains a dynamic expression, an escape sequence that cannot be fully decoded, or a multi-line plain scalar. YAML scalar parsing SHALL return no value rather than a partial value when it cannot decode the whole scalar.

#### Scenario: unrelated-job-sharing-substring

- **WHEN** gate rule-gate-docs exists and the only CI failure is in job build-docs, or in a step whose name merely contains the word docs
- **THEN** gate rule-gate-docs is not credited with a block

#### Scenario: dynamic-step-name

- **WHEN** a workflow containing gate G has another step whose name contains a dynamic expression
- **THEN** G is unattributable and no gate-silent recommendation about G is resolved

#### Scenario: multiline-plain-name

- **WHEN** a step name is a plain scalar continued on the next line
- **THEN** the parsed name is no value and the step is unattributable

### Requirement: Gate added date is unknown when history cannot establish it

The gate added date SHALL be determined with rename following. When the repository is a shallow clone, or whether it is one cannot be determined, the added date SHALL be unknown, and gate-silent recommendations SHALL be unmeasured.

#### Scenario: shallow-clone

- **WHEN** the review runs in a shallow clone
- **THEN** every gate added date is unknown and no gate-silent recommendation is resolved

#### Scenario: renamed-gate

- **WHEN** a gate script was renamed after it was first added
- **THEN** its added date is the date it was first added, not the date of the rename

### Requirement: Streaks reset visibly when the previous snapshot lacks carry data

When the previous snapshot has no carried or weeks data, every continuing recommendation SHALL be marked with streak reset, and the report SHALL state that the previous snapshot was produced without a report step.

#### Scenario: previous-snapshot-collect-only

- **WHEN** the previous snapshot was produced by collect and never passed through report
- **THEN** continuing recommendations carry streak reset true and the report names the reason

### Requirement: CI run listing is verified against its declared total

The CI collector SHALL compare the number of listed runs with the response's declared total count and SHALL mark CI incomplete when the response lacks the runs list, lacks the total, or the counts disagree.

#### Scenario: runs-response-wrong-shape

- **WHEN** a runs page response has no workflow runs list
- **THEN** CI is marked incomplete instead of reporting zero failures

### Requirement: Read-failure injection is tested per source family

The test suite SHALL inject, for every collector, a file read failure, a directory listing failure, a malformed line, and where applicable a malformed API response, and SHALL assert that no previous recommendation becomes resolved. Each injection point SHALL be covered by at least one test that fails when the corresponding failure handling is removed.

#### Scenario: injection-matrix

- **WHEN** the injection tests run against a previous snapshot holding one recommendation of every kind
- **THEN** for every injected failure, no recommendation dependent on the failed source is reported as resolved

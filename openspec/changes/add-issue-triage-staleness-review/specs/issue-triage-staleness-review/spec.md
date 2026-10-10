## Purpose

Defines how the issue-triage skill detects GitHub issues that are obsolete or long inactive, and how it escalates review depth with age without ever closing an issue on age alone. It exists because the skill otherwise biases only against wrongful closure and lets obsolete issues accumulate indefinitely.

## ADDED Requirements

### Requirement: Last substantive human activity measurement

The skill SHALL compute, for every open GitHub issue, the timestamp of its last substantive human activity as the latest of the issue creation time and the creation time of every comment that is neither bot-authored nor posted by the triage skill itself. A comment SHALL be treated as bot-authored when GitHub reports the author's account type as Bot. The determination SHALL NOT rely on the login text, because the issue list JSON strips the "[bot]" suffix (the account github-actions[bot] appears there as github-actions) and some bot accounts, such as Copilot, never carry the suffix. A comment whose author account was deleted (empty login) SHALL be treated as human activity. A comment SHALL be treated as posted by the triage skill only when the last non-empty line of its body is exactly one complete triage marker as defined in the marker requirement below and it was authored by the account that is running the skill; a comment that merely mentions the marker prefix, whose marker is not on its last non-empty line, whose marker kind is not one of the known kinds, or whose marker lacks the date, SHALL count as substantive human activity, as SHALL a comment that ends with a complete marker but was written by any other account. Label changes, assignee changes, and reactions SHALL NOT count as activity. The number of days since this timestamp is the issue's inactivity age.

#### Scenario: Triage comment does not reset the clock

- **WHEN** an issue was created 200 days ago, its only comment was posted 5 days ago by the triage skill and carries the triage marker
- **THEN** the issue's inactivity age is 200 days

#### Scenario: Pasted marker from another account counts as activity

- **WHEN** an issue was created 200 days ago and a different account posted a comment 2 days ago whose body contains the triage marker
- **THEN** the issue's inactivity age is 2 days

#### Scenario: Incomplete marker is human activity

- **WHEN** an issue was created 200 days ago and the account running the skill posted a comment 2 days ago that mentions the marker prefix in prose without a date or closing, or whose last line is a marker of an unknown kind such as stale-notice-foo, or whose complete marker is followed by further text
- **THEN** the comment counts as substantive human activity, is not recognized as a stale notice, and the issue's inactivity age is 2 days

#### Scenario: Bot comment does not reset the clock

- **WHEN** the latest comment on an issue was posted 3 days ago by the account github-actions[bot], which the issue list JSON shows as github-actions, and the latest human comment is 120 days old
- **THEN** the issue's inactivity age is 120 days

#### Scenario: Bot account without a login suffix

- **WHEN** the latest comment on an issue was posted 2 days ago by the account Copilot whose reported type is Bot, and the latest human comment is 90 days old
- **THEN** the issue's inactivity age is 90 days

#### Scenario: Deleted author counts as human

- **WHEN** the latest comment on an issue was posted 6 days ago by an author with an empty login
- **THEN** the issue's inactivity age is 6 days

#### Scenario: Issue without comments

- **WHEN** an issue has no comments and was created 45 days ago
- **THEN** the issue's inactivity age is 45 days

### Requirement: Triage marker on every skill-authored comment

Every comment that the skill posts to an issue (stale notice, closing note, scope update, merge note) SHALL end with, as its last non-empty line, an HTML comment of the exact form issue-triage, a colon, the comment kind, a space, and an ISO date (YYYY-MM-DD), where the kind is one of close, update-scope, merge, and stale-notice. The marker SHALL be present on comments posted under the apply path for every verdict that posts a comment.

#### Scenario: Closing note carries the marker

- **WHEN** the skill posts a closing note for an obsolete issue during an apply run
- **THEN** the comment body contains the triage marker with kind "close" and the run date

#### Scenario: Scope update carries the marker

- **WHEN** the skill posts an UPDATE-SCOPE comment during an apply run
- **THEN** the comment body contains the triage marker with kind "update-scope" and the run date

#### Scenario: Merge note carries the marker

- **WHEN** the skill posts a comment on a GitHub issue while merging it into another issue during an apply run
- **THEN** the last line of the comment body is the triage marker with kind "merge" and the run date

### Requirement: Inactivity tiers escalate the evidence burden

The skill SHALL assign each issue to an inactivity tier and SHALL apply the tier's requirements in both the fast and the deep depth modes. The cross-check against archived changes and ADRs SHALL remain restricted to the deep depth mode.

| Tier | Inactivity age | Additional requirement |
|------|----------------|------------------------|
| 0 | fewer than 30 days | none beyond the standard flow |
| 1 | 30 to 89 days | the code drift signal SHALL be collected and reported |
| 2 | 90 to 179 days | the code drift signal SHALL be collected, and a KEEP verdict SHALL cite affirmative evidence that the issue's premise still holds |
| 3 | 180 days or more | all tier 2 requirements, and the issue becomes eligible for the STALE-CANDIDATE verdict |

The tier boundaries are initial values and SHALL be presented to the user for calibration on the first run. When no affirmative evidence can be found for a tier 2 or tier 3 KEEP, the verdict SHALL remain KEEP, the report SHALL flag the issue as premise-unverified, and the flag SHALL NOT by itself cause a close recommendation.

#### Scenario: Tier 2 KEEP requires affirmative evidence

- **WHEN** an issue with 100 days of inactivity has all symptoms NOT DONE and its referenced files still exist unchanged on the baseline
- **THEN** the KEEP verdict in the report cites the existing files as evidence that the premise still holds

#### Scenario: Tier 2 KEEP without affirmative evidence is flagged

- **WHEN** an issue with 100 days of inactivity references no repository paths and the symptom verification could not confirm that the affected behavior still exists
- **THEN** the verdict stays KEEP, the report flags the issue as premise-unverified, and no close is recommended

#### Scenario: Tier 1 collects drift only

- **WHEN** an issue with 40 days of inactivity is triaged in fast depth mode
- **THEN** the report includes the code drift result for the issue and no STALE-CANDIDATE verdict is produced

##### Example: tier assignment

| Inactivity age (days) | Tier |
|-----------------------|------|
| 0 | 0 |
| 29 | 0 |
| 30 | 1 |
| 89 | 1 |
| 90 | 2 |
| 179 | 2 |
| 180 | 3 |
| 400 | 3 |

### Requirement: Code drift signal

For every repository-relative file path referenced in an issue body, the skill SHALL report its state on the evidence baseline as one of: unchanged since the issue creation time, changed since the issue creation time with the number of commits, deleted, or renamed. A path that does not exist on the baseline and is neither deleted nor renamed in history SHALL be reported as never existed. A never-existed state SHALL NOT by itself demonstrate that a premise has vanished, because it usually means the issue mistyped the path. Drift collection SHALL be implemented by a standalone script so that the skill document contains a single script invocation instead of multi-step shell logic.

#### Scenario: Referenced file was deleted

- **WHEN** an issue created 150 days ago references a path that a commit on the baseline deleted 60 days ago
- **THEN** the drift signal for that path is reported as deleted with the deleting commit

#### Scenario: Referenced file changed repeatedly

- **WHEN** an issue created 150 days ago references a path that 12 commits on the baseline modified since then
- **THEN** the drift signal for that path is reported as changed with a count of 12 commits

#### Scenario: Issue references no paths

- **WHEN** an issue body contains no repository-relative file path
- **THEN** the drift signal is reported as not applicable and the absence of drift is not treated as evidence that the premise holds

#### Scenario: Never-existed path is not evidence of absence

- **WHEN** an issue references a path that never existed anywhere in the baseline history
- **THEN** the drift signal is reported as never existed and the issue does not receive the OBSOLETE verdict on that basis

### Requirement: OBSOLETE verdict

The skill SHALL assign the OBSOLETE verdict to an issue only when every unresolved symptom's premise artifacts (files, symbols, features, or changes the symptom depends on) are demonstrated absent on the evidence baseline, and no exemption applies. A search that returns zero hits SHALL NOT by itself demonstrate absence: the verdict requires a positive control showing that the same search method finds a known existing artifact in the same location, and a search directory that does not exist SHALL yield the UNCLEAR outcome for that symptom. When only some unresolved symptoms have lost their premise, the verdict SHALL be UPDATE-SCOPE and not OBSOLETE. The recommended closing reason for OBSOLETE SHALL be "not planned" and SHALL NOT be "completed".

#### Scenario: Premise artifacts removed with positive control

- **WHEN** every unresolved symptom of an issue references a module that no longer exists on the baseline, and a search for a known existing module in the same parent directory succeeds
- **THEN** the verdict is OBSOLETE and the recommended closing reason is "not planned"

#### Scenario: Zero hits without positive control

- **WHEN** a search for a symptom's artifact returns zero hits and the search directory does not exist on the baseline
- **THEN** that symptom's outcome is UNCLEAR and the issue does not receive the OBSOLETE verdict

#### Scenario: Partial loss of premise

- **WHEN** one unresolved symptom's artifact was removed and another unresolved symptom's artifact still exists and is unfixed
- **THEN** the verdict is UPDATE-SCOPE

### Requirement: STALE-CANDIDATE verdict and grace period

The skill SHALL assign the STALE-CANDIDATE verdict only to an issue that would otherwise receive KEEP, whose inactivity age is 180 days or more, whose premise has not been shown absent, and to which no exemption applies. The recommended action for a first-time STALE-CANDIDATE SHALL be to post a stale notice asking whether the issue is still needed, stating a grace period of 14 days. A stale notice marker SHALL be recognized only on a comment authored by the account that is running the skill. When an issue already carries a recognized stale notice marker, at least 14 days have elapsed since that notice, and no substantive human activity occurred after it, the skill SHALL recommend closing the issue with reason "not planned". When substantive human activity occurred after the notice, the issue SHALL be evaluated as if no notice existed. The skill SHALL NOT recommend closing any issue on the basis of inactivity age alone, without a prior stale notice and an elapsed grace period. Before a closing comment is posted after an elapsed grace period, the skill SHALL measure the inactivity again and SHALL cancel the close when substantive human activity occurred after the notice.

#### Scenario: First stale candidate

- **WHEN** an otherwise-KEEP issue has 200 days of inactivity, no exemption, and no stale notice marker
- **THEN** the verdict is STALE-CANDIDATE and the recommended action is to post a stale notice with a 14 day grace period

#### Scenario: Grace period elapsed without response

- **WHEN** an issue carries a stale notice marker dated 20 days ago and has no substantive human activity after it
- **THEN** the recommended action is to close the issue with reason "not planned"

#### Scenario: Human responds during grace period

- **WHEN** an issue carries a stale notice marker dated 10 days ago and a human commented 4 days ago
- **THEN** the issue is evaluated as if no stale notice existed and its inactivity age is 4 days

#### Scenario: Stale notice marker from another account is ignored

- **WHEN** an issue has 200 days of inactivity and the only comment containing a stale notice marker was authored by a different account 30 days ago
- **THEN** the marker is not recognized, that comment counts as human activity, and the issue's inactivity age is 30 days

#### Scenario: Age alone never closes

- **WHEN** an otherwise-KEEP issue has 900 days of inactivity and no stale notice marker
- **THEN** the recommended action is never a close and is at most the stale notice

#### Scenario: Reply arrives between the verdict and the write

- **WHEN** the report recommended closing an issue after an elapsed grace period and a human commented before the user confirmed the close
- **THEN** the skill measures the inactivity again before writing, cancels the close, and lists the issue as cancelled because of new activity

### Requirement: Exemptions from staleness verdicts

An issue SHALL NOT receive the STALE-CANDIDATE verdict and SHALL NOT receive an age-based close recommendation when any of the following holds: it carries a security-related label, it has at least one assignee, it has a milestone whose due date is in the future, it is bound to an active openspec change, or a comment by an author whose association is OWNER, MEMBER, or COLLABORATOR states that the issue is to be kept open. The report SHALL list each exempt issue together with the exemption reason.

#### Scenario: Assigned issue is exempt

- **WHEN** an otherwise-KEEP issue has 300 days of inactivity and one assignee
- **THEN** the verdict is KEEP and the report lists the exemption reason "assigned"

#### Scenario: Keep-open comment from a non-maintainer

- **WHEN** an otherwise-KEEP issue has 300 days of inactivity and the only keep-open comment was written by an author whose association is NONE
- **THEN** that comment does not create an exemption

### Requirement: Verdict precedence with the new verdicts

When more than one verdict condition holds for an issue, the skill SHALL select exactly one primary verdict using the precedence MERGE, then CLOSE, then OBSOLETE, then UPDATE-SCOPE, then STALE-CANDIDATE, then KEEP. RELABEL SHALL remain an orthogonal annotation that can accompany any primary verdict.

#### Scenario: All symptoms done and premise also gone

- **WHEN** every symptom of an issue is DONE and the referenced files were also removed
- **THEN** the primary verdict is CLOSE and not OBSOLETE

#### Scenario: Duplicate of another issue and stale

- **WHEN** an issue duplicates another open issue and also qualifies as STALE-CANDIDATE
- **THEN** the primary verdict is MERGE

### Requirement: Inactivity does not lower the priority of unresolved severe issues

The priority ranking SHALL NOT lower the priority of an unresolved issue solely because of its inactivity age. The ranking SHALL treat inactivity as a separate review-urgency annotation. An unresolved issue with high severity and a high inactivity age SHALL NOT be ranked below an otherwise identical issue with a low inactivity age.

#### Scenario: Old severe bug keeps its priority

- **WHEN** two otherwise identical unresolved bugs have inactivity ages of 10 days and 250 days
- **THEN** the 250 day bug is ranked no lower than the 10 day bug and carries a review-urgency annotation

### Requirement: Write actions for the new verdicts remain opt-in

Posting a stale notice, closing an issue as obsolete, and closing a stale issue after its grace period SHALL execute only when the user passes the apply option and confirms each item individually. A scheduled or webhook-triggered run SHALL stop at the report even when the apply option is present.

#### Scenario: Scheduled run

- **WHEN** the skill runs from a schedule and finds a STALE-CANDIDATE issue
- **THEN** the issue appears in the report and no comment is posted

#### Scenario: Apply run with confirmation

- **WHEN** the user passes the apply option and confirms a stale notice for one issue
- **THEN** exactly that issue receives the stale notice comment carrying the triage marker

### Requirement: Unavailable staleness data fails safe

When the inactivity measurement or the code drift signal cannot be obtained for an issue, the skill SHALL NOT assign STALE-CANDIDATE or OBSOLETE to that issue, SHALL NOT treat the missing data as human activity or as the absence of drift, and SHALL list the issue in the report as staleness review unavailable together with the reason. The remaining verdicts for that issue SHALL still be computed. A second failure of the comment lookup within the same run SHALL stop the staleness review, and every issue not yet reviewed SHALL then be listed as staleness review unavailable. A missing JSON processing tool SHALL list every issue that needs the lookup as staleness review unavailable. Only run-wide preconditions (the baseline check and the issue listing) stop the whole run.

#### Scenario: Comment lookup fails for one issue

- **WHEN** the call that fetches the comments of one issue fails while the other issues succeed
- **THEN** that issue is listed as staleness review unavailable, receives no STALE-CANDIDATE or OBSOLETE verdict, and the other issues are triaged normally

#### Scenario: Drift lookup fails for one issue

- **WHEN** the code drift script fails with an unexpected error, or cannot find the baseline ref, for one issue while the other issues succeed
- **THEN** that issue is listed as staleness review unavailable, is not treated as having no drift, receives no STALE-CANDIDATE or OBSOLETE verdict, and the other issues are triaged normally

#### Scenario: Repeated comment lookup failure

- **WHEN** the comment lookup fails for a second time within the same run
- **THEN** the staleness review stops and every issue not yet reviewed is listed as staleness review unavailable

### Requirement: Staleness verdicts apply to GitHub issues only

The OBSOLETE and STALE-CANDIDATE verdicts SHALL be assigned only to GitHub issues. Jira bugs SHALL continue to receive only the verdicts that existed before this capability, because the Jira updated field, comment authors, and automation accounts have different semantics and need a separate design.

#### Scenario: Old Jira bug

- **WHEN** a Jira bug has had no update for 400 days
- **THEN** it is not assigned OBSOLETE or STALE-CANDIDATE and is triaged with the existing verdict table rows only

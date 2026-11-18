## MODIFIED Requirements

### Requirement: Demoted findings have a defined destination

US-003 / AC-003-1. Every non-blocking finding SHALL be routed through a four-way filter so that unverified noise never enters the issue tracker while verified defects retain an explicit owner:

1. Findings in `## Deferred for lack of evidence` (missing/malformed evidence, precision-only, un-reproduced, zero-hit grep, unreachable under the current architecture, or unconfirmed `Invalid` broken-evidence items) and Actionable NIT findings SHALL rely solely on the pull request review comment and SHALL NOT create a GitHub issue (unless a broken-evidence item is explicitly confirmed by the human in Step 8).
2. Verified reproducible Round 2 Important findings confined to a single file within 15 lines and without public-interface or Review Contract changes SHOULD be fixed in place before Step 8 (verified by local CI and gated by remote CI before merge without starting Round 3) and SHALL NOT create a GitHub issue.
3. Verified Deferred Important findings belonging to an active Spectra change that remains unarchived after the pull request merges SHALL be recorded in that change's `tasks.md` gated by `spectra archive`, and SHALL NOT create a separate GitHub issue (if the change is archived in the current pull request's Step 11a, unfinished items SHALL be fixed in place or routed to item 4).
4. Remaining standalone Verified Deferred Important findings (or broken-evidence items explicitly confirmed by the human in Step 8) SHALL create at most one GitHub issue per pull request **only after** the pull request is confirmed `MERGED` in Step 10, using a concrete module-and-symptom title (never the generic `"Deferred from review: PR #<N>"` title) and domain labels, without bundling unrelated minor items.

#### Scenario: many-important-one-issue -- 多筆降級 Important 只開一張票

**GIVEN** the pull request has been confirmed `MERGED` and three standalone Verified Deferred Important findings remain after excluding unverified items, single-file ≤15-line fixes, and active Spectra change tasks
**WHEN** post-merge deferral routing runs
**THEN** at most one GitHub issue MUST be created for the pull request
  AND the issue title MUST state the concrete module and symptom rather than `"Deferred from review: PR #<N>"`
  AND the issue body MUST list the verified findings with source PR provenance

#### Scenario: nit-only-no-issue -- 只有 NIT 降級則不開票

**GIVEN** the review loop has ended with demoted Actionable NIT findings and no Verified Deferred Important findings
**WHEN** deferral routing runs
**THEN** no issue MUST be created

#### Scenario: no-demotions-no-issue -- 無降級則不開票

**GIVEN** the review loop has ended with no Verified Deferred Important findings
**WHEN** deferral routing runs
**THEN** no issue MUST be created

#### Scenario: unverified-or-unreachable-no-issue -- 未重現、缺證據或現行架構不可達者禁止建票

**GIVEN** an Important finding is demoted into `## Deferred for lack of evidence` because it lacks valid evidence, did not reproduce, had zero grep hits, or is unreachable under the current architecture
**WHEN** deferral routing runs
**THEN** the finding MUST remain recorded in the pull request review comment
  AND no GitHub issue MUST be created for that finding

#### Scenario: small-round2-fix-in-place -- Round 2 單檔 15 行內小修當場結清不建票

**GIVEN** Round 2 identifies a verified reproducible Important defect fixable within 15 lines in a single file without changing public interfaces or the Review Contract
**WHEN** the lead resolves Round 2 before Step 8
**THEN** the runbook MUST direct fixing the defect in place with CI verification without starting Round 3
  AND no GitHub issue MUST be created for that defect

#### Scenario: active-spectra-change-routes-to-tasks -- 隸屬進行中 Spectra change 者寫入 tasks.md 不建票

**GIVEN** a Verified Deferred Important finding belongs to an active Spectra change that remains unarchived after the current pull request merges
**WHEN** deferral routing runs
**THEN** the item MUST be recorded in that change's `tasks.md`
  AND no separate GitHub issue MUST be created

#### Scenario: pre-merge-issue-creation-forbidden -- PR 合併成功前禁止建立延後 issue

**GIVEN** a pull request is still `OPEN`, paused at the circuit breaker, or `CLOSED` without merging
**WHEN** non-blocking or deferred findings exist
**THEN** `gh issue create` MUST NOT run before the pull request is confirmed `MERGED`

#### Scenario: opaque-deferred-title-forbidden -- 禁止無語意的制式標題回退

**GIVEN** `SKILL.md` is checked by `check_convergence_contract`
**WHEN** the forbidden generic title `'Deferred from review: PR #'` or pre-merge circuit-breaker issue creation wording appears, or any four-way filter anchor is removed
**THEN** `check_convergence_contract` MUST return a non-empty failure list naming the violation

"""Convergence contract checker for pr-cycle-deep SKILL.md.

This file **is** the mechanical checker (testplan「可測性前提」). pytest can only assert against
the SKILL.md document itself; the aggregator / lead behaviour every AC ultimately cares about is
LLM-runtime and is **not** verifiable here (see testplan Missing Coverage). A green suite therefore
proves **document conformance only** — that the runbook still contains these rules — never that an
agent obeys them on a future PR.

`check_convergence_contract(text)` is a **pure function** on purpose: a test file that only asserts
against the real file cannot exercise its own failure paths, so the negative cases
(PRC-DT-002 / PRC-EG-001 / PRC-EG-006) would be impossible and the checker would rot into a
"always green, no information" decoration. All anchor matching reads raw UTF-8 via
`Path.read_text(encoding="utf-8")` (Python-layer read; not a rule-13/bash concern): the anchors
contain 全形／CJK characters (`每個 PR 至多一張`), and an ASCII substitution would silently
fail to match.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# scripts/tests/ -> scripts/ -> pr-cycle-deep/
SKILL_MD = Path(__file__).resolve().parents[2] / "SKILL.md"

# The change's self-imposed line budget: the file must not grow past its pre-change length.
#
# Raised 1220 -> 1239 (+19) for Step 1.6 "Fact-assertion sweep". Recorded here rather than
# absorbed silently, because the point of this ratchet is that growth must be argued for:
#
#   yibi-mvp PR #933 ran this skill with 3 voices over 2 rounds and produced 25 findings, yet its
#   two highest-consequence defects were found by NO voice -- every voice reads only diff.patch,
#   so a false statement living outside the diff is structurally invisible to all of them. Adding
#   reviewers cannot close that gap; only widening the surface can. The 19 lines buy the trigger
#   for that widening.
#
# Raised 1239 -> 1256 (+17) for two Evidence-gate integrity fixes found by running this skill
# against PR #360 after it merged. Both are cases where the skill's own machinery defeated itself:
#
#   (1) +6 lines, Stage 3 render: the extract schema dropped `Contract mapping` / `Evidence`, so
#       Step 5's Evidence gate ("missing or not the required form -> demote immediately") fired on
#       EVERY external-voice finding regardless of what the reviewer actually supplied. Only the
#       Claude voice, which skips extract, could clear it. Measured on PR #360: all three Codex
#       findings arrived with no evidence field and would have been deferred; the lead reproduced
#       all three by hand and one was then upgraded to Critical in R2. A cross-family review whose
#       gate structurally discards two of the three families is not a cross-family review.
#
#   (2) +11 lines, Step 3.2: the step dispatches four subagents at once, one of which
#       (`pr-test-analyzer`) mutates files in the shared worktree while the other three read them
#       -- directly contradicting rule 17's "finish the review round, collect every report, *then*
#       mutate". The note tells pr-test-analyzer to sequence or copy, and to report
#       `git status --porcelain`. A skill cannot instruct a violation of a rule it also cites.
#
# Anyone raising this again: say what the added lines buy, in the same commit.
#
# Raised 1239 -> 1246 (+7) for the agy-review/agy-consult split. Stage 1 and R2 both kept
# --dangerously-skip-permissions after an empirical probe (agy 1.1.8; re-verified on agy
# 1.1.12, 2026-08-13, real-worktree stage1 form) confirmed --sandbox auto-denies agy's
# `command` permission-class tools in headless mode -- read_file/ListDirectory within
# --add-dir ARE allowed, but the exploratory shell `command` a real review issues is denied,
# yielding empty output. The 7 lines record that finding as a `subagent` permission-class
# note (own absolute-path allow-list entry, not a bare Bash(agy:*)) so the next reader
# doesn't re-litigate a settled, re-verified finding.
#
# Merged with an independent 1239 -> 1256 (+17) raise from origin/main (two Evidence-gate
# integrity fixes, landed in parallel via PR #368) -> combined budget 1263.
#
# Raised 1263 -> 1294 (+31) for Step 3.0, the snapshot preflight (issue #372). What the lines buy:
#   * A blocking gate before any voice is dispatched. Voices read the WORKING TREE, which is not
#     an immutable snapshot -- a concurrent session in the same worktree, or an in-progress merge,
#     lets a voice read an intermediate state and report a finding that does not hold for what
#     landed. First-hand evidence (yibi-mvp PR #1169, 2026-08-04): a code-reviewer subagent read
#     .github/workflows/ci.yml while it was `UU` and reported a missing `needs` entry as Important;
#     the landed `needs` contained it. That PR's aggregated review recorded the rejection.
#   * 8 of the 31 lines are the exit-code table. Rule 11 ("Tool Exit Codes Must Be Listed in
#     SKILL.md Branch Design") requires it: a PASS/FAIL-only runbook collapses exit 2 (unmerged,
#     never overridable) and exit 3 (merge in progress, overridable only by pinning a SHA) into
#     one outcome, and the agent then routes the recoverable case as a hard failure or skips it.
#   * The remainder is the `verify` call and one blockquote stating the two boundaries readers
#     otherwise re-litigate: why this is not a global PreToolUse hook (it would block the
#     legitimate "review my conflict resolution" case and cannot gate human review), and that it
#     does not replace the conflict-detector step (GitHub-side mergeability is a different
#     question from local working-tree state).
# The first draft was +46; the allow-list entry was folded into 3.1's existing block and the
# rationale prose cut to one blockquote, since the script header carries the long form.
#
# Raised 1294 -> 1307 (+14 lines added; old budget had 1 line of slack over 1293 actual)
# for two lessons from yibi-firmware PR #44 (issue #437):
#
#   (1) +6 lines, Contract mapping validation: a blockquote in the Contract mapping gate
#       requiring the lead to verify each mapping reference exists (AC-ID in the Contract,
#       repo baseline path in the repo) before promoting to the blocking set. Without this,
#       a voice can write a fabricated AC-ID or cite a nonexistent rule file and the finding
#       enters the blocking set unchecked — caught only if another voice happens to DISAGREE.
#
#   (2) +8 lines, Evidence hallucination tell: a new tier row in the Evidence gate table plus a
#       blockquote describing the hallucination tell pattern — evidence that describes what the
#       result *should* look like rather than what it *does*. The structure check passes
#       fabricated evidence in valid form; the Verify tier catches it for Critical (lead must
#       reproduce), but Important findings slip through on Spot-check. The tell gives the lead
#       a screening heuristic before spot-checking.
#
#   Both are Tier 2 (incident-cited): yibi-firmware PR #44 mob review, where a Claude NIT had
#   no contract mapping and agy fabricated a Critical + evidence about a nonexistent heading
#   rename. The first was caught by Codex DISAGREE in R2; the second was refuted by grep.
#
# Raised 1307 -> 1327 (+20 lines; old budget had 0 slack) for Step 1.7, the red-first gate.
# Evidence (yibi-mvp transcripts 2026-08-25 ~ 09-25, 789 sessions): three TDD skills were
# invoked 0 times and 12 of 158 code-editing sessions were test-first, although spectra-apply
# already instructed "write a failing test FIRST" — prose had no effect, so the step runs a
# repo-provided checker that reverts production code to the merge-base and requires the PR's
# tests to fail (feat/fix) or keep passing (refactor/perf). The first draft was +51; the
# rationale, exit-code table and don'ts were folded into two paragraphs, since the checker's
# docstring carries the long form.
#
# Raised 1327 -> 1336 (+9 lines) for two lessons taken from mattpocock/skills' tdd skill
# (skills/engineering/tdd/, read 2026-09-25):
#   (1) +6, Step 1.7 carries two exit-0 markers forward: [WEAK-RED] (red from an import/compile
#       error only — a tautological `assert total(xs) == sum(...)` goes red the same way, so the
#       listed tests are pasted into prompt-r1.md for every voice) and [EXEMPT] (config / wiring
#       with no independent truth to assert, mattpocock issue #746 — the lead may not accept it,
#       it becomes a Step 8 hotspot). Plus the --pr-body-file argument that makes [EXEMPT]
#       reachable.
#   (2) +3, the R1 prompt gains a "Tautological or implementation-coupled test" evidence form and
#       one focus bullet; the gate otherwise demotes such findings as having no valid form.
#
# Set to 1340 (+4 over the pre-review 1336; an interim 1349 was lowered again) after PR #469's
# own mob review (Claude + Codex, 2026-09-26).
# Round 1 found the Step 1.7 prose could skip or misroute the gate silently (title pasted into
# `--title "<PR title>"` so `${N}` from real PR #387 expanded to nothing; stale origin base; restore
# check reachable only after exit 0; a traceback's exit 1 read as a verdict). Round 2 found the
# first fix told the agent to run separate Bash calls while passing PR_TITLE / WT_ROOT between
# them, which the Bash tool does not keep. All of that logic moved into scripts/red-first.sh (one
# call, tested by test_red_first_sh.py), so Step 1.7 shrank; the +4 are the template slots that
# carry [WEAK-RED] into the Step 3.1 prompt and a Red-first block into Step 8.
# The anchors below guard command text and single-occurrence sentences, not repeated tokens:
# Round 2's mutation run showed a "[WEAK-RED]" anchor (3 occurrences) and prose-only anchors let
# single-point regressions through.
#
# Raised 1340 -> 1355 (+15) for enforce-testplan-trace (testplan TCs made verifiable):
#   (1) +6 lines, Step 8: a Manual Verification section in human-summary.md plus the instruction
#       to confirm each unchecked MV item with the human, post the result as a PR comment, and
#       tick it. Measured before this change: [manual]/[doc] TCs across 13 testplans were almost
#       never executed -- they were written into an 8-column table nobody ran. This is the one
#       place in the lifecycle where a human is already present to run them.
#   (2) +9 lines, Step 11a: run check_testplan_trace.py --strict before archiving, with its exit
#       codes. Without it the trace gate has no enforcement point at the moment a change claims to
#       be finished -- the only moment its FAIL severity is meant to bite.
#
# Raised 1355 -> 1363 (+8) for the Spec-drift preflight (issue #510, PR #515). The paragraph adds 25
# lines; 1338 + 25 = 1363, so 8 of them exceed the old slack. The first 14-line version picked
# commits by author date after "the last commit touching spec/change files" over a local origin
# ref, and R1 showed it silently reports "no drift" when a later commit touches a spec file (a
# tasks.md tick, a typo fix, a rename), when HEAD is not the PR head, when origin is a stale fork,
# and after a rebase keeps author dates. The lines buy: the HEAD == headRefOid check, the
# fetched-base range in one call, "inspect every commit" with the reason no spec edit is a
# baseline, `--remerge-diff` for merge commits (a plain --stat of a "merge main" commit lists every
# base change as if the branch made it) with `%p` in the listing to tell merges apart, the
# octopus fallback (remerge-diff only warns on 3+ parents and prints an empty stat -- PR #515 R2,
# reproduced on git 2.56.0), the `[spec]` marker, and "failure or empty range is [FAIL], not
# none". Zero slack is deliberate.
LINE_BUDGET = 1363

# Spec-drift preflight (issue #510). These anchors name each rule clause so a failure says WHICH
# clause went missing, and check_preflight_position requires each to sit inside Step 1 before
# drafting. They are diagnostics, not the guard: PR #515's review found new unpinned clauses three
# passes in a row (10/12 mutants surviving, then 13 semantic mutants such as newest -> oldest and
# upstream/origin swapped, then 14 mutants that kept every anchor and appended a contradiction).
# Same shape three times means substring anchors cannot close this class, so the guard is the
# golden snapshot below (PREFLIGHT_SHA256): any edit to the paragraph turns the suite red.
PREFLIGHT_ANCHORS: list[str] = [
    "Spec-drift preflight",  # the step exists
    "new or existing PR",  # scope: both paths
    "--json baseRefName -q .baseRefName`",  # base branch comes from THIS PR, not upstream tracking
    "existing PR, `git rev-parse HEAD` must equal",  # existing PR: HEAD must be the PR head ...
    "--json headRefOid -q .headRefOid`, else `[FAIL]`",  # ... or stop
    "as `setup-review-dir.sh` does",  # base remote resolution (PR #22, issue #196)
    "(`upstream` if present, else",  # ... upstream wins over a possibly stale fork origin
    "git fetch <base-remote> -- {{base_branch}} &&",  # fetch and list in one call (FETCH_HEAD)
    "git log --topo-order --format='%h %p %s' FETCH_HEAD..HEAD",  # %p: parents identify merges
    "Inspect every commit in that range with `git show --stat <sha>`",  # no baseline cut-off
    "`git show --remerge-diff --stat <sha>`",  # a merge shows only its own resolution
    "an octopus merge (3+ parents) gets only a warning",  # remerge-diff skips it (PR #515 R2)
    "use plain `--stat` and tag it `[octopus]`",  # ... so it is inspected, never silently empty
    "not only those after a spec edit",  # ... explicitly
    "`proposal.md`, `design.md` or `specs/`",  # what counts as a spec edit
    "as `[spec]` in the list — a marker only",  # AC-1(c): annotate, never cut
    "changes Goal-level intent",  # the judgement being asked for
    "final section) MUST carry",  # the drift list is mandatory
    "new-PR draft, or the existing PR's final section",  # where the list goes
    "Spec vs implementation drift",  # the list's name
    "(commit, what changed, affected Goal/AC)",  # the list's fields
    "at the **first** confirmation",  # the timing the Goal is about
    "if none, say so",  # "no drift" is stated, not implied
    "or an empty range is `[FAIL]`",  # empty range is a stop ...
    "never report it as no drift",  # ... never "none"
]

# Load-bearing strings that MUST be present. Each proves one piece of this change landed; the
# PRC-EG-006 mutation test asserts every one of them is genuinely checked (removing it turns the
# checker red), so a stale anchor cannot silently make the guard vacuous.
REQUIRED_ANCHORS: list[str] = [
    "Evidence:",  # finding format carries an Evidence field
    "Evidence forms",  # the closed evidence-classification table
    "No acceptable evidence form",  # precision findings are always deferred
    "Evidence gate",  # the aggregation-time gate section
    "baseline..HEAD",  # Round 2 reviews only the fix delta
    "Round 3",  # ... which per the round table does not exist
    "bounded to two rounds",  # the loop is capped, not shrinkage-terminated
    "preserved verbatim",  # demoted findings keep their original text
    "never record it as",  # invalid evidence != absent defect
    "fixes it once",  # invalid evidence is repaired at most once
    "每個 PR 至多一張",  # at most one batch issue per PR
    "deferred-from-review",  # the batch issue's label
    "## Review Contract",  # PR body contract wrapper
    "### Goal",  # contract: required outcome
    "### Non-goals",  # contract: explicit scope exclusions
    "### Accepted Residual Risks",  # contract: human-owned risk acceptance
    "Failure mode / impact:",  # residual-risk field (colon-anchored to the Step 1 template line)
    "Accepted boundary:",  # residual-risk field: the accepted boundary
    "Mitigation:",  # residual-risk field (colon avoids matching the bare word)
    "Detection / recovery:",  # residual-risk field: detection & recovery procedure
    "### Acceptance Criteria",  # contract: PR-specific merge gates
    "### Follow-ups",  # contract: explicit non-blocking deferrals
    "frozen Review Contract",  # confirmed snapshot used by one review pass
    "Contract mapping:",  # finding -> AC / repo baseline / unaccepted risk
    "Contract mapping validation",  # lead MUST verify mapping references exist
    "lead MUST verify the reference exists",  # semantic: mandatory
    "Evidence hallucination tell",  # screen for fabricated evidence in valid form
    "describes what",  # semantic: hallucination-tell demotion
    "Accepted by:",  # a review voice cannot accept risk for a human
    "blocking set is the sole LGTM gate",  # raw voice verdict has no veto
    "R2 skipped: no contract-blocking candidate or dispute",  # clean R1 exit
    "material amendment",  # semantic contract change restarts full-diff R1
    "editorial amendment",  # non-semantic correction keeps the current pass
    *PREFLIGHT_ANCHORS,  # issue #510 Spec-drift preflight; also position-checked, see below
    "### Step 1.7 — Red-first gate",  # the gate step exists
    # the gate runs as ONE call to the tested wrapper (title/base/restore logic lives there)
    'scripts/red-first.sh --pr {{pr_number}} --repo-root "$PWD" --out-dir "$CLAUDE_JOB_DIR"',
    "never as hand-split steps",  # Bash calls do not share shell variables
    "(`RED_FIRST_RESULT=fail`) → **stop before Step 2**",  # a verdict FAIL blocks review
    "do not restore by hand (rule 15)",  # exit 3 / killed call hands the tree to a human
    "Step 3.1 pastes them into `prompt-r1.md`",  # [WEAK-RED] is carried to every voice
    "Weak-red tests (inspect for tautology)",  # ... via a slot in the Step 3.1 template
    "the lead may not accept it",  # an exemption needs a human
    "## Red-first (always shown",  # ... via a slot in the Step 8 template
    "Tautological or implementation-coupled test",  # the evidence form for such findings
    "starting with any `[WEAK-RED]` tests from Step 1.7",  # pr-test-analyzer focus (AC-3)
    "tests whose expected value is computed the way the",  # R1 prompt focus bullet (AC-3)
]

# Strings that MUST be absent. The NIT-must-be-cleaned convention (any spelling) and the old
# "3 rounds / until all voices LGTM" termination wording were removed by this change; if any
# reappears the checker must go red.
FORBIDDEN_STRINGS: list[str] = [
    "LGTM-with-trickle-NITs",
    "cleans up every",  # "cleans up every (undisputed) actionable NIT"
    "until all voices LGTM",
    "3 consecutive rounds",
    "連續 3 輪",
    "每個 actionable NIT 都要在 merge 前清掉",  # PRC-DT-003 / PRC-EG-002 CJK forbidden convention
    "全員 LGTM",
    "all voices LGTM",
    "All voices LGTM",
    "Every active voice's latest round outputs",
    "Want to skip R2 and run only R1 | Not allowed",
    '--title "<PR title>"',  # PR #469 R1: title pasted into shell source
    "Run these as separate calls",  # PR #469 R2: variables do not survive between Bash calls
]


def _count_lines(text: str) -> int:
    """Logical line count. A missing final newline is NOT an off-by-one (PRC-VL-004); CRLF counts
    the same as LF because only `\\n` is counted (PRC-VL-005)."""
    if text == "":
        return 0
    n = text.count("\n")
    if not text.endswith("\n"):
        n += 1
    return n


def check_convergence_contract(text: str) -> list[str]:
    """Return a list of failure messages; an empty list means every check passed.

    Pure function — no file I/O — so the negative paths are testable on synthetic fixtures.
    """
    failures: list[str] = []

    n = _count_lines(text)
    if n > LINE_BUDGET:
        failures.append(f"line budget exceeded: {n} lines exceeds {LINE_BUDGET} budget")

    for anchor in REQUIRED_ANCHORS:
        if anchor not in text:
            failures.append(f"required anchor absent: {anchor!r}")

    for forbidden in FORBIDDEN_STRINGS:
        if forbidden in text:
            failures.append(f"forbidden string present: {forbidden!r}")

    return failures


# Position markers for the Spec-drift preflight (issue #510). Substring anchors cannot see order,
# and PR #515 R1 showed the paragraph could move after drafting -- or out of Step 1 -- with the
# suite green; its second pass showed checking only the heading lets the body move instead. So the
# heading AND every PREFLIGHT_ANCHORS entry must occur between the contract template and drafting.
PREFLIGHT_MARKER = "**Spec-drift preflight"
CONTRACT_TEMPLATE_END = (
    "- <explicitly deferred hardening; non-blocking unless promoted by human amendment>"
)
DRAFTING_MARKER = "For a new PR, the lead drafts"


def check_preflight_position(text: str) -> list[str]:
    """Return failures unless the preflight sits between the contract template and drafting.

    Pure function so the negative paths run on synthetic text. A missing marker is a failure, not a
    pass: otherwise deleting a marker would turn this check vacuous.
    """
    positions = {
        m: text.find(m) for m in (CONTRACT_TEMPLATE_END, PREFLIGHT_MARKER, DRAFTING_MARKER)
    }
    missing = [m for m, i in positions.items() if i < 0]
    if missing:
        return [f"position marker absent: {m!r}" for m in missing]
    if (
        not positions[CONTRACT_TEMPLATE_END]
        < positions[PREFLIGHT_MARKER]
        < positions[DRAFTING_MARKER]
    ):
        return ["Spec-drift preflight is not between the Step 1 contract template and drafting"]
    lo, hi = positions[CONTRACT_TEMPLATE_END], positions[DRAFTING_MARKER]
    return [
        f"preflight anchor not inside Step 1 before drafting: {a!r}"
        for a in PREFLIGHT_ANCHORS
        if text.find(a, lo, hi) < 0
    ]


# Golden snapshot of the preflight paragraph: everything from the heading up to the drafting
# paragraph, whitespace-trimmed. A hash rather than a literal keeps the test file inside ruff's
# 100-column limit; on mismatch the failure prints the current text so the diff is readable.
# Changing the paragraph is legitimate -- but it must be a deliberate edit of this constant, made
# in the same commit, so a reviewer sees the runbook rule change as a test change too.
PREFLIGHT_SHA256 = "e92d04a6f41f8c6e3192945666b0d7759c6d95497141c26b67af925d16457ac1"


def preflight_text(text: str) -> str | None:
    """Return the preflight paragraph (heading through the line before drafting), or None."""
    start, end = text.find(PREFLIGHT_MARKER), text.find(DRAFTING_MARKER)
    if start < 0 or end < 0 or end <= start:
        return None
    return text[start:end].strip()


def check_preflight_snapshot(text: str) -> list[str]:
    """Return a failure unless the preflight paragraph hashes to PREFLIGHT_SHA256."""
    body = preflight_text(text)
    if body is None:
        return ["preflight snapshot: paragraph not found between its heading and drafting"]
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if digest != PREFLIGHT_SHA256:
        return [f"preflight snapshot mismatch: sha256 {digest} != PREFLIGHT_SHA256\n{body}"]
    return []


def read_skill_md(path: Path = SKILL_MD) -> str:
    """Read the real SKILL.md, failing loud on a missing path (PRC-EG-005).

    A missing file is a broken checkout, not "nothing to check": raise SystemExit (non-zero) so it
    can never be mistaken for a pytest skip or a vacuous pass.
    """
    if not path.is_file():
        raise SystemExit(f"[FAIL] SKILL.md not found: {path}")
    return path.read_text(encoding="utf-8")


def _fixture(n_lines: int, *, trailing_newline: bool = True, eol: str = "\n") -> str:
    """Build a synthetic document with every required anchor, no forbidden string, and exactly
    `n_lines` logical lines."""
    lines = list(REQUIRED_ANCHORS)
    i = 0
    while len(lines) < n_lines:
        lines.append(f"filler line {i}")
        i += 1
    lines = lines[:n_lines]
    body = eol.join(lines)
    return body + eol if trailing_newline else body


# --------------------------------------------------------------------------- line budget (VL)


def test_prc_vl_001_budget_upper_bound_accepted():
    """PRC-VL-001: exactly LINE_BUDGET lines, anchors complete → []."""
    text = _fixture(LINE_BUDGET)
    assert _count_lines(text) == LINE_BUDGET
    assert check_convergence_contract(text) == []


def test_prc_vl_002_budget_plus_one_rejected_with_both_numbers():
    """PRC-VL-002: budget+1 fails with a single message naming both the count and the budget.

    Derived from LINE_BUDGET rather than hardcoded: the first budget raise (1220 -> 1239) broke
    these three tests precisely because the numbers were literals, so the boundary assertions
    stopped describing the boundary they claim to guard.
    """
    over = LINE_BUDGET + 1
    text = _fixture(over)
    assert _count_lines(text) == over
    failures = check_convergence_contract(text)
    budget_msgs = [f for f in failures if str(over) in f and str(LINE_BUDGET) in f]
    assert len(budget_msgs) == 1, failures


def test_prc_vl_003_budget_minus_one_accepted():
    """PRC-VL-003: budget-1 lines → []."""
    under = LINE_BUDGET - 1
    text = _fixture(under)
    assert _count_lines(text) == under
    assert check_convergence_contract(text) == []


def test_prc_vl_004_no_trailing_newline_not_off_by_one():
    """PRC-VL-004: a budget-length doc without a final newline counts exactly, not +/-1."""
    text = _fixture(LINE_BUDGET, trailing_newline=False)
    assert not text.endswith("\n")
    assert _count_lines(text) == LINE_BUDGET
    assert check_convergence_contract(text) == []


def test_prc_vl_005_crlf_counts_same_as_lf():
    """PRC-VL-005: rebuilding the 1221 fixture with CRLF fails identically — CRLF does not change
    the count.

    T045 decision: KEPT. This repo does not pin LF via .gitattributes, so a Windows checkout could
    introduce CRLF; the test is cheap and guards the `\\n`-only counting.
    """
    over = LINE_BUDGET + 1
    text = _fixture(over, eol="\r\n")
    assert _count_lines(text) == over
    failures = check_convergence_contract(text)
    assert any(str(over) in f and str(LINE_BUDGET) in f for f in failures)


# --------------------------------------------------------------------------- anchors (DT)


def test_prc_dt_001_all_anchors_present_passes():
    """PRC-DT-001: anchors complete, no forbidden string, within budget → []."""
    assert check_convergence_contract(_fixture(900)) == []


def test_prc_dt_002_missing_anchor_fails_loud():
    """PRC-DT-002: removing a required anchor yields a failure naming it plus 'absent' — never []
    and never a skip."""
    text = _fixture(900).replace("baseline..HEAD", "")
    failures = check_convergence_contract(text)
    assert any("baseline..HEAD" in f and "absent" in f for f in failures), failures


def test_prc_dt_003_forbidden_convention_present_fails():
    """PRC-DT-003: the removed NIT-must-be-cleaned convention, if present, fails the checker."""
    text = _fixture(900) + "每個 actionable NIT 都要在 merge 前清掉\n"
    failures = check_convergence_contract(text)
    assert any("每個 actionable NIT 都要在 merge 前清掉" in f for f in failures), failures


def test_prc_dt_004_no_forbidden_convention_passes():
    """PRC-DT-004: a clean fixture with anchors complete and no forbidden string → []."""
    assert check_convergence_contract(_fixture(900)) == []


@pytest.mark.parametrize(
    "heading",
    [
        "## Review Contract",
        "### Goal",
        "### Non-goals",
        "### Accepted Residual Risks",
        "### Acceptance Criteria",
        "### Follow-ups",
    ],
)
def test_prc_dt_005_review_contract_headings_are_required(heading: str):
    """spec: pr-review-contract#missing-contract-section-blocks-reviewer-launch

    Removing any fixed Review Contract heading turns the pure checker red, so a partial PR-body
    template cannot silently launch the expensive reviewers.
    """
    text = _fixture(900).replace(heading, "")
    failures = check_convergence_contract(text)
    assert any(heading in f and "absent" in f for f in failures), failures


@pytest.mark.parametrize(
    "anchor",
    [
        "frozen Review Contract",
        "Contract mapping:",
        "Accepted by:",
        "blocking set is the sole LGTM gate",
        "R2 skipped: no contract-blocking candidate or dispute",
        "material amendment",
        "editorial amendment",
    ],
)
def test_prc_dt_006_contract_decision_anchors_are_required(anchor: str):
    """spec: pr-review-contract#conditional-r2-mutation-fails

    Contract amendment, mapping, human risk ownership, LGTM, and conditional-R2 rules are all
    load-bearing; removing one is a conformance failure rather than an optional documentation edit.
    """
    text = _fixture(900).replace(anchor, "")
    failures = check_convergence_contract(text)
    assert any(anchor in f and "absent" in f for f in failures), failures


@pytest.mark.parametrize(
    "wording",
    [
        "全員 LGTM（含 actionable NIT）",
        "all voices LGTM",
        "All voices LGTM",
        "Every active voice's latest round outputs `Final verdict: LGTM`",
        "Want to skip R2 and run only R1 | Not allowed",
    ],
)
def test_prc_dt_007_unanimous_voice_and_mandatory_r2_wording_is_forbidden(wording: str):
    """spec: pr-review-contract#unanimous-wording-mutation-fails

    Known semantic variants of the old unanimous-veto and always-R2 rules must not survive merely
    because the original checker searched one exact English phrase.
    """
    failures = check_convergence_contract(_fixture(900) + wording + "\n")
    assert any("forbidden string present" in f for f in failures), failures


def test_prc_dt_008_preflight_sits_between_template_and_drafting():
    """PRC-DT-008: the real SKILL.md has the Spec-drift preflight heading and every rule clause
    after the Step 1 contract template and before the drafting paragraph (issue #510, AC-1/AC-3),
    and the paragraph matches its golden snapshot byte for byte."""
    text = read_skill_md()
    assert check_preflight_position(text) == []
    assert check_preflight_snapshot(text) == []


# --------------------------------------------------------------------------- edge / guard (EG)


def test_prc_eg_001_empty_text_fails_loud_not_vacuous():
    """PRC-EG-001: empty text must NOT pass just because 0 <= 1220 — it must list every missing
    anchor."""
    failures = check_convergence_contract("")
    assert failures  # never []
    for anchor in REQUIRED_ANCHORS:
        assert any(anchor in f for f in failures), anchor


def test_prc_eg_002_cjk_forbidden_detected_ascii_not():
    """PRC-EG-002: a CJK forbidden string is detected by raw UTF-8 match; an ASCII transliteration
    is NOT falsely matched."""
    base = _fixture(900)
    detected = check_convergence_contract(base + "每個 actionable NIT 都要在 merge 前清掉\n")
    assert any("每個 actionable NIT" in f for f in detected)
    # ASCII transliteration of the same intent — must not trip any forbidden matcher.
    ascii_line = base + "meige actionable NIT dou yao zai merge qian qingdiao\n"
    assert check_convergence_contract(ascii_line) == []


def test_prc_eg_003_forbidden_inside_code_fence_still_detected():
    """PRC-EG-003: a forbidden string inside a code fence is still detected (deliberate, documented
    behaviour — the checker searches the whole document, it does not exempt fences)."""
    text = _fixture(900) + "```\nLGTM-with-trickle-NITs\n```\n"
    failures = check_convergence_contract(text)
    assert any("LGTM-with-trickle-NITs" in f for f in failures), failures


def test_prc_eg_004_duplicate_anchor_no_crash_no_double_count():
    """PRC-EG-004: repeating an anchor does not raise and does not fail (membership, not counting).

    T045 decision: KEPT (minimal). The checker uses `in`, so per the testplan this TC is
    low-value; it stays as a one-line regression guard documenting the `in`-based design.
    """
    text = _fixture(900) + "baseline..HEAD baseline..HEAD baseline..HEAD\n"
    assert check_convergence_contract(text) == []


def test_prc_eg_005_missing_path_fails_loud_not_skip():
    """PRC-EG-005: a non-existent SKILL.md path raises SystemExit (non-zero) naming the path — not a
    pytest skip, not a silent []."""
    missing = Path("/nonexistent/pr-cycle-deep/SKILL.md")
    with pytest.raises(SystemExit) as exc:
        read_skill_md(missing)
    assert str(missing) in str(exc.value)


def test_prc_eg_006_every_required_anchor_is_load_bearing():
    """PRC-EG-006: mutation test — for each required anchor, remove ONLY that anchor from the real
    file and assert the checker now names it. One mutation per iteration; the anchor is asserted to
    actually be present first, so a stale anchor fails loud instead of producing a vacuous pass."""
    text = read_skill_md()
    assert check_convergence_contract(text) == [], "real SKILL.md must pass before mutating"
    for anchor in REQUIRED_ANCHORS:
        assert anchor in text, f"stale anchor (absent from real file): {anchor!r}"
        mutant = text.replace(anchor, "")  # remove ALL occurrences = make this one anchor absent
        failures = check_convergence_contract(mutant)
        assert any(anchor in f for f in failures), (
            f"mutant survived: removing {anchor!r} stayed green"
        )


def test_prc_eg_007_line_budget_mutation_killed_both_directions():
    """PRC-EG-007: +1 line over a passing budget-length fixture fails; -1 line under a failing
    budget+1 fixture passes. Both mutants killed."""
    ok = _fixture(LINE_BUDGET)
    over = ok + "one more line\n"
    assert _count_lines(over) == LINE_BUDGET + 1
    assert check_convergence_contract(over), "adding a line over budget must fail"

    bad = _fixture(LINE_BUDGET + 1)
    lines = bad.split("\n")
    under = "\n".join(lines[:-2]) + "\n"  # drop one logical line
    assert _count_lines(under) == LINE_BUDGET
    assert check_convergence_contract(under) == [], "dropping back to budget must pass"


def _preflight_window(body: str) -> str:
    """Synthetic Step 1: template end, preflight heading + body, drafting marker."""
    return f"{CONTRACT_TEMPLATE_END}\n{PREFLIGHT_MARKER}**\n{body}\n{DRAFTING_MARKER}\n"


def test_prc_eg_008_preflight_moved_after_drafting_fails():
    """PRC-EG-008: negative control -- moving the whole paragraph after drafting turns it red."""
    text = f"{CONTRACT_TEMPLATE_END}\n{DRAFTING_MARKER}\n{PREFLIGHT_MARKER} ...\n"
    assert check_preflight_position(text) == [
        "Spec-drift preflight is not between the Step 1 contract template and drafting"
    ]


@pytest.mark.parametrize("marker", ["CONTRACT_TEMPLATE_END", "PREFLIGHT_MARKER", "DRAFTING_MARKER"])
def test_prc_eg_009_missing_position_marker_fails_loud(marker: str):
    """PRC-EG-009: each deleted marker is reported by name, never a vacuous pass."""
    value = globals()[marker]
    text = _preflight_window("\n".join(PREFLIGHT_ANCHORS)).replace(value, "")
    assert f"position marker absent: {value!r}" in check_preflight_position(text)


def test_prc_eg_010_preflight_body_moved_after_drafting_fails():
    """PRC-EG-010: negative control -- heading stays, rule body moves after drafting (PR #515 R1
    second pass: the heading-only check let this through at an unchanged line count)."""
    ok = _preflight_window("\n".join(PREFLIGHT_ANCHORS))
    assert check_preflight_position(ok) == []
    body_only_heading = _preflight_window("Spec-drift preflight") + "\n".join(PREFLIGHT_ANCHORS)
    # Every anchor except the heading's own text must be reported -- not just a sample of them, or a
    # checker that looked at only two anchors would pass (PR #515 R1 third pass).
    assert set(check_preflight_position(body_only_heading)) == {
        f"preflight anchor not inside Step 1 before drafting: {a!r}"
        for a in PREFLIGHT_ANCHORS
        if a != "Spec-drift preflight"
    }


def test_prc_eg_011_preflight_body_before_template_fails():
    """PRC-EG-011: negative control for the window's lower bound -- anchors placed before the Step 1
    contract template are reported (a checker with `lo = 0` would pass this)."""
    text = "\n".join(PREFLIGHT_ANCHORS) + "\n" + _preflight_window("Spec-drift preflight")
    assert set(check_preflight_position(text)) == {
        f"preflight anchor not inside Step 1 before drafting: {a!r}"
        for a in PREFLIGHT_ANCHORS
        if a != "Spec-drift preflight"
    }


def test_prc_eg_012_preflight_snapshot_rejects_appended_reversal():
    """PRC-EG-012: negative control for the snapshot -- appending a contradiction while keeping
    every anchor (PR #515 R1 third pass: "an empty range simply means no drift") turns it red."""
    text = read_skill_md()
    assert check_preflight_snapshot(text) == []
    old = "never report it as no drift."
    assert text.count(old) == 1
    mutant = text.replace(
        old, "never report it as no drift (an empty range simply means no drift)."
    )
    assert check_convergence_contract(mutant) == [], "anchors alone cannot see this mutant"
    assert check_preflight_position(mutant) == [], "position alone cannot see this mutant"
    assert check_preflight_snapshot(mutant)[0].startswith("preflight snapshot mismatch")


def test_prc_eg_013_preflight_snapshot_missing_paragraph_fails_loud():
    """PRC-EG-013: no paragraph between heading and drafting is reported, never a vacuous pass."""
    assert check_preflight_snapshot(f"{DRAFTING_MARKER}\n{PREFLIGHT_MARKER}\n") == [
        "preflight snapshot: paragraph not found between its heading and drafting"
    ]


# --------------------------------------------------------------------------- smoke (SMK)


def test_smk_001_suite_passes_against_real_skill_md():
    """SMK-001: the real SKILL.md satisfies the contract, including the preflight position."""
    text = read_skill_md()
    assert check_convergence_contract(text) == []
    assert check_preflight_position(text) == []
    assert check_preflight_snapshot(text) == []


def test_smk_002_real_line_count_reported_within_budget(capsys):
    """SMK-002: the real line count is printed (run with -s to see it) and is <= budget."""
    n = _count_lines(read_skill_md())
    with capsys.disabled():
        print(f"\n[SMK-002] SKILL.md line count = {n} (budget {LINE_BUDGET})")
    assert n <= LINE_BUDGET, f"{n} exceeds budget {LINE_BUDGET}"


if __name__ == "__main__":
    skill_text = read_skill_md()
    problems = (
        check_convergence_contract(skill_text)
        + check_preflight_position(skill_text)
        + check_preflight_snapshot(skill_text)
    )
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        raise SystemExit(1)
    print(
        f"[OK] convergence contract holds ({_count_lines(read_skill_md())} lines <= {LINE_BUDGET})"
    )

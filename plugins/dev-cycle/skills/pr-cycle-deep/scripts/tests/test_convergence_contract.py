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
    "Tautological or implementation-coupled test",  # the evidence form for such findings
    "starting with any `[WEAK-RED]` tests from Step 1.7",  # pr-test-analyzer focus (AC-3)
    "tests whose expected value is computed the way the",  # R1 prompt focus bullet (AC-3)
    "## Verified Deferred Important",  # verified reproducible deferrals separated from unverified
    "禁止建立 GitHub issue",  # unverified / unreachable / active-change items never open issues
    "15 行以內",  # single-file <=15-line Round 2 fixes handled in place without Round 3 or issue
    "寫入該 change 的 `tasks.md`",  # active Spectra change items route to tasks.md
    "確認 PR 已 `MERGED` 後",  # issue creation gated on post-merge confirmation
    "標題必須寫明具體模組與問題症狀",  # concrete title required instead of generic PR prefix
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
    "Deferred from review: PR #",  # opaque generic deferral issue title retired (any quote/flag)
    "circuit breaker（人類裁決）路徑下**同樣建立**",  # pre-merge issue creation retired
]


def check_convergence_contract(text: str) -> list[str]:
    """Return a list of failure messages; an empty list means every check passed.

    Pure function — no file I/O — so the negative paths are testable on synthetic fixtures.
    """
    failures: list[str] = []

    for anchor in REQUIRED_ANCHORS:
        if anchor not in text:
            failures.append(f"required anchor absent: {anchor!r}")

    for forbidden in FORBIDDEN_STRINGS:
        if forbidden in text:
            failures.append(f"forbidden string present: {forbidden!r}")

    failures.extend(check_deferral_sections(text))
    return failures


STEP5_START = "### Step 5 —"
STEP5_END = "### Step 5a —"
STEP5C_START = "### Step 5c —"
STEP5C_END = "### Step 6 —"
STEP10B_START = "#### Step 10b —"
STEP10B_END = "### Step 11 —"

VDI_HEADING = "## Verified Deferred Important (verified reproducible; routed after merge)"
OUTSIDE_CONTRACT_HEADING = "## Outside contract (not blocking; mapping reason stated per item)"
CR_SOURCE_CLAUSE = "- Code-review source: CR-<n>"

STEP5_CLAUSES: tuple[str, ...] = (
    "## Deferred for lack of evidence (not blocking; reason stated per item)",
    VDI_HEADING,
    "禁止建立 GitHub issue",
)

STEP5C_CLAUSES: tuple[str, ...] = (
    "禁止執行 `gh issue create`",
    "單一檔案",
    "15 行以內",
    "不改變公開介面或 Review Contract",
    "通過本地與遠端 CI",
    "寫入該 change 的 `tasks.md`",
    "禁止建立 GitHub issue",
)
STEP5C_FORBIDDEN: tuple[str, ...] = ("gh issue create ",)

STEP10B_CLAUSES: tuple[str, ...] = (
    "確認 PR 已 `MERGED` 後",
    "每個 PR 至多一張",
    "標題必須寫明具體模組與問題症狀",
    "既有領域標籤",
    "--limit 300 --json name",
    "WT_ROOT=$(git rev-parse --show-toplevel)",
    'REVIEW_DIR="$WT_ROOT/.pr-review"',
)


def _slice_section(
    text: str, start_marker: str, end_marker: str, label: str
) -> tuple[str | None, list[str]]:
    """Return (window, errors) for text between start_marker and end_marker."""
    lo = text.find(start_marker)
    hi = text.find(end_marker)
    errs: list[str] = []
    if lo < 0:
        errs.append(f"{label} section marker absent: {start_marker!r}")
    if hi < 0:
        errs.append(f"{label} section marker absent: {end_marker!r}")
    if errs:
        return None, errs
    if hi <= lo:
        return None, [f"{label} section markers out of order: {start_marker!r} .. {end_marker!r}"]
    return text[lo:hi], []


def check_deferral_sections(text: str) -> list[str]:
    """Verify deferral clauses live in their authoritative Step 5 / Step 5c / Step 10b sections."""
    failures: list[str] = []

    step5, errs = _slice_section(text, STEP5_START, STEP5_END, "Step 5")
    failures.extend(errs)
    if step5 is not None:
        for clause in STEP5_CLAUSES:
            if clause not in step5:
                failures.append(f"Step 5 clause absent: {clause!r}")
        vdi_idx = step5.find(VDI_HEADING)
        outside_idx = step5.find(OUTSIDE_CONTRACT_HEADING, max(vdi_idx, 0))
        if vdi_idx < 0 or outside_idx < 0 or outside_idx <= vdi_idx:
            failures.append(
                f"Step 5 Verified Deferred Important template bounds absent: {CR_SOURCE_CLAUSE!r}"
            )
        elif CR_SOURCE_CLAUSE not in step5[vdi_idx:outside_idx]:
            failures.append(
                f"Step 5 Verified Deferred Important clause absent: {CR_SOURCE_CLAUSE!r}"
            )

    step5c, errs = _slice_section(text, STEP5C_START, STEP5C_END, "Step 5c")
    failures.extend(errs)
    if step5c is not None:
        for clause in STEP5C_CLAUSES:
            if clause not in step5c:
                failures.append(f"Step 5c clause absent: {clause!r}")
        stripped_5c = step5c.replace("`gh issue create`", "")
        if "gh issue create" in stripped_5c:
            failures.append("Step 5c forbidden call present: 'gh issue create'")

    step10b, errs = _slice_section(text, STEP10B_START, STEP10B_END, "Step 10b")
    failures.extend(errs)
    if step10b is not None:
        for clause in STEP10B_CLAUSES:
            if clause not in step10b:
                failures.append(f"Step 10b clause absent: {clause!r}")

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


def _fixture() -> str:
    """Build a synthetic document containing every required contract clause and section window."""
    anchors = "\n".join(REQUIRED_ANCHORS)
    sections = "\n".join(
        [
            f"{STEP5_START} Aggregator synthesis",
            *STEP5_CLAUSES,
            f"   {CR_SOURCE_CLAUSE}",
            OUTSIDE_CONTRACT_HEADING,
            f"{STEP5_END} Count gate",
            f"{STEP5C_START} Deferral filter",
            *STEP5C_CLAUSES,
            f"{STEP5C_END} Fix",
            f"{STEP10B_START} Post-merge issue",
            *STEP10B_CLAUSES,
            f"{STEP10B_END} Archive",
        ]
    )
    return f"{anchors}\n{sections}\n"


# --------------------------------------------------------------------------- anchors (DT)


def test_prc_dt_001_all_anchors_present_passes():
    """PRC-DT-001: anchors complete and no forbidden string → []."""
    assert check_convergence_contract(_fixture()) == []


def test_prc_dt_002_missing_anchor_fails_loud():
    """PRC-DT-002: removing a required anchor yields a failure naming it plus 'absent' — never []
    and never a skip."""
    text = _fixture().replace("baseline..HEAD", "")
    failures = check_convergence_contract(text)
    assert any("baseline..HEAD" in f and "absent" in f for f in failures), failures


def test_prc_dt_003_forbidden_convention_present_fails():
    """PRC-DT-003: the removed NIT-must-be-cleaned convention, if present, fails the checker."""
    text = _fixture() + "每個 actionable NIT 都要在 merge 前清掉\n"
    failures = check_convergence_contract(text)
    assert any("每個 actionable NIT 都要在 merge 前清掉" in f for f in failures), failures


def test_prc_dt_004_no_forbidden_convention_passes():
    """PRC-DT-004: a clean fixture with anchors complete and no forbidden string → []."""
    assert check_convergence_contract(_fixture()) == []


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
    text = _fixture().replace(heading, "")
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
    text = _fixture().replace(anchor, "")
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
    failures = check_convergence_contract(_fixture() + wording + "\n")
    assert any("forbidden string present" in f for f in failures), failures


def test_prc_dt_008_preflight_sits_between_template_and_drafting():
    """PRC-DT-008: the real SKILL.md has the Spec-drift preflight heading and every rule clause
    after the Step 1 contract template and before the drafting paragraph (issue #510, AC-1/AC-3),
    and the paragraph matches its golden snapshot byte for byte."""
    text = read_skill_md()
    assert check_preflight_position(text) == []
    assert check_preflight_snapshot(text) == []


_DEFERRAL_SECTION_CASES: list[tuple[str, str, str]] = [
    *((STEP5_START, STEP5_END, c) for c in STEP5_CLAUSES),
    (VDI_HEADING, OUTSIDE_CONTRACT_HEADING, CR_SOURCE_CLAUSE),
    *((STEP5C_START, STEP5C_END, c) for c in STEP5C_CLAUSES),
    *((STEP10B_START, STEP10B_END, c) for c in STEP10B_CLAUSES),
]


@pytest.mark.parametrize(("start_m", "end_m", "clause"), _DEFERRAL_SECTION_CASES)
def test_gdri_dt_001_deferral_filter_anchors_are_required(start_m: str, end_m: str, clause: str):
    """
    spec: pr-review-convergence#many-important-one-issue
    spec: pr-review-convergence#nit-only-no-issue
    spec: pr-review-convergence#no-demotions-no-issue
    spec: pr-review-convergence#unverified-or-unreachable-no-issue
    spec: pr-review-convergence#small-round2-fix-in-place
    spec: pr-review-convergence#active-spectra-change-routes-to-tasks
    spec: pr-review-convergence#pre-merge-issue-creation-forbidden
    spec: pr-review-convergence#opaque-deferred-title-forbidden
    tc: GDRI-DT-001
    """
    base = _fixture()
    lo = base.index(start_m)
    hi = base.index(end_m, lo)
    window = base[lo:hi]
    assert window.count(clause) == 1
    mutated = base[:lo] + window.replace(clause, "", 1) + base[hi:]
    failures = check_convergence_contract(mutated)
    assert any(clause in f and "absent" in f for f in failures), failures


@pytest.mark.parametrize(
    "forbidden",
    [
        '--title "Deferred from review: PR #{{pr_number}}"',
        "-t 'Deferred from review: PR #999'",
        '--title="Deferred from review: PR #42"',
        "circuit breaker（人類裁決）路徑下**同樣建立**",
    ],
)
def test_gdri_dt_002_opaque_deferred_title_and_premerge_creation_forbidden(forbidden: str):
    """
    spec: pr-review-convergence#pre-merge-issue-creation-forbidden
    spec: pr-review-convergence#opaque-deferred-title-forbidden
    tc: GDRI-DT-002
    """
    failures = check_convergence_contract(_fixture() + forbidden + "\n")
    assert any("forbidden string present" in f for f in failures), failures

    for bad_call in (
        'gh issue create --repo "{{owner/repo}}"',
        'gh issue create --label bug --title "Module X"',
    ):
        injected = _fixture().replace(STEP5C_START, f"{STEP5C_START}\n{bad_call}\n", 1)
        step5c_failures = check_convergence_contract(injected)
        assert any(
            "Step 5c forbidden call present: 'gh issue create'" in f for f in step5c_failures
        ), step5c_failures


# --------------------------------------------------------------------------- edge / guard (EG)


def test_prc_eg_001_empty_text_fails_loud_not_vacuous():
    """PRC-EG-001: empty input must list every missing required anchor, not pass vacuously."""
    failures = check_convergence_contract("")
    assert failures  # never []
    for anchor in REQUIRED_ANCHORS:
        assert any(anchor in f for f in failures), anchor


def test_prc_eg_002_cjk_forbidden_detected_ascii_not():
    """PRC-EG-002: a CJK forbidden string is detected by raw UTF-8 match; an ASCII transliteration
    is NOT falsely matched."""
    base = _fixture()
    detected = check_convergence_contract(base + "每個 actionable NIT 都要在 merge 前清掉\n")
    assert any("每個 actionable NIT" in f for f in detected)
    # ASCII transliteration of the same intent — must not trip any forbidden matcher.
    ascii_line = base + "meige actionable NIT dou yao zai merge qian qingdiao\n"
    assert check_convergence_contract(ascii_line) == []


def test_prc_eg_003_forbidden_inside_code_fence_still_detected():
    """PRC-EG-003: a forbidden string inside a code fence is still detected (deliberate, documented
    behaviour — the checker searches the whole document, it does not exempt fences)."""
    text = _fixture() + "```\nLGTM-with-trickle-NITs\n```\n"
    failures = check_convergence_contract(text)
    assert any("LGTM-with-trickle-NITs" in f for f in failures), failures


def test_prc_eg_004_duplicate_anchor_no_crash_no_double_count():
    """PRC-EG-004: repeating an anchor does not raise and does not fail (membership, not counting).

    T045 decision: KEPT (minimal). The checker uses `in`, so per the testplan this TC is
    low-value; it stays as a one-line regression guard documenting the `in`-based design.
    """
    text = _fixture() + "baseline..HEAD baseline..HEAD baseline..HEAD\n"
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


def test_gdri_eg_001_real_skill_deferral_anchors_kill_mutants():
    """
    spec: pr-review-convergence#many-important-one-issue
    spec: pr-review-convergence#unverified-or-unreachable-no-issue
    spec: pr-review-convergence#small-round2-fix-in-place
    spec: pr-review-convergence#active-spectra-change-routes-to-tasks
    spec: pr-review-convergence#pre-merge-issue-creation-forbidden
    spec: pr-review-convergence#opaque-deferred-title-forbidden
    tc: GDRI-EG-001
    """
    text = read_skill_md()
    assert check_convergence_contract(text) == []

    for start_m, end_m, clause in _DEFERRAL_SECTION_CASES:
        lo = text.index(start_m)
        hi = text.index(end_m, lo)
        window = text[lo:hi]
        assert window.count(clause) == 1, f"expected unique {clause!r} in {start_m}..{end_m}"
        mutant = text[:lo] + window.replace(clause, "", 1) + text[hi:]
        failures = check_convergence_contract(mutant)
        assert any(clause in f and "absent" in f for f in failures), (start_m, clause, failures)

    for top_clause in (*STEP5_CLAUSES, *STEP5C_CLAUSES):
        top_failures = check_convergence_contract(text.replace(top_clause, "", 1))
        assert any(top_clause in f and "absent" in f for f in top_failures), (
            top_clause,
            top_failures,
        )

    for bad_call in (
        'gh issue create --repo "{{owner/repo}}"',
        'gh issue create --label bug --title "Module X"',
    ):
        injected_5c = text.replace(STEP5C_START, f"{STEP5C_START}\n{bad_call}\n", 1)
        assert any(
            "Step 5c forbidden call present: 'gh issue create'" in f
            for f in check_convergence_contract(injected_5c)
        )

    single_quoted = text + "\ngh issue create -t 'Deferred from review: PR #999'\n"
    assert any("forbidden string present" in f for f in check_convergence_contract(single_quoted))


def test_gdri_vl_001_real_skill_rejects_opaque_title_and_passes():
    """
    spec: pr-review-convergence#many-important-one-issue
    spec: pr-review-convergence#opaque-deferred-title-forbidden
    tc: GDRI-VL-001
    """
    text = read_skill_md()
    assert check_convergence_contract(text) == []
    for bad_line in (
        'gh issue create --title "Deferred from review: PR #999"',
        "gh issue create -t 'Deferred from review: PR #999'",
    ):
        failures = check_convergence_contract(f"{text}\n{bad_line}\n")
        assert any("forbidden string present" in f for f in failures), failures


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
    print("[OK] convergence contract holds")

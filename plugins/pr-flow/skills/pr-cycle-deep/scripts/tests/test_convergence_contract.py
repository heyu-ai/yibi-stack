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
`Path.read_text(encoding="utf-8")` (host rule 13): the anchors contain 全形／CJK characters
(`每個 PR 至多一張`), and an ASCII substitution would silently fail to match.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# scripts/tests/ -> scripts/ -> pr-cycle-deep/
SKILL_MD = Path(__file__).resolve().parents[2] / "SKILL.md"

# The change's self-imposed line budget: the file must not grow past its pre-change length.
LINE_BUDGET = 1220

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
    """PRC-VL-001: exactly 1220 lines, anchors complete → []."""
    text = _fixture(1220)
    assert _count_lines(text) == 1220
    assert check_convergence_contract(text) == []


def test_prc_vl_002_budget_plus_one_rejected_with_both_numbers():
    """PRC-VL-002: 1221 lines fails with a single message naming both 1221 and 1220."""
    text = _fixture(1221)
    assert _count_lines(text) == 1221
    failures = check_convergence_contract(text)
    budget_msgs = [f for f in failures if "1221" in f and "1220" in f]
    assert len(budget_msgs) == 1, failures


def test_prc_vl_003_budget_minus_one_accepted():
    """PRC-VL-003: 1219 lines → []."""
    text = _fixture(1219)
    assert _count_lines(text) == 1219
    assert check_convergence_contract(text) == []


def test_prc_vl_004_no_trailing_newline_not_off_by_one():
    """PRC-VL-004: a 1220-line doc without a final newline counts as 1220, not 1219/1221."""
    text = _fixture(1220, trailing_newline=False)
    assert not text.endswith("\n")
    assert _count_lines(text) == 1220
    assert check_convergence_contract(text) == []


def test_prc_vl_005_crlf_counts_same_as_lf():
    """PRC-VL-005: rebuilding the 1221 fixture with CRLF fails identically — CRLF does not change
    the count.

    T045 decision: KEPT. This repo does not pin LF via .gitattributes, so a Windows checkout could
    introduce CRLF; the test is cheap and guards the `\\n`-only counting.
    """
    text = _fixture(1221, eol="\r\n")
    assert _count_lines(text) == 1221
    failures = check_convergence_contract(text)
    assert any("1221" in f and "1220" in f for f in failures)


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
    """PRC-EG-007: +1 line over a passing 1220 fixture fails; -1 line under a failing 1221 fixture
    passes. Both mutants killed."""
    ok = _fixture(1220)
    over = ok + "one more line\n"
    assert _count_lines(over) == 1221
    assert check_convergence_contract(over), "adding a line over budget must fail"

    bad = _fixture(1221)
    lines = bad.split("\n")
    under = "\n".join(lines[:-2]) + "\n"  # drop one logical line
    assert _count_lines(under) == 1220
    assert check_convergence_contract(under) == [], "dropping back to budget must pass"


# --------------------------------------------------------------------------- smoke (SMK)


def test_smk_001_suite_passes_against_real_skill_md():
    """SMK-001: the real SKILL.md satisfies the contract."""
    assert check_convergence_contract(read_skill_md()) == []


def test_smk_002_real_line_count_reported_within_budget(capsys):
    """SMK-002: the real line count is printed (run with -s to see it) and is <= budget."""
    n = _count_lines(read_skill_md())
    with capsys.disabled():
        print(f"\n[SMK-002] SKILL.md line count = {n} (budget {LINE_BUDGET})")
    assert n <= LINE_BUDGET, f"{n} exceeds budget {LINE_BUDGET}"


if __name__ == "__main__":
    problems = check_convergence_contract(read_skill_md())
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        raise SystemExit(1)
    print(
        f"[OK] convergence contract holds ({_count_lines(read_skill_md())} lines <= {LINE_BUDGET})"
    )

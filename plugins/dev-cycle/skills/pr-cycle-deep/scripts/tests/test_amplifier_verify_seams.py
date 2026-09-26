"""Test Seams check for amplifier-verify.py (Check 4).

A testplan declares the public boundaries it tests at (`## Test Seams`, a table with `Seam` and
`Public interface` columns and no ID column); each TC table may carry a `Seam` column mapping the
TC to one of them. Idea taken from mattpocock/skills' tdd skill ("test only at pre-agreed seams"):
agreeing the seams up front, during propose, is what keeps tests at public interfaces instead of
internals.

Severity is chosen so existing plans are not retroactively flagged: a plan with neither a seam
table nor a Seam column gets INFO (UNVERIFIED), never SHOULD. A plan that opted into seams -- it
declares them, or its TC tables carry a Seam column -- and then maps a TC to an undeclared, empty
or conflicting seam gets SHOULD: that is a defect in the plan, not its shape.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "amplifier-verify.py"
_spec = importlib.util.spec_from_file_location("amplifier_verify_seams", _SCRIPT)
av = importlib.util.module_from_spec(_spec)
sys.modules["amplifier_verify_seams"] = av
_spec.loader.exec_module(av)

SEAMS_TABLE = """\
## Test Seams

| Seam | Public interface | Why here |
|------|------------------|----------|
| `invite-api` | `POST /api/v1/families/{id}/invitations` | the contract mobile depends on |
| invite-service | `InvitationService.create` | business rules without HTTP |
"""

TC_TABLE_WITH_SEAMS = """\
| TC-ID | Seam | Test Purpose |
|-------|------|--------------|
| INV-API-001 | invite-api | duplicate email returns 409 |
| INV-SVC-001 | `invite-service` | expired invite is rejected |
"""


def _tc_table(*rows: str) -> str:
    return "| TC-ID | Seam | Test Purpose |\n|---|---|---|\n" + "".join(r + "\n" for r in rows)


def _check(plan: str) -> object:
    """Run the plan through the same parse -> analyze path main() uses."""
    return av.analyze(
        av.parse_tc_table(plan),
        [],
        [],
        seams=av.parse_seams(plan),
        tc_seams=av.parse_tc_seams(plan),
    )


def _seam_should(f: object) -> list[str]:
    return [s for s in f.should if "seam" in s.lower()]


# --- parsing -----------------------------------------------------------------------------------


def test_parse_seams_reads_the_declaration_table_and_strips_backticks():
    assert av.parse_seams(SEAMS_TABLE + "\n" + TC_TABLE_WITH_SEAMS) == [
        "invite-api",
        "invite-service",
    ]


def test_a_tc_tables_seam_column_is_not_a_declaration():
    # A TC table has an ID column; its Seam column references seams, it does not declare them.
    assert av.parse_seams(TC_TABLE_WITH_SEAMS) == []


def test_parse_tc_seams_maps_each_tc_to_its_seam():
    assert av.parse_tc_seams(SEAMS_TABLE + "\n" + TC_TABLE_WITH_SEAMS) == {
        "INV-API-001": ["invite-api"],
        "INV-SVC-001": ["invite-service"],
    }


def test_parse_tc_seams_normalises_case_and_backticks():
    assert av.parse_tc_seams(_tc_table("| INV-API-001 | `Invite-API` | x |")) == {
        "INV-API-001": ["invite-api"]
    }


def test_tc_table_without_a_seam_column_maps_nothing():
    plain = "| TC-ID | Test Purpose |\n|---|---|\n| INV-API-001 | x |\n"
    assert av.parse_tc_seams(plain) == {}


def test_example_tables_in_fenced_code_are_not_declarations():
    fenced = "```markdown\n" + SEAMS_TABLE + "```\n"
    assert av.parse_seams(fenced) == []


def test_example_tables_in_tilde_fences_are_not_declarations():
    # CommonMark `~~~` fences: a ```-only toggle read this example as a real declaration, so the
    # example seam became "declared" and a TC using it passed clean.
    fenced = "~~~markdown\n" + SEAMS_TABLE + "~~~\n"
    assert av.parse_seams(fenced) == []


def test_an_inner_fence_does_not_close_an_outer_longer_one():
    fenced = "````markdown\n```\nx\n```\n" + SEAMS_TABLE + "````\n"
    assert av.parse_seams(fenced) == []


def test_a_table_without_a_public_interface_column_is_not_a_declaration():
    # A traceability summary lists seams too; reading it as a declaration whitelists the very
    # undeclared seam the check should reject.
    summary = "| Seam | TC-IDs |\n|---|---|\n| invite-repo | INV-API-001 |\n"
    assert av.parse_seams(SEAMS_TABLE + "\n" + summary) == ["invite-api", "invite-service"]


def test_a_column_merely_containing_seam_is_not_the_seam_column():
    notes = "| Seam notes | Public interface |\n|---|---|\n| invite-repo | x |\n"
    assert av.parse_seams(notes) == []


def test_every_declaration_table_is_merged():
    second = "| Seam | Public interface |\n|---|---|\n| invite-web | /invite |\n"
    assert av.parse_seams(SEAMS_TABLE + "\n" + second) == [
        "invite-api",
        "invite-service",
        "invite-web",
    ]


def test_a_row_short_of_its_seam_cell_records_an_empty_seam():
    # GFM renders the missing trailing cell as empty, so it must not read as "no Seam column".
    plan = "| TC-ID | Purpose | Seam |\n|---|---|---|\n| INV-API-001 | a |\n"
    assert av.parse_tc_seams(plan) == {"INV-API-001": [""]}


# --- analyze ---------------------------------------------------------------------------------


def _tc(tc_id: str) -> object:
    return av.TCRow(tc_id=tc_id, slug="", raw_line="")


def test_no_declared_seams_is_info_not_should():
    f = av.analyze([_tc("INV-API-001")], [], [], seams=[], tc_seams={})
    assert not _seam_should(f)
    assert any("Test Seams" in i and "UNVERIFIED" in i for i in f.info)


def test_a_plan_written_before_check_4_stays_info_end_to_end():
    old = "| TC-ID | Test Purpose |\n|---|---|\n| INV-API-001 | x |\n"
    f = _check(old)
    assert not _seam_should(f)
    assert any("declares no Test Seams table" in i for i in f.info)


def test_tc_mapped_to_an_undeclared_seam_is_should():
    f = av.analyze(
        [_tc("INV-API-001")],
        [],
        [],
        seams=["invite-api"],
        tc_seams={"INV-API-001": ["invite-repo"]},
    )
    assert any("INV-API-001" in s and "invite-repo" in s for s in f.should)


def test_tc_with_an_empty_seam_cell_is_should_when_seams_are_declared():
    f = av.analyze(
        [_tc("INV-API-001")], [], [], seams=["invite-api"], tc_seams={"INV-API-001": [""]}
    )
    # Assert the finding CLASS, not just the TC-ID: without this the "undeclared seam" branch
    # also catches "" and reports "mapped to seam ''", and a TC-ID-only assertion stays green.
    assert any("INV-API-001" in s and "empty Seam cell" in s for s in f.should)
    assert not any("mapped to seam ''" in s for s in f.should)


def test_tcs_absent_from_every_seam_column_are_info():
    f = av.analyze(
        [_tc("INV-API-001"), _tc("INV-SVC-001")],
        [],
        [],
        seams=["invite-api"],
        tc_seams={"INV-API-001": ["invite-api"]},
    )
    assert not any("INV-SVC-001" in s for s in f.should)
    assert any("1/2" in i and "seam" in i.lower() for i in f.info)


def test_every_tc_on_a_declared_seam_raises_no_seam_finding():
    f = av.analyze(
        [_tc("INV-API-001")],
        [],
        [],
        seams=["invite-api"],
        tc_seams={"INV-API-001": ["invite-api"]},
    )
    assert not _seam_should(f)
    assert not any("UNVERIFIED" in i and "Seam" in i for i in f.info)


def test_seam_matching_ignores_case():
    f = av.analyze(
        [_tc("INV-API-001")],
        [],
        [],
        seams=["Invite-API"],
        tc_seams={"INV-API-001": ["invite-api"]},
    )
    assert not _seam_should(f)


# --- end to end: shapes that used to fall silent -----------------------------------------------


def test_an_undeclared_seam_in_a_later_table_is_reported_in_either_order():
    a = _tc_table("| INV-API-001 | invite-api | overview |")
    b = _tc_table("| INV-API-001 | invite-repo | detail |")
    for plan in (SEAMS_TABLE + "\n" + a + "\n" + b, SEAMS_TABLE + "\n" + b + "\n" + a):
        assert any("INV-API-001" in s and "'invite-repo'" in s for s in _check(plan).should)


def test_an_empty_overview_cell_does_not_outvote_a_real_seam():
    a = _tc_table("| INV-API-001 |  | overview |")
    b = _tc_table("| INV-API-001 | invite-api | detail |")
    assert not _seam_should(_check(SEAMS_TABLE + "\n" + a + "\n" + b))


def test_one_tc_on_two_declared_seams_is_should():
    a = _tc_table("| INV-API-001 | invite-api | x |")
    b = _tc_table("| INV-API-001 | invite-service | y |")
    f = _check(SEAMS_TABLE + "\n" + a + "\n" + b)
    assert any("INV-API-001" in s and "different seams" in s for s in f.should)


def test_a_tc_only_in_the_second_tc_table_is_checked():
    a = _tc_table("| INV-API-001 | invite-api | x |")
    b = _tc_table("| INV-API-002 | invite-repo | y |")
    assert any("INV-API-002" in s for s in _check(SEAMS_TABLE + "\n" + a + "\n" + b).should)


def test_a_row_short_of_its_seam_cell_is_the_empty_should_end_to_end():
    plan = SEAMS_TABLE + "\n| TC-ID | Purpose | Seam |\n|---|---|---|\n| INV-API-001 | a |\n"
    assert any("INV-API-001" in s and "empty Seam cell" in s for s in _check(plan).should)


def test_an_empty_declaration_table_does_not_waive_the_tc_seams():
    # Header + separator, no rows: seams=[] used to route to the no-seam-table INFO, so an
    # undeclared and an empty TC seam both passed.
    empty = "| Seam | Public interface | Why here |\n|---|---|---|\n"
    plan = empty + "\n" + _tc_table("| INV-API-001 | unknown-api | x |", "| INV-API-002 |  | y |")
    f = _check(plan)
    assert any("no Test Seams declaration was recognised" in s for s in f.should)
    assert not any("declares no Test Seams table" in i for i in f.info)


def test_an_unrecognised_declaration_table_does_not_waive_the_tc_seams():
    # An extra ID column makes the declaration read as a TC table; a header variant makes it
    # read as nothing. Either way the TCs opted into seams, so the gap must be loud.
    for header in ("| Seam | Public interface | AC-ID |", "| Seam name | Public interface | x |"):
        decl = header + "\n|---|---|---|\n| invite-api | POST /x | AC-01 |\n"
        f = _check(decl + "\n" + _tc_table("| INV-API-001 | invite-repo | x |"))
        assert any("no Test Seams declaration was recognised" in s for s in f.should), header


def test_the_testplan_template_passes_its_own_seam_check():
    # Real-file control: the template every new plan is copied from must declare the seam its own
    # example TC uses. A first draft declared `invite-api` while the TC said `login-api`, so every
    # plan written from it would have started with a Check 4 SHOULD.
    template = (
        Path(__file__).resolve().parents[6]
        / "plugins"
        / "sdd"
        / "references"
        / "testplan-template.md"
    )
    text = template.read_text(encoding="utf-8")
    assert av.parse_seams(text), "template lost its Test Seams table"
    assert av.parse_tc_seams(text), "template's TC table lost its Seam column"
    assert not _seam_should(_check(text))


def test_analyze_defaults_keep_the_old_call_shape_working():
    # Existing tests (and any external caller) call analyze() without seam arguments.
    f = av.analyze([_tc("INV-API-001")], [], [])
    assert any("Test Seams" in i for i in f.info)

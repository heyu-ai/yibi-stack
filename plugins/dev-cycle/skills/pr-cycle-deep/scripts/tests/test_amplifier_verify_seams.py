"""Test Seams check for amplifier-verify.py (Check 4).

A testplan declares the public boundaries it tests at (`## Test Seams`, a table with a `Seam`
column and no ID column); each TC table may carry a `Seam` column mapping the TC to one of them.
Idea taken from mattpocock/skills' tdd skill ("test only at pre-agreed seams"): agreeing the seams
up front, during propose, is what keeps tests at public interfaces instead of internals.

Severity is chosen so existing plans are not retroactively flagged: a plan that declares no seams
gets INFO (UNVERIFIED), never SHOULD. Only a plan that DOES declare seams and then maps a TC to an
undeclared or empty seam gets SHOULD -- that is a defect in the plan, not its shape.
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
        "INV-API-001": "invite-api",
        "INV-SVC-001": "invite-service",
    }


def test_tc_table_without_a_seam_column_maps_nothing():
    plain = "| TC-ID | Test Purpose |\n|---|---|\n| INV-API-001 | x |\n"
    assert av.parse_tc_seams(plain) == {}


def test_example_tables_in_fenced_code_are_not_declarations():
    fenced = "```markdown\n" + SEAMS_TABLE + "```\n"
    assert av.parse_seams(fenced) == []


def _tc(tc_id: str) -> object:
    return av.TCRow(tc_id=tc_id, slug="", raw_line="")


def test_no_declared_seams_is_info_not_should():
    f = av.analyze([_tc("INV-API-001")], [], [], seams=[], tc_seams={})
    assert not any("seam" in s.lower() for s in f.should)
    assert any("Test Seams" in i and "UNVERIFIED" in i for i in f.info)


def test_tc_mapped_to_an_undeclared_seam_is_should():
    f = av.analyze(
        [_tc("INV-API-001")], [], [], seams=["invite-api"], tc_seams={"INV-API-001": "invite-repo"}
    )
    assert any("INV-API-001" in s and "invite-repo" in s for s in f.should)


def test_tc_with_an_empty_seam_cell_is_should_when_seams_are_declared():
    f = av.analyze([_tc("INV-API-001")], [], [], seams=["invite-api"], tc_seams={"INV-API-001": ""})
    # Assert the finding CLASS, not just the TC-ID: without this the "undeclared seam" branch
    # also catches "" and reports "mapped to seam ''" -- mutation S3 survived on exactly that.
    assert any("INV-API-001" in s and "empty Seam cell" in s for s in f.should)
    assert not any("mapped to seam ''" in s for s in f.should)


def test_tcs_absent_from_every_seam_column_are_info():
    f = av.analyze(
        [_tc("INV-API-001"), _tc("INV-SVC-001")],
        [],
        [],
        seams=["invite-api"],
        tc_seams={"INV-API-001": "invite-api"},
    )
    assert not any("INV-SVC-001" in s for s in f.should)
    assert any("1/2" in i and "seam" in i.lower() for i in f.info)


def test_every_tc_on_a_declared_seam_raises_no_seam_finding():
    f = av.analyze(
        [_tc("INV-API-001")], [], [], seams=["invite-api"], tc_seams={"INV-API-001": "invite-api"}
    )
    assert not any("seam" in s.lower() for s in f.should)
    assert not any("UNVERIFIED" in i and "Seam" in i for i in f.info)


def test_seam_matching_ignores_case_and_backticks():
    f = av.analyze(
        [_tc("INV-API-001")], [], [], seams=["Invite-API"], tc_seams={"INV-API-001": "invite-api"}
    )
    assert not any("seam" in s.lower() for s in f.should)


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
    seams = av.parse_seams(text)
    assert seams, "template lost its Test Seams table"
    tc_seams = av.parse_tc_seams(text)
    assert tc_seams, "template's TC table lost its Seam column"
    f = av.analyze(av.parse_tc_table(text), [], [], seams=seams, tc_seams=tc_seams)
    assert not [s for s in f.should if "seam" in s.lower()]


def test_analyze_defaults_keep_the_old_call_shape_working():
    # main() and existing tests call analyze() without seam arguments.
    f = av.analyze([_tc("INV-API-001")], [], [])
    assert any("Test Seams" in i for i in f.info)

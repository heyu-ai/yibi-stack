"""Tests for plugins/sdd/scripts/check_testplan_trace.py.

The checker exists because testplans were written and never verified: TC-IDs were matched by
free-text grep, so a generic ID in a fixture counted as "covered". These tests pin the property
that replaces that grep -- a binding is only what a test's docstring explicitly declares.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from check_testplan_trace import (
    Binding,
    ChangeInput,
    ConfigError,
    Testplan,
    check_trace,
    parse_bindings,
    parse_testplan,
)


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


TESTPLAN_WITH_KIND = """\
# demo — Test Plan

trace: enforced

## TC Table

| TC-ID | Kind | Test Purpose | Technique | Expected Result |
|-------|------|--------------|-----------|-----------------|
| LOGIN-VL-001 | auto | empty password rejected | BVA | 422 |
| LOGIN-VL-002 | manual | reviewer reads the message | EP | message shown |
"""

TESTPLAN_LEGACY = """\
# demo — Test Plan

| TC-ID | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|-------------|-----------|------|-------------|-------|-----------|----------------|
| REG-DT-001 | classify | DT | High | - | 1. run | x | ok |

## Redundant TCs

| TC-ID | 與哪個重複 | 建議動作 |
|-------|-----------|---------|
| REG-DT-009 | REG-DT-001 | 合併 |
"""


class TestParseBindings:
    def test_tpt_vl_001_docstring_line_binds_every_listed_id(self, tmp_path: Path) -> None:
        """TPT-VL-001: `tc: A, B` in a test docstring binds both IDs."""
        path = _write(
            tmp_path,
            "tests/test_login.py",
            'def test_login():\n    """\n    spec: login#require-password\n'
            '    tc: LOGIN-VL-001, LOGIN-VL-002\n    """\n',
        )
        bindings = parse_bindings(path, tmp_path)
        assert len(bindings) == 1
        assert bindings[0].tc_ids == ("LOGIN-VL-001", "LOGIN-VL-002")
        assert bindings[0].spec_slugs == ("require-password",)
        assert bindings[0].nodeid == "tests/test_login.py::test_login"

    def test_tpt_vl_002_literal_id_in_fixture_does_not_bind(self, tmp_path: Path) -> None:
        """TPT-VL-002: an ID inside test data, a comment, or a non-docstring string never binds."""
        path = _write(
            tmp_path,
            "tests/test_fixture.py",
            'FIXTURE = "tc: SMK-001"\n\n'
            "def test_uses_fixture():\n"
            "    # tc: SMK-002\n"
            '    data = "SMK-003"\n'
            "    assert data\n",
        )
        assert [b for b in parse_bindings(path, tmp_path) if b.tc_ids] == []

    def test_tpt_vl_003_method_nodeid_includes_class(self, tmp_path: Path) -> None:
        """TPT-VL-003: a method binding reports path::Class::method as its node id."""
        path = _write(
            tmp_path,
            "tests/test_cls.py",
            'class TestLogin:\n    def test_x(self):\n        """tc: LOGIN-VL-001"""\n',
        )
        assert [b.nodeid for b in parse_bindings(path, tmp_path)] == [
            "tests/test_cls.py::TestLogin::test_x"
        ]

    def test_tpt_vl_004_non_test_function_ignored(self, tmp_path: Path) -> None:
        """TPT-VL-004: a helper whose name does not start with test_ is not a binding."""
        path = _write(tmp_path, "tests/test_h.py", 'def helper():\n    """tc: LOGIN-VL-001"""\n')
        assert parse_bindings(path, tmp_path) == []

    def test_tpt_vl_005_id_mentioned_in_docstring_prose_does_not_bind(self, tmp_path: Path) -> None:
        """TPT-VL-005: only a line starting with tc: binds; an ID cited in prose does not."""
        path = _write(
            tmp_path,
            "tests/test_prose.py",
            'def test_regression():\n    """Regression for SMK-001 (see LOGIN-VL-009).\n\n'
            '    spec: login#require-password\n    """\n',
        )
        assert parse_bindings(path, tmp_path)[0].tc_ids == ()


class TestParseTestplan:
    def test_tpt_dt_001_kind_column_classifies(self) -> None:
        """TPT-DT-001: the Kind column yields auto / manual per TC."""
        plan = parse_testplan(TESTPLAN_WITH_KIND)
        assert plan.enforced is True
        assert plan.has_kind is True
        assert plan.tcs == {"LOGIN-VL-001": "auto", "LOGIN-VL-002": "manual"}

    def test_tpt_dt_002_missing_kind_column_is_legacy(self) -> None:
        """TPT-DT-002: no Kind column -> legacy; every TC is treated as automatable."""
        plan = parse_testplan(TESTPLAN_LEGACY)
        assert plan.has_kind is False
        assert plan.enforced is False
        assert plan.tcs == {"REG-DT-001": "auto"}

    def test_tpt_eg_001_non_tc_table_with_tc_id_column_not_parsed(self) -> None:
        """TPT-EG-001: a Redundant table that starts with TC-ID is not the TC table."""
        assert "REG-DT-009" not in parse_testplan(TESTPLAN_LEGACY).tcs

    def test_tpt_eg_002_unknown_kind_value_is_treated_as_auto(self) -> None:
        """TPT-EG-002: a Kind value other than auto/manual fails safe -- it still needs a test."""
        text = TESTPLAN_WITH_KIND.replace("| LOGIN-VL-002 | manual |", "| LOGIN-VL-002 | mech |")
        assert parse_testplan(text).tcs["LOGIN-VL-002"] == "auto"

    def test_tpt_eg_003_no_tc_table_is_unparsed(self) -> None:
        """TPT-EG-003: a testplan without any TC table reports parse_ok False, not zero TCs."""
        plan = parse_testplan("# demo\n\ntrace: enforced\n\nno table here\n")
        assert plan.parse_ok is False

    def test_tpt_dt_003_slug_mapping_and_manual_items(self) -> None:
        """TPT-DT-003: Coverage rows map TC -> slug; Manual Verification items keep their state."""
        text = (
            TESTPLAN_WITH_KIND
            + "\n## Coverage Analysis\n\n| Scenario slug | TC-ID(s) |\n|---|---|\n"
            + "| `require-password` | LOGIN-VL-001, LOGIN-VL-002 |\n"
            + "\n## Manual Verification\n\n- [ ] MV-001 reviewer sees it (scenario: x)\n"
            + "- [x] MV-002 done already (scenario: y)\n\n## Other\n\n- [ ] MV-003 not in section\n"
        )
        plan = parse_testplan(text)
        assert plan.tc_slugs["LOGIN-VL-001"] == {"require-password"}
        assert [(m.item_id, m.checked) for m in plan.manual] == [
            ("MV-001", False),
            ("MV-002", True),
        ]


# ---------------------------------------------------------------------------
# check_trace：純函式，全部用合成資料
# ---------------------------------------------------------------------------


def _plan(
    tcs: dict[str, str],
    slugs: dict[str, set[str]] | None = None,
    *,
    enforced: bool = True,
    has_kind: bool = True,
    manual: list | None = None,
) -> Testplan:
    return Testplan(
        enforced=enforced,
        has_kind=has_kind,
        parse_ok=True,
        tcs=dict(tcs),
        tc_slugs=dict(slugs or {}),
        manual=list(manual or []),
    )


def _change(name: str, plan: Testplan, total: int = 5, done: int = 5) -> ChangeInput:
    return ChangeInput(name=name, plan=plan, tasks_total=total, tasks_done=done)


def _kinds(findings) -> list[tuple[str, str, str]]:
    return sorted((f.kind, f.tc_id, f.severity) for f in findings)


class TestMissing:
    def test_tpt_dt_010_auto_tc_without_test_is_missing(self) -> None:
        """TPT-DT-010: an auto TC with no binding is missing (spec: auto-tc-without-test)."""
        plan = _plan({"REG-VL-001": "auto"}, {"REG-VL-001": {"s"}})
        findings = check_trace([_change("c", plan)], {}, [], strict=False)
        assert _kinds(findings) == [("missing", "REG-VL-001", "FAIL")]

    def test_tpt_dt_011_bound_or_manual_tc_is_not_missing(self) -> None:
        """TPT-DT-011: a bound auto TC and a manual TC produce no missing finding."""
        plan = _plan({"REG-VL-001": "auto", "REG-VL-002": "manual"}, {"REG-VL-001": {"s"}})
        binding = Binding("t.py::test_a", ("REG-VL-001",), ("s",))
        assert check_trace([_change("c", plan)], {}, [binding], strict=False) == []


class TestOrphan:
    def test_tpt_dt_020_renamed_prefix_is_orphan_and_missing(self) -> None:
        """TPT-DT-020: FREG-* binding for a REG-* plan -> orphan + missing (spec example)."""
        plan = _plan({"REG-DT-001": "auto"}, {"REG-DT-001": {"load-registry"}})
        binding = Binding("t.py::test_a", ("FREG-DT-001",), ("load-registry",))
        findings = check_trace([_change("registry", plan)], {}, [binding], strict=False)
        assert _kinds(findings) == [
            ("missing", "REG-DT-001", "FAIL"),
            ("orphan", "FREG-DT-001", "FAIL"),
        ]

    def test_tpt_dt_021_id_defined_only_in_archive_is_not_orphan(self) -> None:
        """TPT-DT-021: a binding to an archived TC is valid history, not an orphan."""
        archived = {"old": _plan({"OLD-VL-001": "auto"}, enforced=False)}
        binding = Binding("t.py::test_a", ("OLD-VL-001",), ("x",))
        assert check_trace([], archived, [binding], strict=False) == []

    def test_tpt_eg_020_unattributable_orphan_is_warn(self) -> None:
        """TPT-EG-020: an orphan whose spec slug matches no enforced change is only WARN."""
        plan = _plan({"REG-DT-001": "auto"}, {"REG-DT-001": {"load-registry"}})
        bindings = [
            Binding("t.py::test_ok", ("REG-DT-001",), ("load-registry",)),
            Binding("t.py::test_x", ("ZZZ-VL-001",), ("unrelated",)),
        ]
        findings = check_trace([_change("registry", plan)], {}, bindings, strict=False)
        assert _kinds(findings) == [("orphan", "ZZZ-VL-001", "WARN")]


class TestMismatch:
    @pytest.mark.parametrize(
        ("spec_slugs", "expected"),
        [
            (("negative-untriggered-passes",), []),
            (("baseline-regression",), [("mismatch", "SEVAL-DT-003", "FAIL")]),
            ((), [("mismatch", "SEVAL-DT-003", "FAIL")]),
        ],
    )
    def test_tpt_dt_030_binding_scenario_agreement(
        self, spec_slugs: tuple[str, ...], expected: list[tuple[str, str, str]]
    ) -> None:
        """TPT-DT-030: the three rows of the spec's agreement-outcomes example table."""
        plan = _plan({"SEVAL-DT-003": "auto"}, {"SEVAL-DT-003": {"negative-untriggered-passes"}})
        binding = Binding("t.py::test_a", ("SEVAL-DT-003",), spec_slugs)
        findings = check_trace([_change("seval", plan)], {}, [binding], strict=False)
        assert _kinds(findings) == expected

    def test_tpt_dt_031_missing_spec_line_names_the_fix(self) -> None:
        """TPT-DT-031: tc line without spec line says so explicitly."""
        plan = _plan({"SEVAL-DT-003": "auto"}, {"SEVAL-DT-003": {"negative-untriggered-passes"}})
        binding = Binding("t.py::test_a", ("SEVAL-DT-003",), ())
        (finding,) = check_trace([_change("seval", plan)], {}, [binding], strict=False)
        assert "沒有 spec 行" in finding.detail

    def test_tpt_eg_030_unmapped_tc_is_not_judged(self) -> None:
        """TPT-EG-030: a TC the testplan never mapped to a slug cannot be judged -- no mismatch."""
        plan = _plan({"SEVAL-DT-004": "auto"})
        binding = Binding("t.py::test_a", ("SEVAL-DT-004",), ("anything",))
        assert check_trace([_change("seval", plan)], {}, [binding], strict=False) == []


class TestCollision:
    def test_tpt_dt_040_active_vs_archived_collision(self) -> None:
        """TPT-DT-040: an active TC-ID also defined by an archived plan collides."""
        plan = _plan({"PRC-DT-001": "auto"}, {"PRC-DT-001": {"s"}})
        archived = {"bound-review-loop": _plan({"PRC-DT-001": "auto"}, enforced=False)}
        binding = Binding("t.py::test_a", ("PRC-DT-001",), ("s",))
        findings = check_trace([_change("contract", plan)], archived, [binding], strict=False)
        assert _kinds(findings) == [("collision", "PRC-DT-001", "FAIL")]
        assert "bound-review-loop" in findings[0].detail

    def test_tpt_dt_041_unique_ids_do_not_collide(self) -> None:
        """TPT-DT-041: distinct IDs across active and archived plans produce no collision."""
        plan = _plan({"PRC-DT-001": "auto"}, {"PRC-DT-001": {"s"}})
        archived = {"other": _plan({"PRC-DT-002": "auto"}, enforced=False)}
        binding = Binding("t.py::test_a", ("PRC-DT-001",), ("s",))
        assert check_trace([_change("contract", plan)], archived, [binding], strict=False) == []


class TestRatchet:
    @pytest.mark.parametrize(
        ("enforced", "total", "done", "strict", "severity"),
        [
            (False, 5, 5, True, "WARN"),
            (True, 5, 3, False, "WARN"),
            (True, 5, 5, False, "FAIL"),
            (True, 0, 0, False, "WARN"),
            (True, 5, 3, True, "FAIL"),
        ],
    )
    def test_tpt_dt_050_ratchet_matrix(
        self, enforced: bool, total: int, done: int, strict: bool, severity: str
    ) -> None:
        """TPT-DT-050: the five rows of the spec's ratchet-outcomes example table."""
        plan = _plan({"REG-VL-001": "auto"}, enforced=enforced)
        findings = check_trace([_change("c", plan, total, done)], {}, [], strict=strict)
        assert [f.severity for f in findings] == [severity]

    def test_tpt_eg_050_legacy_without_kind_is_always_warn(self) -> None:
        """TPT-EG-050: an enforced plan without a Kind column is still legacy -> WARN only."""
        plan = _plan({"REG-VL-001": "auto"}, has_kind=False)
        findings = check_trace([_change("c", plan)], {}, [], strict=True)
        assert [f.severity for f in findings] == ["WARN"]


class TestManualAndUnparsable:
    def test_tpt_dt_060_unchecked_manual_item_blocks_strict(self) -> None:
        """TPT-DT-060: under --strict an unchecked MV item -> manual-open FAIL; checked -> none."""
        from check_testplan_trace import ManualItem

        items = [ManualItem("MV-002", False, "reviewer sees it"), ManualItem("MV-003", True, "ok")]
        plan = _plan({}, manual=items)
        findings = check_trace([_change("c", plan, 5, 3)], {}, [], strict=True)
        assert _kinds(findings) == [("manual-open", "MV-002", "FAIL")]

    def test_tpt_dt_061_manual_items_ignored_without_strict(self) -> None:
        """TPT-DT-061: manual-open is a strict-mode finding only."""
        from check_testplan_trace import ManualItem

        plan = _plan({}, manual=[ManualItem("MV-002", False, "x")])
        assert check_trace([_change("c", plan)], {}, [], strict=False) == []

    def test_tpt_dt_062_unparsable_legacy_warns(self) -> None:
        """TPT-DT-062: a legacy plan with no TC table -> unparsable WARN (spec)."""
        plan = Testplan(enforced=False, parse_ok=False)
        assert _kinds(check_trace([_change("c", plan)], {}, [], strict=True)) == [
            ("unparsable", "-", "WARN")
        ]

    def test_tpt_eg_060_unparsable_enforced_is_config_error(self) -> None:
        """TPT-EG-060: an enforced plan with no TC table raises ConfigError, never 'clean'."""
        plan = Testplan(enforced=True, parse_ok=False)
        with pytest.raises(ConfigError):
            check_trace([_change("c", plan)], {}, [], strict=False)

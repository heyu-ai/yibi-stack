"""選取 change 時仍以完整 ownership 判定追溯，不混入其他 change 的檢查。"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest
from check_testplan_trace import Binding, ChangeInput, Testplan, check_trace, load_changes

SCRIPT = Path(__file__).resolve().parents[1] / "check_testplan_trace.py"


def _change(name: str, tc_id: str, slug: str) -> ChangeInput:
    return ChangeInput(
        name,
        Testplan(
            enforced=True,
            has_kind=True,
            parse_ok=True,
            tcs={tc_id: "manual"},
            tc_slugs={tc_id: {slug}},
        ),
        1,
        1,
    )


def _binding(tc_id: str, *slugs: str) -> Binding:
    return Binding("tests/test_scope.py::test_case", (tc_id,), slugs)


@pytest.mark.parametrize("archived", [False, True])
def test_known_elsewhere_is_not_selected_orphan(archived: bool) -> None:
    selected = _change("selected", "SEL-VL-001", "selected-slug")
    other = _change("other", "OTHER-VL-001", "other-slug")
    findings = check_trace(
        [selected],
        {other.name: other.plan} if archived else {},
        [_binding("OTHER-VL-001", "selected-slug")],
        strict=True,
        known_active=[selected] if archived else [selected, other],
    )
    assert findings == []


@pytest.mark.parametrize(
    ("slugs", "expected"),
    [
        (("selected-slug",), [("FAIL", "selected")]),
        (("other-slug",), []),
        (("selected-slug", "other-slug"), [("WARN", "-")]),
        (("unmapped",), [("WARN", "-")]),
        ((), [("WARN", "-")]),
    ],
)
def test_undefined_ids_follow_complete_scenario_ownership(
    slugs: tuple[str, ...], expected: list[tuple[str, str]]
) -> None:
    selected = _change("selected", "SEL-VL-001", "selected-slug")
    other = _change("other", "OTHER-VL-001", "other-slug")
    findings = check_trace(
        [selected],
        {},
        [_binding("UNKNOWN-VL-001", *slugs)],
        strict=True,
        known_active=[selected, other],
    )
    assert [(f.severity, f.change) for f in findings] == expected
    assert all(f.kind == "orphan" and f.tc_id == "UNKNOWN-VL-001" for f in findings)


@pytest.mark.parametrize("archived", [False, True])
def test_selected_collisions_keep_real_owner_identity(archived: bool) -> None:
    selected = _change("selected", "SAME-VL-001", "shared")
    other = _change("other", "SAME-VL-001", "shared")
    findings = check_trace(
        [selected],
        {other.name: other.plan} if archived else {},
        [],
        strict=True,
        known_active=[selected] if archived else [selected, other],
    )
    assert [(f.kind, f.change, f.severity) for f in findings] == [("collision", "selected", "FAIL")]
    owner = "archive/other" if archived else "other"
    assert findings[0].detail.endswith(owner)
    if not archived:
        assert "archive/" not in findings[0].detail


def test_context_does_not_require_repeating_selected_change() -> None:
    selected = _change("selected", "SEL-VL-001", "selected-slug")
    other = _change("other", "OTHER-VL-001", "other-slug")
    assert (
        check_trace(
            [selected],
            {},
            [_binding("SEL-VL-001", "selected-slug")],
            strict=True,
            known_active=[other],
        )
        == []
    )


def test_default_all_change_checks_still_include_each_owner() -> None:
    selected = _change("selected", "SEL-VL-001", "selected-slug")
    other = _change("other", "OTHER-VL-001", "other-slug")
    findings = check_trace(
        [selected, other], {}, [_binding("UNKNOWN-VL-001", "other-slug")], strict=True
    )
    assert [(f.kind, f.change, f.severity) for f in findings] == [("orphan", "other", "FAIL")]


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("slug", ["selected-slug", "other-slug"])
def test_unparsed_context_never_proves_absence_or_unrelatedness(archived: bool, slug: str) -> None:
    selected = _change("selected", "SEL-VL-001", "selected-slug")
    other = _change("other", "OTHER-VL-001", "other-slug")
    unknown = ChangeInput("unknown", Testplan(enforced=True, parse_ok=False), 0, 0)
    findings = check_trace(
        [selected],
        {unknown.name: unknown.plan} if archived else {},
        [_binding("UNKNOWN-VL-001", slug)],
        strict=True,
        known_active=[selected, other] if archived else [selected, other, unknown],
    )
    assert [(f.kind, f.severity) for f in findings] == [
        ("ownership-unparsed", "WARN"),
        ("orphan", "WARN"),
    ]
    assert "unknown" in findings[0].detail
    assert "ownership 不完整" in findings[1].detail


def _write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _plan(repo: Path, name: str, tc_id: str, slug: str) -> None:
    _write(
        repo,
        f"openspec/changes/{name}/testplan.md",
        "trace: enforced\n\n"
        "| TC-ID | Kind | Test Purpose | Expected Result |\n"
        "|---|---|---|---|\n"
        f"| {tc_id} | auto | scoped ownership | correct owner |\n\n"
        "## Coverage Analysis\n\n"
        "| Scenario slug | TC-ID(s) |\n|---|---|\n"
        f"| `{slug}` | {tc_id} |\n",
    )


def _test(repo: Path, name: str, tc_id: str, *slugs: str) -> None:
    markers = "".join(f"    spec: scope#{slug}\n" for slug in slugs)
    _write(
        repo,
        f"tests/test_{name}.py",
        f'def test_{name}():\n    """\n{markers}    tc: {tc_id}\n    """\n',
    )


def _repo(repo: Path) -> None:
    _plan(repo, "selected", "SEL-VL-001", "selected-slug")
    _plan(repo, "other", "OTHER-VL-001", "other-slug")
    _test(repo, "selected", "SEL-VL-001", "selected-slug")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--strict", *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("archived", [False, True])
def test_cli_known_elsewhere_is_not_orphan(tmp_path: Path, archived: bool) -> None:
    _repo(tmp_path)
    if archived:
        _plan(tmp_path, "archive/old", "OLD-VL-001", "old-slug")
    tc_id = "OLD-VL-001" if archived else "OTHER-VL-001"
    _test(tmp_path, "foreign", tc_id, "selected-slug")
    result = _run(tmp_path, "--change", "selected")
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("slugs", "code", "output"),
    [
        (("selected-slug",), 1, "[FAIL] orphan: selected UNKNOWN-VL-001"),
        (("other-slug",), 0, ""),
        (("selected-slug", "other-slug"), 0, "[WARN] orphan: - UNKNOWN-VL-001"),
        (("unmapped",), 0, "[WARN] orphan: - UNKNOWN-VL-001"),
        ((), 0, "[WARN] orphan: - UNKNOWN-VL-001"),
    ],
)
def test_cli_orphan_scope(tmp_path: Path, slugs: tuple[str, ...], code: int, output: str) -> None:
    _repo(tmp_path)
    _test(tmp_path, "unknown", "UNKNOWN-VL-001", *slugs)
    result = _run(tmp_path, "--change", "selected")
    assert result.returncode == code, result.stderr + result.stdout
    if output:
        assert output in result.stdout
    else:
        assert result.stdout == ""
    assert "missing: other" not in result.stdout


@pytest.mark.parametrize("archived", [False, True])
def test_cli_collision_scope(tmp_path: Path, archived: bool) -> None:
    _repo(tmp_path)
    owner = "archive/old" if archived else "other"
    _plan(tmp_path, owner, "SEL-VL-001", "selected-slug")
    result = _run(tmp_path, "--change", "selected")
    assert result.returncode == 1, result.stderr + result.stdout
    assert "[FAIL] collision: selected SEL-VL-001" in result.stdout
    assert result.stdout.rstrip().endswith(owner)
    assert len(result.stdout.splitlines()) == 1


def test_cli_report_contains_only_selected_rows(tmp_path: Path) -> None:
    _repo(tmp_path)
    _plan(tmp_path, "archive/old", "OLD-VL-001", "old-slug")
    _test(tmp_path, "other", "OTHER-VL-001", "other-slug")
    result = _run(tmp_path, "--change", "selected", "--report")
    assert result.returncode == 0, result.stderr
    assert "SEL-VL-001" in result.stdout
    assert "tests/test_selected.py::test_selected" in result.stdout
    assert "OTHER-VL-001" not in result.stdout
    assert "OLD-VL-001" not in result.stdout


def test_cli_unknown_selected_name_is_config_error(tmp_path: Path) -> None:
    _repo(tmp_path)
    result = _run(tmp_path, "--change", "missing-change")
    assert result.returncode == 2
    assert "missing-change" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("report", [False, True])
def test_cli_unparsed_ownership_is_visible(tmp_path: Path, archived: bool, report: bool) -> None:
    _repo(tmp_path)
    owner = "archive/unknown" if archived else "unknown"
    _write(tmp_path, f"openspec/changes/{owner}/testplan.md", "trace: enforced\nno table\n")
    args = ["--change", "selected"]
    if report:
        args.append("--report")
    result = _run(tmp_path, *args)
    assert result.returncode == 0, result.stderr + result.stdout
    diagnostic = result.stderr if report else result.stdout
    assert "[WARN] ownership-unparsed:" in diagnostic
    assert owner in diagnostic


def test_load_changes_keeps_active_and_archive_context_separate(tmp_path: Path) -> None:
    _repo(tmp_path)
    _plan(tmp_path, "archive/old", "OLD-VL-001", "old-slug")
    active, archived = load_changes(tmp_path / "openspec", None)
    assert {change.name for change in active} == {"selected", "other"}
    assert set(archived) == {"old"}
    selected, archived = load_changes(tmp_path / "openspec", "selected")
    assert [change.name for change in selected] == ["selected"]
    assert set(archived) == {"old"}

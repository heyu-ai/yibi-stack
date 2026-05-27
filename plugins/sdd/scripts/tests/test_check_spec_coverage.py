"""Tests for plugins/sdd/scripts/check_spec_coverage.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from check_spec_coverage import (
    CoverageResult,
    compute_coverage,
    parse_spec_scenarios,
    parse_test_traces,
)


def make_spec(tmp_path: Path, cap: str, content: str) -> Path:
    """Create a spec.md under tmp_path/specs/<cap>/spec.md."""
    spec_dir = tmp_path / "specs" / cap
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_file = spec_dir / "spec.md"
    spec_file.write_text(content, encoding="utf-8")
    return spec_file


def make_test(tmp_path: Path, name: str, content: str) -> Path:
    """Create a test_<name>.py under tmp_path/tests/."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    test_file = tests_dir / f"test_{name}.py"
    test_file.write_text(content, encoding="utf-8")
    return test_file


class TestParseSpecScenarios:
    def test_happy_path(self, tmp_path: Path) -> None:
        """CSCAN-ST-001: basic slug extraction."""
        make_spec(tmp_path, "login", "#### Scenario: require-password -- 必須提供密碼\n")
        result = parse_spec_scenarios(tmp_path / "specs")
        assert result == {"login": ["require-password"]}

    def test_multiple_slugs(self, tmp_path: Path) -> None:
        """CSCAN-ST-002: multiple scenarios in one spec."""
        content = (
            "#### Scenario: slug-a -- A\n\n#### Scenario: slug-b -- B\n"
        )
        make_spec(tmp_path, "auth", content)
        result = parse_spec_scenarios(tmp_path / "specs")
        assert result == {"auth": ["slug-a", "slug-b"]}

    def test_crlf_line_endings(self, tmp_path: Path) -> None:
        """CSCAN-EG-001: CRLF spec files should not produce 0 slugs."""
        crlf_content = "#### Scenario: add-item -- 新增項目\r\n"
        make_spec(tmp_path, "cart", crlf_content)
        result = parse_spec_scenarios(tmp_path / "specs")
        assert result == {"cart": ["add-item"]}

    def test_duplicate_slug_exits(self, tmp_path: Path) -> None:
        """CSCAN-EG-002: duplicate slug in one spec exits with code 1."""
        content = (
            "#### Scenario: same-slug -- A\n\n#### Scenario: same-slug -- B\n"
        )
        make_spec(tmp_path, "feature", content)
        with pytest.raises(SystemExit) as exc_info:
            parse_spec_scenarios(tmp_path / "specs")
        assert exc_info.value.code == 1

    def test_non_kebab_slug_warns(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """CSCAN-EG-003: non-kebab slug warns to stderr, does not track slug."""
        make_spec(tmp_path, "feature", "#### Scenario: Invalid_Slug -- bad\n")
        result = parse_spec_scenarios(tmp_path / "specs")
        assert result == {}
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err
        assert "kebab-case" in captured.err

    def test_cap_filter(self, tmp_path: Path) -> None:
        """CSCAN-ST-003: --cap filters to only the specified capability."""
        make_spec(tmp_path, "login", "#### Scenario: login-ok -- pass\n")
        make_spec(tmp_path, "register", "#### Scenario: register-ok -- pass\n")
        result = parse_spec_scenarios(tmp_path / "specs", cap="login")
        assert "login" in result
        assert "register" not in result

    def test_trailing_hyphen_slug_not_tracked(self, tmp_path: Path) -> None:
        """CSCAN-EG-004: trailing hyphen in slug is not captured by SCENARIO_PATTERN."""
        make_spec(tmp_path, "feature", "#### Scenario: bad-slug- -- trailing hyphen\n")
        result = parse_spec_scenarios(tmp_path / "specs")
        assert result == {}

    def test_empty_spec_dir_returns_empty(self, tmp_path: Path) -> None:
        """CSCAN-EG-005: empty specs dir returns empty dict."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        result = parse_spec_scenarios(specs_dir)
        assert result == {}


class TestParseTestTraces:
    def test_happy_path(self, tmp_path: Path) -> None:
        """CSCAN-ST-004: basic trace extraction."""
        make_test(
            tmp_path,
            "login",
            'def test_foo():\n    """\n    spec: login#require-password\n    """\n',
        )
        result = parse_test_traces(tmp_path / "tests")
        assert result == {"login": ["require-password"]}

    def test_cap_normalized_lowercase(self, tmp_path: Path) -> None:
        """CSCAN-EG-006: uppercase cap in trace is normalized to lowercase."""
        make_test(
            tmp_path,
            "auth",
            'def test_foo():\n    """\n    spec: Auth#login-ok\n    """\n',
        )
        result = parse_test_traces(tmp_path / "tests")
        assert "auth" in result
        assert "Auth" not in result

    def test_deduplication(self, tmp_path: Path) -> None:
        """CSCAN-EG-007: same slug traced twice in one file is deduplicated."""
        content = (
            'def test_a():\n    """\n    spec: login#require-password\n    """\n'
            'def test_b():\n    """\n    spec: login#require-password\n    """\n'
        )
        make_test(tmp_path, "login", content)
        result = parse_test_traces(tmp_path / "tests")
        assert result["login"] == ["require-password"]

    def test_no_false_positive_nospec(self, tmp_path: Path) -> None:
        """CSCAN-EG-008: 'nospec:' must not match TRACE_PATTERN."""
        make_test(tmp_path, "misc", '# nospec: login#slug\n')
        result = parse_test_traces(tmp_path / "tests")
        assert result == {}

    def test_cap_filter(self, tmp_path: Path) -> None:
        """CSCAN-ST-005: cap filter skips unrelated traces."""
        content = (
            'def test_a():\n    """\n    spec: login#ok\n    """\n'
            'def test_b():\n    """\n    spec: register#ok\n    """\n'
        )
        make_test(tmp_path, "mixed", content)
        result = parse_test_traces(tmp_path / "tests", cap="login")
        assert "login" in result
        assert "register" not in result


class TestComputeCoverage:
    def test_covered_missing_orphan(self) -> None:
        """CSCAN-ST-006: all three coverage categories computed correctly."""
        spec = {"login": ["require-password", "handle-wrong-password"]}
        traces = {"login": ["require-password"], "login2": ["orphan-slug"]}
        result = compute_coverage(spec, traces)
        assert "login#require-password" in result.covered
        assert "login#handle-wrong-password" in result.missing
        assert "login2#orphan-slug" in result.orphan

    def test_empty_spec_all_orphan(self) -> None:
        """CSCAN-EG-009: traces with no matching spec are all orphans."""
        spec: dict[str, list[str]] = {}
        traces = {"auth": ["login-ok"]}
        result = compute_coverage(spec, traces)
        assert result.covered == []
        assert result.missing == []
        assert "auth#login-ok" in result.orphan

    def test_full_coverage_no_orphan(self) -> None:
        """CSCAN-ST-007: perfect coverage produces no missing or orphan."""
        spec = {"auth": ["login-ok", "login-fail"]}
        traces = {"auth": ["login-ok", "login-fail"]}
        result = compute_coverage(spec, traces)
        assert len(result.covered) == 2
        assert result.missing == []
        assert result.orphan == []

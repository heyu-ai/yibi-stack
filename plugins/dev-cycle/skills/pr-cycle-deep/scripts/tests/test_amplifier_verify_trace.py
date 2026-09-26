"""amplifier-verify 與 sdd plugin check_testplan_trace.py 的接線（enforce-testplan-trace 3.1）。

dev-cycle 與 sdd 分開安裝，amplifier-verify 以子程序呼叫 checker。這裡守三件事：FAIL 逐行
變成 MUST、WARN 彙總成一筆 SHOULD、以及找不到 checker 或結果不可信時一律 fail-closed。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "amplifier-verify.py"
_spec = importlib.util.spec_from_file_location("amplifier_verify", _SCRIPT)
amplifier_verify = importlib.util.module_from_spec(_spec)
sys.modules["amplifier_verify"] = amplifier_verify
_spec.loader.exec_module(amplifier_verify)

Findings = amplifier_verify.Findings
TraceResult = amplifier_verify.TraceResult


def _fake_checker(tmp_path: Path, stdout: str, code: int) -> Path:
    """寫一支假的 checker：印出指定內容並以指定 exit code 結束。"""
    path = tmp_path / "fake_checker.py"
    path.write_text(
        f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({code})\n", encoding="utf-8"
    )
    return path


class TestApplyTraceResult:
    def test_avt_dt_001_fail_lines_become_one_must_each(self) -> None:
        """AVT-DT-001: every FAIL line is its own MUST finding."""
        findings = Findings()
        result = TraceResult(
            1, ["[FAIL] missing: c A-VL-001 -- x", "[FAIL] orphan: c B-VL-9 -- y"], [], ""
        )
        assert amplifier_verify.apply_trace_result(findings, result, enforced=True) is None
        assert len(findings.must) == 2
        assert all(m.startswith("testplan trace [FAIL]") for m in findings.must)

    def test_avt_dt_002_warn_lines_summarised_into_one_should(self) -> None:
        """AVT-DT-002: 23 WARN lines become ONE SHOULD with per-kind counts, not 23."""
        warns = [f"[WARN] missing: c A-VL-{i:03d} -- x" for i in range(20)] + [
            "[WARN] collision: c SMK-001 -- y",
            "[WARN] collision: c SMK-002 -- y",
            "[WARN] orphan: - Z-VL-1 -- z",
        ]
        findings = Findings()
        assert (
            amplifier_verify.apply_trace_result(
                findings, TraceResult(0, [], warns, ""), enforced=True
            )
            is None
        )
        assert findings.must == []
        assert len(findings.should) == 1
        assert "23 WARN (collision 2, missing 20, orphan 1)" in findings.should[0]

    def test_avt_dt_004_legacy_warns_are_info_not_should(self) -> None:
        """AVT-DT-004: a legacy (non-enforced) plan's WARNs go to INFO, never SHOULD.

        Same rule as Check 4: plans written before the trace gate are not retro-flagged, so a
        legacy testplan must not turn amplifier-verify from exit 0 into exit 1.
        """
        findings = Findings()
        result = TraceResult(0, [], ["[WARN] unparsable: c - -- x"], "")
        assert amplifier_verify.apply_trace_result(findings, result, enforced=False) is None
        assert findings.should == []
        assert len(findings.info) == 1 and "unparsable 1" in findings.info[0]

    def test_avt_dt_003_clean_run_adds_nothing(self) -> None:
        """AVT-DT-003: exit 0 with no lines adds no finding at all."""
        findings = Findings()
        assert (
            amplifier_verify.apply_trace_result(findings, TraceResult(0, [], [], ""), enforced=True)
            is None
        )
        assert findings.is_empty()

    def test_avt_eg_001_config_error_is_fatal(self) -> None:
        """AVT-EG-001: checker exit 2 (config error) is returned as an error -> caller exits 2."""
        error = amplifier_verify.apply_trace_result(
            Findings(), TraceResult(2, [], [], "[FAIL] 找不到 active change：x"), enforced=True
        )
        assert error is not None and "exit 2" in error and "找不到 active change" in error

    def test_avt_eg_002_exit_1_without_fail_line_is_not_trusted(self) -> None:
        """AVT-EG-002: exit 1 with no FAIL line (e.g. a traceback) is not a verdict."""
        error = amplifier_verify.apply_trace_result(
            Findings(), TraceResult(1, [], [], "Traceback ..."), enforced=True
        )
        assert error is not None and "不可信" in error

    def test_avt_eg_003_checker_that_could_not_run_is_fatal(self) -> None:
        """AVT-EG-003: returncode None (binary missing / timeout) is an error, not clean."""
        error = amplifier_verify.apply_trace_result(
            Findings(), TraceResult(None, [], [], "無法執行"), enforced=True
        )
        assert error is not None


class TestRunTraceChecker:
    def test_avt_st_001_splits_fail_and_warn_lines(self, tmp_path: Path) -> None:
        """AVT-ST-001: stdout lines are split by severity; unrelated lines are ignored."""
        checker = _fake_checker(
            tmp_path,
            "[FAIL] missing: c A-VL-001 -- x\n[WARN] collision: c SMK-001 -- y\nnoise line\n",
            1,
        )
        result = amplifier_verify.run_trace_checker(checker, tmp_path, "c")
        assert result.returncode == 1
        assert result.fails == ["[FAIL] missing: c A-VL-001 -- x"]
        assert result.warns == ["[WARN] collision: c SMK-001 -- y"]


class TestLocateTraceChecker:
    def test_avt_st_010_installed_plugin_path_wins(self, tmp_path: Path) -> None:
        """AVT-ST-010: the installPath recorded in installed_plugins.json is used when present."""
        install = tmp_path / "cache" / "sdd" / "9.9.9"
        (install / "scripts").mkdir(parents=True)
        (install / "scripts" / "check_testplan_trace.py").write_text("", encoding="utf-8")
        registry = tmp_path / "home" / ".claude" / "plugins" / "installed_plugins.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps({"plugins": {"sdd@yibi-stack": [{"installPath": str(install)}]}}),
            encoding="utf-8",
        )
        found = amplifier_verify.locate_trace_checker(tmp_path / "repo", home=tmp_path / "home")
        assert found == install / "scripts" / "check_testplan_trace.py"

    def test_avt_st_011_repo_fallback(self, tmp_path: Path) -> None:
        """AVT-ST-011: with no installed plugin, the repo's plugins/sdd copy is used."""
        repo = tmp_path / "repo"
        target = repo / "plugins" / "sdd" / "scripts" / "check_testplan_trace.py"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        assert amplifier_verify.locate_trace_checker(repo, home=tmp_path / "home") == target

    def test_avt_eg_010_nothing_found_returns_none(self, tmp_path: Path) -> None:
        """AVT-EG-010: an install path that lacks the script and no repo copy -> None."""
        registry = tmp_path / "home" / ".claude" / "plugins" / "installed_plugins.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps({"plugins": {"sdd@yibi-stack": [{"installPath": str(tmp_path / "old")}]}}),
            encoding="utf-8",
        )
        assert (
            amplifier_verify.locate_trace_checker(tmp_path / "repo", home=tmp_path / "home") is None
        )

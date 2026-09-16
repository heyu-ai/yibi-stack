"""Tests for plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy_print_timeout.py (issue #443).

agy >= 1.1.28 returns the partial output and exits 0 when `--print-timeout` expires; the only
signal is a stderr line. These tests pin the budget bounds, the two independent timeout
signals, and the quarantine of the partial output so no downstream step can consume it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agy_print_timeout import (
    BUDGET_DEFAULT_SECS,
    BUDGET_MAX_SECS,
    detect_print_timeout,
    last_quota_line,
    main,
    quarantine_partial,
    resolve_budget,
)

MARKER_STDERR = "[agy] print timeout after 40s with turn in progress; returning partial output\n"


class TestResolveBudget:
    def test_agyt_dt_001_default_when_unset_or_empty(self) -> None:
        """AGYT-DT-001: unset or empty env falls back to the default budget."""
        assert resolve_budget(None) == BUDGET_DEFAULT_SECS
        assert resolve_budget("") == BUDGET_DEFAULT_SECS

    def test_agyt_dt_002_default_and_max_stay_under_bash_tool_cap(self) -> None:
        """AGYT-DT-002: both bounds leave headroom under the Bash tool's 600 s cap."""
        assert BUDGET_DEFAULT_SECS == 480
        assert BUDGET_MAX_SECS == 570

    @pytest.mark.parametrize("raw", ["1", "480", "570"])
    def test_agyt_dt_003_accepts_in_range(self, raw: str) -> None:
        """AGYT-DT-003: integers 1..570 are accepted as-is."""
        assert resolve_budget(raw) == int(raw)

    @pytest.mark.parametrize(
        "raw", ["0", "571", "600", "-5", "+5", "4.5", "abc", " 480", "99999999999999999999"]
    )
    def test_agyt_dt_004_rejects_out_of_range_or_non_digit(self, raw: str) -> None:
        """AGYT-DT-004: anything but plain digits within 1..570 is rejected."""
        with pytest.raises(ValueError, match="AGY_PRINT_TIMEOUT_SECS"):
            resolve_budget(raw)


class TestDetectPrintTimeout:
    def test_agyt_dt_005_marker_is_a_timeout(self) -> None:
        """AGYT-DT-005: the stderr marker alone is a timeout, even well within budget."""
        reason = detect_print_timeout(MARKER_STDERR, elapsed_secs=5, budget_secs=480)
        assert reason is not None and "print timeout" in reason

    def test_agyt_dt_006_elapsed_over_budget_is_a_suspected_timeout(self) -> None:
        """AGYT-DT-006: no marker but elapsed > budget is reported as a suspected timeout."""
        reason = detect_print_timeout("", elapsed_secs=481, budget_secs=480)
        assert reason is not None and "疑似" in reason

    def test_agyt_dt_007_elapsed_equal_to_budget_is_not_a_timeout(self) -> None:
        """AGYT-DT-007: elapsed == budget is not a timeout (SECONDS rounds; strict >)."""
        assert detect_print_timeout("", elapsed_secs=480, budget_secs=480) is None

    def test_agyt_dt_008_unrelated_stderr_is_not_a_timeout(self) -> None:
        """AGYT-DT-008: other stderr chatter within budget does not trip detection."""
        assert detect_print_timeout("some warning\n", elapsed_secs=10, budget_secs=480) is None


class TestQuarantinePartial:
    def test_agyt_dt_009_moves_to_partial_name_with_0600(self, tmp_path: Path) -> None:
        """AGYT-DT-009: the raw output moves aside, content intact, mode 0600."""
        raw = tmp_path / "gemini-r2.md"
        raw.write_text("## Cross-review verdict\ncut", encoding="utf-8")
        raw.chmod(0o644)
        moved = quarantine_partial(raw)
        assert moved == tmp_path / "gemini-r2.timeout-partial.md"
        assert not raw.exists()
        assert moved.read_text(encoding="utf-8") == "## Cross-review verdict\ncut"
        assert moved.stat().st_mode & 0o777 == 0o600

    def test_agyt_dt_010_multi_suffix_keeps_last_suffix(self, tmp_path: Path) -> None:
        """AGYT-DT-010: stage2's gemini-r1.json.tmp keeps its .tmp suffix."""
        raw = tmp_path / "gemini-r1.json.tmp"
        raw.write_text("{", encoding="utf-8")
        assert quarantine_partial(raw) == tmp_path / "gemini-r1.json.timeout-partial.tmp"

    def test_agyt_dt_011_missing_raw_returns_none(self, tmp_path: Path) -> None:
        """AGYT-DT-011: nothing to move is not an error."""
        assert quarantine_partial(tmp_path / "absent.md") is None


class TestLastQuotaLine:
    def test_agyt_dt_012_returns_last_resource_exhausted_line(self) -> None:
        """AGYT-DT-012: the most recent 429 retry line is surfaced (measured agy 1.2.4 shape)."""
        log = (
            "I0916 run.go:389] Run: attempt 1 failed (RESOURCE_EXHAUSTED (code 429): first)\n"
            "I0916 other line\n"
            "I0916 run.go:389] Run: attempt 2 failed (RESOURCE_EXHAUSTED (code 429): second)\n"
        )
        line = last_quota_line(log)
        assert line is not None and "second" in line

    def test_agyt_dt_013_none_without_quota_errors(self) -> None:
        """AGYT-DT-013: a log without 429 lines yields None."""
        assert last_quota_line("I0916 all good\n") is None


class TestMain:
    def test_agyt_st_001_budget_prints_validated_value(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AGYT-ST-001: `budget` prints the resolved value on stdout and exits 0."""
        monkeypatch.setenv("AGY_PRINT_TIMEOUT_SECS", "300")
        assert main(["budget"]) == 0
        assert capsys.readouterr().out.strip() == "300"

    def test_agyt_st_002_budget_invalid_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AGYT-ST-002: an invalid budget exits 2 with [FAIL] and prints nothing on stdout."""
        monkeypatch.setenv("AGY_PRINT_TIMEOUT_SECS", "600")
        assert main(["budget"]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "[FAIL]" in captured.err

    def test_agyt_st_003_check_timeout_quarantines_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AGYT-ST-003: `check` on a timeout exits 1, moves the raw, and names both paths."""
        raw = tmp_path / "gemini-r2.md"
        raw.write_text("partial", encoding="utf-8")
        stderr_log = tmp_path / "gemini-r2.log"
        stderr_log.write_text(MARKER_STDERR, encoding="utf-8")
        agy_log = tmp_path / "gemini-r2.agy.log"
        agy_log.write_text("x failed (RESOURCE_EXHAUSTED (code 429): try later)\n", "utf-8")
        rc = main(
            [
                "check",
                "--raw", str(raw),
                "--stderr-log", str(stderr_log),
                "--agy-log", str(agy_log),
                "--elapsed-secs", "12",
                "--budget-secs", "480",
                "--label", "agy R2",
            ]
        )  # fmt: skip
        assert rc == 1
        err = capsys.readouterr().err
        assert "[FAIL] agy R2" in err
        assert "gemini-r2.timeout-partial.md" in err
        assert "RESOURCE_EXHAUSTED" in err
        assert not raw.exists()

    def test_agyt_st_004_check_no_timeout_exits_0_and_keeps_raw(self, tmp_path: Path) -> None:
        """AGYT-ST-004: `check` without either signal exits 0 and leaves the raw in place."""
        raw = tmp_path / "gemini-r2.md"
        raw.write_text("complete", encoding="utf-8")
        stderr_log = tmp_path / "gemini-r2.log"
        stderr_log.write_text("", encoding="utf-8")
        rc = main(
            [
                "check",
                "--raw", str(raw),
                "--stderr-log", str(stderr_log),
                "--elapsed-secs", "12",
                "--budget-secs", "480",
            ]
        )  # fmt: skip
        assert rc == 0
        assert raw.read_text(encoding="utf-8") == "complete"

    def test_agyt_st_005_check_unreadable_stderr_log_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AGYT-ST-005: a missing stderr log cannot rule out a timeout -> exit 2, not 0."""
        raw = tmp_path / "gemini-r2.md"
        raw.write_text("complete", encoding="utf-8")
        rc = main(
            [
                "check",
                "--raw", str(raw),
                "--stderr-log", str(tmp_path / "absent.log"),
                "--elapsed-secs", "12",
                "--budget-secs", "480",
            ]
        )  # fmt: skip
        assert rc == 2
        assert "[FAIL]" in capsys.readouterr().err

"""Tests for plugins/dev-cycle/skills/pr-cycle-deep/scripts/pre_review_check.py.

Step 1.5 used to spawn three Task agents, each running a single command. This script replaces
them; the tests pin the one property that matters when a subagent's judgement is replaced by
code -- every failure path must surface as exit 2 (stop), never as a quiet "CI OK".
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pre_review_check as prc
import pytest
from pre_review_check import RunResult, classify_amplifier, summarize_checks, summarize_diff


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


class TestSummarizeDiff:
    def test_prck_dt_001_parses_counts(self) -> None:
        """PRCK-DT-001: valid gh pr view JSON becomes a one-line summary."""
        out = json.dumps({"changedFiles": 12, "additions": 97, "deletions": 226})
        assert summarize_diff(RunResult(0, out, "")) == ("12 files, +97/-226 lines", None)

    @pytest.mark.parametrize(
        "result",
        [
            RunResult(1, "", "GraphQL: Could not resolve to a PullRequest"),
            RunResult(None, "", "gh 無法執行"),
            RunResult(0, "not json", ""),
            RunResult(0, json.dumps({"changedFiles": 1}), ""),
        ],
    )
    def test_prck_eg_001_failure_or_garbage_is_an_error(self, result: RunResult) -> None:
        """PRCK-EG-001: non-zero exit, missing binary, or unparsable output all report an error."""
        summary, err = summarize_diff(result)
        assert summary is None
        assert err


class TestSummarizeChecks:
    def test_prck_dt_002_all_pass(self) -> None:
        """PRCK-DT-002: exit 0 with JSON -> bucket counts."""
        out = json.dumps([{"name": "a", "bucket": "pass"}, {"name": "b", "bucket": "pass"}])
        assert summarize_checks(RunResult(0, out, "")) == ("pass 2", None)

    @pytest.mark.parametrize("code", [1, 8])
    def test_prck_dt_003_failing_or_pending_still_parsed(self, code: int) -> None:
        """PRCK-DT-003: gh exits 1 (failed check) / 8 (pending) but stdout is still JSON."""
        out = json.dumps(
            [
                {"name": "lint", "bucket": "fail"},
                {"name": "test", "bucket": "pending"},
                {"name": "ok", "bucket": "pass"},
            ]
        )
        summary, err = summarize_checks(RunResult(code, out, ""))
        assert err is None
        assert summary == "fail 1 / pass 1 / pending 1 (failing: lint)"

    def test_prck_dt_004_no_checks_yet(self) -> None:
        """PRCK-DT-004: gh's 'no checks reported' message is the one non-JSON case let through."""
        res = RunResult(1, "", "no checks reported on the 'feat' branch")
        assert summarize_checks(res) == ("not yet triggered", None)

    @pytest.mark.parametrize(
        "result",
        [
            RunResult(1, "", "HTTP 401: Bad credentials"),
            RunResult(4, "", "To get started with GitHub CLI, please run: gh auth login"),
            RunResult(None, "", "gh 無法執行"),
        ],
    )
    def test_prck_eg_002_tool_error_is_not_ci_ok(self, result: RunResult) -> None:
        """PRCK-EG-002: auth / missing-binary failures must not be reported as a CI state."""
        summary, err = summarize_checks(result)
        assert summary is None
        assert err


class TestClassifyAmplifier:
    @pytest.mark.parametrize(
        ("code", "stdout", "expected"),
        [
            (0, "", 0),
            (1, "[MUST]   TC-001 untraced\n", 1),
            (1, "[SHOULD] TC-002 weak\n", 1),
            (2, "", 2),
            (3, "", 2),
            (None, "", 2),
        ],
    )
    def test_prck_dt_005_exit_code_mapping(
        self, code: int | None, stdout: str, expected: int
    ) -> None:
        """PRCK-DT-005: 0 pass, 1 + finding line = continue, 2 fatal; anything else is fatal."""
        _, mapped = classify_amplifier(RunResult(code, stdout, ""))
        assert mapped == expected

    @pytest.mark.parametrize(
        "stderr",
        ["Traceback (most recent call last):\n  ...\nKeyError: 'x'\n", ""],
    )
    def test_prck_eg_005_exit_1_without_finding_line_is_fatal(self, stderr: str) -> None:
        """PRCK-EG-005: Python exits 1 on any uncaught exception; exit 1 counts as findings only
        when amplifier-verify printed a [MUST]/[SHOULD] line, otherwise it is a crash (exit 2)."""
        _, mapped = classify_amplifier(RunResult(1, "=== Amplifier-Verifier Report", stderr))
        assert mapped == 2


class TestRun:
    def test_prck_eg_006_missing_binary_returns_none(self, tmp_path: Path) -> None:
        """PRCK-EG-006: a command that cannot start becomes returncode=None, not an exception."""
        assert prc.run(["definitely-not-a-binary-xyz"], tmp_path).returncode is None

    def test_prck_eg_007_timeout_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PRCK-EG-007: a hung command (e.g. gh pr checks) becomes returncode=None."""
        monkeypatch.setattr(prc, "_TIMEOUT", 0.2)
        res = prc.run([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path)
        assert res.returncode is None

    def test_prck_eg_008_non_utf8_output_does_not_raise(self, tmp_path: Path) -> None:
        """PRCK-EG-008: non-UTF-8 child output (e.g. Big5 from a testplan) must not raise
        UnicodeDecodeError, which would escape as an uncaught exit 1."""
        res = prc.run(["printf", "\\xa4\\xa4"], tmp_path)
        assert res.returncode == 0


class TestMain:
    def _fake_run(self, responses: dict[str, RunResult]):
        real_run = prc.run

        def fake(cmd: list[str], cwd: Path) -> RunResult:
            if cmd[0] == "git":
                return real_run(cmd, cwd)
            key = "amplifier" if cmd[1].endswith("amplifier-verify.py") else cmd[2]
            return responses[key]

        return fake

    def _ok(self) -> dict[str, RunResult]:
        return {
            "view": RunResult(
                0, json.dumps({"changedFiles": 2, "additions": 5, "deletions": 1}), ""
            ),
            "checks": RunResult(0, json.dumps([{"name": "ci", "bucket": "pass"}]), ""),
            "amplifier": RunResult(0, "no spectra change", ""),
        }

    def test_prck_smk_001_happy_path_writes_report_and_excludes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PRCK-SMK-001: exit 0, compact stdout, report on disk, .pr-review/ git-excluded."""
        repo = _git_repo(tmp_path)
        monkeypatch.setattr(prc, "run", self._fake_run(self._ok()))
        assert prc.main(["--pr", "7", "--repo-root", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "- Diff: 2 files, +5/-1 lines" in out
        assert "- CI: pass 1" in out
        report = repo / ".pr-review" / "pre-review-check.md"
        assert f"REPORT={report.resolve()}" in out or f"REPORT={report}" in out
        assert "no spectra change" in report.read_text(encoding="utf-8")
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert ".pr-review" not in status.stdout

    def test_prck_dt_006_amplifier_findings_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PRCK-DT-006: amplifier exit 1 propagates as 1 (continue, read the report)."""
        repo = _git_repo(tmp_path)
        responses = self._ok()
        responses["amplifier"] = RunResult(1, "[MUST]   TC-001 untraced", "")
        monkeypatch.setattr(prc, "run", self._fake_run(responses))
        assert prc.main(["--pr", "7", "--repo-root", str(repo)]) == 1
        report = (repo / ".pr-review" / "pre-review-check.md").read_text(encoding="utf-8")
        assert "[MUST]   TC-001 untraced" in report

    def test_prck_eg_009_amplifier_fatal_stderr_lands_in_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PRCK-EG-009: amplifier exit 2 propagates as 2 and its stderr (the fatal reason, e.g.
        HEAD mismatch) is preserved in the report -- SKILL.md tells the lead to read it there."""
        repo = _git_repo(tmp_path)
        responses = self._ok()
        responses["amplifier"] = RunResult(2, "amp-stdout-marker", "[FAIL] HEAD mismatch xyz")
        monkeypatch.setattr(prc, "run", self._fake_run(responses))
        assert prc.main(["--pr", "7", "--repo-root", str(repo)]) == 2
        report = (repo / ".pr-review" / "pre-review-check.md").read_text(encoding="utf-8")
        assert "amp-stdout-marker" in report
        assert "[FAIL] HEAD mismatch xyz" in report

    def test_prck_eg_010_unexpected_exception_is_exit_2(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """PRCK-EG-010: any unexpected exception exits 2 with [FAIL], never Python's exit 1
        (which Step 1.5 would read as "findings, continue")."""
        repo = _git_repo(tmp_path)

        def boom(cmd: list[str], cwd: Path) -> RunResult:
            raise ValueError("unexpected")

        monkeypatch.setattr(prc, "run", boom)
        assert prc.main(["--pr", "7", "--repo-root", str(repo)]) == 2
        assert "[FAIL]" in capsys.readouterr().err

    def test_prck_eg_011_report_write_failure_is_exit_2_and_keeps_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """PRCK-EG-011: if the report cannot be written, exit 2 and still print the summary and
        gh errors (there is no report to read them from)."""
        repo = _git_repo(tmp_path)
        (repo / ".pr-review").write_text("not a dir", encoding="utf-8")
        responses = self._ok()
        responses["checks"] = RunResult(1, "", "HTTP 401: Bad credentials")
        monkeypatch.setattr(prc, "run", self._fake_run(responses))
        assert prc.main(["--pr", "7", "--repo-root", str(repo)]) == 2
        err = capsys.readouterr().err
        assert "[FAIL] 無法寫入" in err
        assert "HTTP 401: Bad credentials" in err

    def test_prck_eg_012_exclude_lookup_failure_is_exit_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PRCK-EG-012: `git rev-parse --git-path info/exclude` failing (no git repo) is exit 2."""
        monkeypatch.setattr(prc, "run", self._fake_run(self._ok()))
        assert prc.main(["--pr", "7", "--repo-root", str(tmp_path)]) == 2

    @pytest.mark.parametrize("broken", ["view", "checks"])
    def test_prck_eg_003_gh_failure_overrides_amplifier_ok(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        broken: str,
    ) -> None:
        """PRCK-EG-003: a gh failure is exit 2 even when amplifier passed; [FAIL] on stderr."""
        repo = _git_repo(tmp_path)
        responses = self._ok()
        responses[broken] = RunResult(1, "", "HTTP 401: Bad credentials")
        monkeypatch.setattr(prc, "run", self._fake_run(responses))
        assert prc.main(["--pr", "7", "--repo-root", str(repo)]) == 2
        assert "[FAIL]" in capsys.readouterr().err

    def test_prck_eg_004_existing_exclude_entry_not_duplicated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PRCK-EG-004: re-running keeps exactly one `.pr-review/` line in info/exclude."""
        repo = _git_repo(tmp_path)
        monkeypatch.setattr(prc, "run", self._fake_run(self._ok()))
        prc.main(["--pr", "7", "--repo-root", str(repo)])
        prc.main(["--pr", "7", "--repo-root", str(repo)])
        exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        assert exclude.splitlines().count(".pr-review/") == 1

"""Tests for setup-retro-review-dir.sh.

Two layers, mirroring test_setup_review_dir.py's convention:

  * Static contract tests -- read the script source and assert the invariants whose
    violation would be **silent**: exact-line exclude matching (`-Fx`, not `-F`),
    `--git-path` resolution of info/exclude (not a hand-assembled `--git-dir` path),
    and a `$#` bounds check before dereferencing the `--pr` value. Each of these has a
    known-bad form that still exits 0, so a behavioral test alone would stay green.
  * Behavioral integration tests -- run the script end-to-end against real throwaway
    repositories, including a linked worktree, exercising exclude idempotence, content
    preservation, unwritable-exclude failure, argument-boundary failures, stale-artifact
    detection, and concurrent-run isolation.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SETUP_SCRIPT = SCRIPTS_DIR / "setup-retro-review-dir.sh"

EXCLUDE_LINE = ".runtime/"


def _git_env() -> dict[str, str]:
    """Return an environment with git's repo-selection vars cleared.

    GIT_DIR / GIT_WORK_TREE outrank the process cwd, so an ambient value (git sets
    GIT_DIR while running hooks, and this repo leans on pre-commit) would make every
    `git rev-parse` in the script answer about the *wrong* repository and quietly
    invalidate the whole fixture.
    """
    env = dict(os.environ)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        env.pop(key, None)
    return env


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603
        ["git", *args],
        cwd=repo,
        env=_git_env(),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _make_repo(root: Path) -> Path:
    """Create a throwaway repo with one commit (needed for `git worktree add`)."""
    repo = root / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--quiet")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "--quiet", "-m", "seed")
    return repo


def _run_script(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(SETUP_SCRIPT), *args],
        cwd=cwd,
        env=_git_env(),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _code_lines(src: str) -> str:
    """Strip whole-line comments so lexical contract checks see only executable code.

    The script *documents* why `--git-dir` is wrong, so a naive substring assertion on
    the raw source matches its own rationale comment. A contract check must look at what
    the script does, not at what it explains.
    """
    return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))


def _parse_review_dir(stdout: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith("RETRO_REVIEW_DIR="):
            return Path(line.split("=", 1)[1])
    raise AssertionError(f"no RETRO_REVIEW_DIR line in stdout: {stdout!r}")


# --------------------------------------------------------------------------- #
# Static contract tests
# --------------------------------------------------------------------------- #


class TestScriptContract:
    def test_rrd_ct_001_exclude_match_is_exact_line(self) -> None:
        """RRD-CT-001: exclude lookup uses `grep -qFx`, never a bare `-qF`.

        Substring matching treats an existing `!.runtime/keep` line as "already
        registered", so `.runtime/` is never appended and review artifacts keep
        polluting `git status` -- with exit 0 and no diagnostic. A behavioral test on
        a clean exclude file passes either way, which is why this is asserted on the
        source.
        """
        code = _code_lines(SETUP_SCRIPT.read_text(encoding="utf-8"))
        assert 'grep -qFx "$EXCLUDE_LINE"' in code, (
            "exclude lookup must use -Fx (exact line); -F alone matches substrings"
        )

    def test_rrd_ct_002_exclude_path_via_git_path(self) -> None:
        """RRD-CT-002: info/exclude is located with `--git-path`, not `--git-dir`.

        In a linked worktree `--git-dir` returns the per-worktree admin directory while
        git reads exclude from the common dir, so a hand-assembled path is written to a
        file git never consults -- silently ineffective (PR #203).
        """
        code = _code_lines(SETUP_SCRIPT.read_text(encoding="utf-8"))
        assert "git rev-parse --git-path info/exclude" in code, (
            "must resolve info/exclude via --git-path"
        )
        assert "--git-dir" not in code, "must not hand-assemble the exclude path from --git-dir"

    def test_rrd_ct_003_pr_value_bounds_checked_before_deref(self) -> None:
        """RRD-CT-003: `--pr` checks `$#` before dereferencing its value.

        Under `set -u`, `PR_NUMBER="$2"` with no value supplied aborts with an
        `unbound variable` interpreter stacktrace instead of a clean [FAIL] naming the
        fix.
        """
        code = _code_lines(SETUP_SCRIPT.read_text(encoding="utf-8"))
        assert '[ "$#" -lt 2 ]' in code, "--pr must bounds-check $# before dereferencing $2"

    def test_rrd_ct_004_exclude_is_appended_never_truncated(self) -> None:
        """RRD-CT-004: exclude is only ever appended to.

        info/exclude is shared git metadata across every worktree; a single `>`
        redirect would destroy another worktree's entries.
        """
        code = _code_lines(SETUP_SCRIPT.read_text(encoding="utf-8"))
        assert '>> "$EXCLUDE_FILE"' in code, "exclude write must append"
        assert '> "$EXCLUDE_FILE"' not in code.replace('>> "$EXCLUDE_FILE"', ""), (
            "exclude must never be truncated with a single > redirect"
        )


# --------------------------------------------------------------------------- #
# Behavioral integration tests
# --------------------------------------------------------------------------- #


class TestExcludeRegistration:
    def test_rrd_dt_001_appends_exact_line(self, tmp_path: Path) -> None:
        """RRD-DT-001: the exclude entry is appended as its own exact line."""
        repo = _make_repo(tmp_path)
        result = _run_script(repo, "--pr", "123")
        assert result.returncode == 0, result.stderr
        exclude = repo / ".git" / "info" / "exclude"
        lines = exclude.read_text(encoding="utf-8").splitlines()
        assert EXCLUDE_LINE in lines, f"exclude lines were {lines!r}"

    def test_rrd_dt_002_second_run_does_not_duplicate(self, tmp_path: Path) -> None:
        """RRD-DT-002: running twice leaves exactly one exclude entry."""
        repo = _make_repo(tmp_path)
        assert _run_script(repo, "--pr", "123").returncode == 0
        assert _run_script(repo, "--pr", "123").returncode == 0
        exclude = repo / ".git" / "info" / "exclude"
        lines = exclude.read_text(encoding="utf-8").splitlines()
        assert lines.count(EXCLUDE_LINE) == 1, f"duplicated entry: {lines!r}"

    def test_rrd_dt_003_linked_worktree_writes_common_exclude(self, tmp_path: Path) -> None:
        """RRD-DT-003: from a linked worktree, the artifact dir is worktree-local but
        the exclude entry lands in the *common* dir git actually reads.
        """
        repo = _make_repo(tmp_path)
        wt = tmp_path / "wt"
        _run_git(repo, "worktree", "add", "--quiet", "-b", "feat", str(wt))

        result = _run_script(wt, "--pr", "77")
        assert result.returncode == 0, result.stderr

        review_dir = _parse_review_dir(result.stdout)
        assert str(review_dir).startswith(str(wt.resolve())) or str(review_dir).startswith(
            str(wt)
        ), f"artifact dir {review_dir} should live inside the worktree {wt}"

        common_exclude = repo / ".git" / "info" / "exclude"
        assert EXCLUDE_LINE in common_exclude.read_text(encoding="utf-8").splitlines(), (
            "exclude entry must be written to the common dir git reads"
        )
        per_worktree_exclude = repo / ".git" / "worktrees" / "wt" / "info" / "exclude"
        assert not per_worktree_exclude.exists(), (
            "must not write to the per-worktree admin path git ignores"
        )

    def test_rrd_dt_004_preserves_existing_exclude_content(self, tmp_path: Path) -> None:
        """RRD-DT-004: pre-existing exclude content survives registration."""
        repo = _make_repo(tmp_path)
        exclude = repo / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("pre-existing-entry/\n!.runtime/keep\n", encoding="utf-8")

        assert _run_script(repo, "--pr", "123").returncode == 0

        lines = exclude.read_text(encoding="utf-8").splitlines()
        assert "pre-existing-entry/" in lines, "existing content was lost"
        assert "!.runtime/keep" in lines, "existing negation was lost"
        # The `!.runtime/keep` line contains `.runtime/` as a substring: a `-F`
        # (non-exact) lookup would treat it as already-registered and skip the append.
        assert EXCLUDE_LINE in lines, "substring collision must not suppress the exact-line append"

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permission bits",
    )
    def test_rrd_dt_014_unwritable_artifact_root_fails_with_the_right_message(
        self, tmp_path: Path
    ) -> None:
        """RRD-DT-014 (pr-test-analyzer Important regression): when `.runtime/` itself is
        unwritable, `mkdir -p "$PR_DIR"` fails before any PR subdirectory exists, and the
        script must report THAT failure -- not let the error surface later inside
        `mktemp -d` with a message that names the wrong cause.

        pr-test-analyzer proved by mutation that swallowing this specific `mkdir -p`
        failure (`... || true`) still leaves exit 1 (the later `mktemp -d` step fails on
        the still-missing directory), so a bare exit-code check does not catch a mutation
        that only degrades the diagnostic. This test pins the message, not just the code.
        """
        repo = _make_repo(tmp_path)
        runtime_root = repo / ".runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        runtime_root.chmod(0o555)
        try:
            result = _run_script(repo, "--pr", "123")
        finally:
            runtime_root.chmod(0o755)
        assert result.returncode == 1, result.stderr
        assert "無法建立產物目錄" in result.stderr, (
            f"must name the actual failure, not a downstream one: {result.stderr!r}"
        )
        assert "RETRO_REVIEW_DIR=" not in result.stdout

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permission bits",
    )
    def test_rrd_dt_005_unwritable_exclude_fails_loud(self, tmp_path: Path) -> None:
        """RRD-DT-005: an unwritable exclude file is an explicit [FAIL], not a silent
        continue -- otherwise artifacts pollute `git status` with no diagnostic.
        """
        repo = _make_repo(tmp_path)
        exclude = repo / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("other/\n", encoding="utf-8")
        exclude.chmod(0o444)
        try:
            result = _run_script(repo, "--pr", "123")
        finally:
            exclude.chmod(0o644)
        assert result.returncode == 1, f"expected exit 1, got {result.returncode}"
        assert "[FAIL]" in result.stderr
        assert "RETRO_REVIEW_DIR=" not in result.stdout, (
            "must not emit an artifact dir when registration failed"
        )


class TestArgumentBoundaries:
    def test_rrd_dt_006_missing_pr_flag_fails_cleanly(self, tmp_path: Path) -> None:
        """RRD-DT-006: no arguments at all -> clean [FAIL], exit 2."""
        repo = _make_repo(tmp_path)
        result = _run_script(repo)
        assert result.returncode == 2, result.stderr
        assert "[FAIL]" in result.stderr
        assert "unbound variable" not in result.stderr

    def test_rrd_dt_007_missing_pr_value_fails_cleanly(self, tmp_path: Path) -> None:
        """RRD-DT-007: `--pr` with no value -> clean [FAIL], not a `set -u` stacktrace.

        This is the case the `$#` bounds check exists for; without it bash aborts with
        `$2: unbound variable` and the operator gets no actionable message.
        """
        repo = _make_repo(tmp_path)
        result = _run_script(repo, "--pr")
        assert result.returncode == 2, result.stderr
        assert "[FAIL]" in result.stderr
        assert "unbound variable" not in result.stderr

    def test_rrd_dt_008_non_numeric_pr_rejected(self, tmp_path: Path) -> None:
        """RRD-DT-008: a non-numeric PR value is rejected rather than used as a path
        component (it becomes a directory name).
        """
        repo = _make_repo(tmp_path)
        result = _run_script(repo, "--pr", "../escape")
        assert result.returncode == 2, result.stderr
        assert "[FAIL]" in result.stderr

    def test_rrd_dt_009_unknown_argument_rejected(self, tmp_path: Path) -> None:
        """RRD-DT-009: an unknown flag fails loudly instead of being ignored."""
        repo = _make_repo(tmp_path)
        result = _run_script(repo, "--nope", "x")
        assert result.returncode == 2, result.stderr
        assert "[FAIL]" in result.stderr


class TestRunIsolation:
    def test_rrd_dt_010_each_run_gets_a_distinct_directory(self, tmp_path: Path) -> None:
        """RRD-DT-010: two runs for the same PR return different directories, so a
        concurrent run cannot overwrite another's artifacts.
        """
        repo = _make_repo(tmp_path)
        first = _run_script(repo, "--pr", "123")
        second = _run_script(repo, "--pr", "123")
        assert first.returncode == 0 and second.returncode == 0
        dir_one = _parse_review_dir(first.stdout)
        dir_two = _parse_review_dir(second.stdout)
        assert dir_one != dir_two, "runs must not share an artifact directory"
        assert dir_one.is_dir() and dir_two.is_dir()

    def test_rrd_dt_011_stale_artifact_is_warned_not_reused(self, tmp_path: Path) -> None:
        """RRD-DT-011: a prior run's artifacts trigger a [WARN] and the new run gets a
        fresh directory, so earlier output is never read as belonging to this run.
        """
        repo = _make_repo(tmp_path)
        first = _run_script(repo, "--pr", "123")
        assert first.returncode == 0
        stale = _parse_review_dir(first.stdout) / "draft-m1.md"
        stale.write_text("stale draft\n", encoding="utf-8")

        second = _run_script(repo, "--pr", "123")
        assert second.returncode == 0, second.stderr
        assert "[WARN]" in second.stderr, "prior artifacts must be surfaced"
        fresh = _parse_review_dir(second.stdout)
        assert not (fresh / "draft-m1.md").exists(), (
            "the new run directory must not contain the earlier run's artifacts"
        )

    def test_rrd_dt_012_first_run_emits_no_stale_warning(self, tmp_path: Path) -> None:
        """RRD-DT-012: negative control for RRD-DT-011 -- a first run must NOT warn.

        Without this, a script that unconditionally printed [WARN] would pass
        RRD-DT-011 while training the operator to ignore the warning.
        """
        repo = _make_repo(tmp_path)
        result = _run_script(repo, "--pr", "123")
        assert result.returncode == 0, result.stderr
        assert "[WARN]" not in result.stderr, "a first run has no prior artifacts to warn about"

    def test_rrd_dt_013_artifact_dir_is_under_runtime_retro_review(self, tmp_path: Path) -> None:
        """RRD-DT-013: the artifact dir sits under the path the exclude entry covers.

        If the two ever drift apart, exclude registration succeeds while `git status`
        still shows the artifacts -- green check, wrong thing checked.
        """
        repo = _make_repo(tmp_path)
        result = _run_script(repo, "--pr", "456")
        assert result.returncode == 0, result.stderr
        review_dir = _parse_review_dir(result.stdout)
        assert ".runtime/retro-review/pr-456/" in str(review_dir).replace(os.sep, "/"), (
            f"artifact dir {review_dir} is not under the excluded .runtime/ path"
        )

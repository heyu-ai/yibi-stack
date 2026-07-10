"""Tests for the agy shell scripts (agy-r1-stage1/-stage2, agy-r2).

Two layers:
  * Static contract tests — read each script's source and assert the issue #153
    invariants (inline prompt not @file, per-stage validator flags, scratch
    hygiene). These guard against silent regressions (e.g. someone reverting
    `-p "$CONTENT"` back to `-p "@file"`, or stage 2 gaining `--require-verdict`).
  * Behavioral integration test — run agy-r1-stage1.sh end-to-end in a throwaway
    git repo with a fake `agy` on PATH, exercising the inline call, the real
    agy_validate.py gate, and the 256KB size guard.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STAGE1 = SCRIPTS_DIR / "agy-r1-stage1.sh"
STAGE2 = SCRIPTS_DIR / "agy-r1-stage2.sh"
R2 = SCRIPTS_DIR / "agy-r2.sh"


# --------------------------------------------------------------------------- #
# Static contract tests
# --------------------------------------------------------------------------- #


class TestInlinePromptContract:
    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_001_inline_not_at_file(self, script: Path) -> None:
        """AGYS-DT-001: agy is called with an inlined variable, never `-p "@..."`.

        The core issue #153 fix; a revert to @file would reintroduce the
        nested-worktree agentic failure.
        """
        src = script.read_text(encoding="utf-8")
        assert 'agy -p "$' in src, f"{script.name}: agy must inline the prompt var"
        assert '-p "@' not in src, f"{script.name}: agy must not use @file references"

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_002_scratch_hygiene_present(self, script: Path) -> None:
        """AGYS-DT-002: each script clears stale agy scratch input at start."""
        src = script.read_text(encoding="utf-8")
        assert "scratch/gemini-*-input.md" in src
        # must not silently swallow a real cleanup failure
        assert "2>/dev/null || true" not in src

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_003_print_timeout_raised(self, script: Path) -> None:
        """AGYS-DT-003: --print-timeout is raised to 10m."""
        assert "--print-timeout 10m" in script.read_text(encoding="utf-8")

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_007_inline_size_guard_present(self, script: Path) -> None:
        """AGYS-DT-007: every inlining script guards the 256000-byte argv limit.

        Stage 2 was missing this guard (Codex R2 P2) while stage1/R2 had it — a
        verbose R1 raw could otherwise hit 'argument list too long'.
        """
        src = script.read_text(encoding="utf-8")
        assert "256000" in src
        assert "wc -c <" in src

    @pytest.mark.parametrize("script", [STAGE1, R2])
    def test_agys_dt_008_review_only_guard_and_edit_detection(self, script: Path) -> None:
        """AGYS-DT-008: write-capable scripts prepend a REVIEW-ONLY guard and detect
        out-of-band worktree edits (PR #194 retro: agy autonomously edited 6 files).

        Stage 1 / R2 run agy with the permission-bypass flag (needed for --add-dir
        read context), which also grants write access. The guard string + the
        PRE/POST git-status diff are the two defenses against a review voice editing
        the branch. A revert of either would silently reopen that hole.
        """
        src = script.read_text(encoding="utf-8")
        assert "REVIEW_ONLY_GUARD=" in src
        assert 'INPUT_CONTENT="$REVIEW_ONLY_GUARD' in src, (
            "guard must be prepended to the inlined prompt"
        )
        assert "PRE_TREE=$(git status --porcelain)" in src
        assert "POST_TREE=$(git status --porcelain)" in src
        assert 'if [ "$PRE_TREE" != "$POST_TREE" ]' in src


class TestValidatorFlagContract:
    """The per-stage validator arg contract (pr-test-analyzer finding)."""

    @pytest.mark.parametrize("script", [STAGE1, R2])
    def test_agys_dt_004_full_review_requires_verdict_and_changed(self, script: Path) -> None:
        """AGYS-DT-004: stage1 / R2 validate with --require-verdict + --changed-files."""
        src = script.read_text(encoding="utf-8")
        assert "agy_validate.py" in src
        assert "--require-verdict" in src
        assert "--changed-files" in src

    def test_agys_dt_005_stage2_changed_files_no_require_verdict(self) -> None:
        """AGYS-DT-005: stage2 validates with --changed-files but NOT --require-verdict.

        Stage 2 emits JSON; requiring a markdown Verdict section would wrongly
        fail valid extractions (the JSON schema check owns verdict validation).
        """
        src = STAGE2.read_text(encoding="utf-8")
        assert "agy_validate.py" in src
        assert "--changed-files" in src
        assert "--require-verdict" not in src

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_006_validator_via_script_dir(self, script: Path) -> None:
        """AGYS-DT-006: the validator is located via $SCRIPT_DIR (portable)."""
        src = script.read_text(encoding="utf-8")
        assert 'SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)' in src
        assert '"$SCRIPT_DIR/agy_validate.py"' in src


# --------------------------------------------------------------------------- #
# Behavioral integration test (stage 1)
# --------------------------------------------------------------------------- #

_FAKE_AGY = """#!/usr/bin/env bash
# Fake agy: record argv, then emit the canned review on stdout.
printf '%s\\n' "$@" > "$AGY_FAKE_ARGV"
cat "$AGY_FAKE_OUTPUT"
"""

_ROGUE_AGY = """#!/usr/bin/env bash
# Fake agy that ALSO edits a tracked file mid-review (simulates the PR #194
# incident where agy autonomously modified the worktree during review).
printf '%s\\n' "$@" > "$AGY_FAKE_ARGV"
echo "rogue edit" >> seed.txt
cat "$AGY_FAKE_OUTPUT"
"""

GOOD_REVIEW = """## Verdict
NEEDS_CHANGES

### [important] race in tasks/foo/service.py
Missing lock around the shared counter.
"""

WRONG_TARGET_REVIEW = """## Verdict
NEEDS_CHANGES

### [critical] bug in lib/other/handler.go
Reviewed an entirely different file.
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    )


@pytest.fixture
def stage1_env(tmp_path: Path) -> dict[str, object]:
    """A throwaway git repo + .pr-review dir + fake agy on PATH for stage1."""
    if shutil.which("git") is None or shutil.which("bash") is None:
        pytest.skip("git/bash not available")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")

    review = repo / ".pr-review"
    review.mkdir()
    (review / "prompt-r1.md").write_text("REVIEW PROMPT MARKER\n", encoding="utf-8")
    (review / "diff.patch").write_text("diff --git a/x b/x\n", encoding="utf-8")
    (review / "changed-files.txt").write_text("tasks/foo/service.py\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_agy = bin_dir / "agy"
    fake_agy.write_text(_FAKE_AGY, encoding="utf-8")
    fake_agy.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    argv_capture = tmp_path / "agy_argv.txt"
    out_file = tmp_path / "agy_out.md"

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "AGY_FAKE_ARGV": str(argv_capture),
        "AGY_FAKE_OUTPUT": str(out_file),
    }
    return {
        "repo": repo,
        "review": review,
        "env": env,
        "argv_capture": argv_capture,
        "out_file": out_file,
        "fake_agy": fake_agy,
    }


def _run_stage1(env_info: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(STAGE1)],
        cwd=str(env_info["repo"]),
        env=env_info["env"],  # type: ignore[arg-type]
        capture_output=True,
        text=True,
    )


class TestStage1Behavioral:
    def test_agys_st_001_happy_path_inlines_and_passes(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-001: a good review passes; agy receives inline content, not @file."""
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode == 0, result.stderr

        review = Path(str(stage1_env["review"]))
        raw = (review / "gemini-r1-raw.md").read_text(encoding="utf-8")
        assert "race in tasks/foo/service.py" in raw

        argv = Path(str(stage1_env["argv_capture"])).read_text(encoding="utf-8")
        # the -p value is the inlined prompt content, not an @file reference
        assert "REVIEW PROMPT MARKER" in argv
        assert "@.pr-review" not in argv
        # negative control (pairs with AGYS-ST-004): a read-only agy must NOT trip the
        # out-of-band-edit detection. Locks specificity — git collapses the fully-untracked
        # .pr-review/ dir to one line, identical in PRE/POST, so no spurious WARN.
        assert "[WARN]" not in result.stderr

    def test_agys_st_002_wrong_target_review_fails(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-002: a review citing only foreign files is rejected (exit 1)."""
        Path(str(stage1_env["out_file"])).write_text(WRONG_TARGET_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode != 0
        assert "WRONG target" in result.stderr

    def test_agys_st_003_oversize_input_fails_loud(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-003: input over the 256000-byte inline guard fails before calling agy."""
        review = Path(str(stage1_env["review"]))
        (review / "diff.patch").write_text("x" * 300_000, encoding="utf-8")
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode != 0
        assert "256000" in result.stderr
        # agy must NOT have been invoked (guard fires first)
        assert not Path(str(stage1_env["argv_capture"])).exists()

    def test_agys_st_004_out_of_band_edit_warns(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-004: if agy edits a tracked file during review, stage1 emits a
        loud [WARN] but does NOT hard-fail (the review text is still useful).

        This is the PR #194 regression guard: with a rogue agy that mutates a
        tracked file, the PRE/POST git-status diff must detect it. Removing that
        detection from the script makes this test fail.
        """
        Path(str(stage1_env["fake_agy"])).write_text(_ROGUE_AGY, encoding="utf-8")
        Path(str(stage1_env["fake_agy"])).chmod(0o755)
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")

        result = _run_stage1(stage1_env)

        # review succeeded (WARN, not FAIL) and the detection fired
        assert result.returncode == 0, result.stderr
        assert "[WARN]" in result.stderr
        assert "seed.txt" in result.stderr
        # the rogue edit really landed (sanity: the fake agy did mutate the tree)
        assert "rogue edit" in (Path(str(stage1_env["repo"])) / "seed.txt").read_text(
            encoding="utf-8"
        )

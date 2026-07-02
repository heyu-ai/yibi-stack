"""Tests for setup-review-dir.sh's base-branch resolution (and its twin block in
codex-r1-stage1.sh).

Two layers, mirroring test_agy_scripts.py's convention:
  * Static contract tests -- read each script's source and assert the PR #175
    invariants (no bare `rev-parse --verify` on the caller-supplied branch, "--"
    end-of-options separator before the ref, an explicit empty-branch guard).
    These guard against silent regressions of the exact bugs PR #175 fixed.
  * Behavioral integration tests -- run setup-review-dir.sh end-to-end against a
    real throwaway origin+clone pair, exercising: a stale local base branch (the
    PR #22 mob-review bug this file's whole fetch+FETCH_HEAD approach exists to
    fix), a nonexistent branch, an empty branch, and an argument-injection attempt.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SETUP_SCRIPT = SCRIPTS_DIR / "setup-review-dir.sh"
CODEX_STAGE1 = SCRIPTS_DIR / "codex-r1-stage1.sh"

# Both scripts share the identical fetch+FETCH_HEAD base-resolution block by design
# (see the "deliberate twin" comment in each) -- contract tests apply to both.
FETCH_TWINS = [SETUP_SCRIPT, CODEX_STAGE1]


# --------------------------------------------------------------------------- #
# Static contract tests
# --------------------------------------------------------------------------- #


class TestBaseResolutionContract:
    @pytest.mark.parametrize("script", FETCH_TWINS)
    def test_srd_dt_001_no_bare_rev_parse_verify_on_base_branch(self, script: Path) -> None:
        """SRD-DT-001: the caller-supplied branch is never validated with a bare
        `git rev-parse --verify "$BASE_BRANCH"` -- that only checks local-ref
        existence, not freshness vs origin, which was PR #22's stale-diff bug.
        """
        src = script.read_text(encoding="utf-8")
        assert 'rev-parse --verify "$BASE_BRANCH"' not in src, (
            f"{script.name}: must not re-introduce local-ref-only validation of BASE_BRANCH"
        )

    @pytest.mark.parametrize("script", FETCH_TWINS)
    def test_srd_dt_002_fetch_uses_end_of_options_separator(self, script: Path) -> None:
        """SRD-DT-002: `git fetch` must terminate options with "--" before the
        caller-derived ref, or a branch name starting with "-" is parsed as a git
        flag (verified command-injection risk, e.g. --upload-pack=<cmd>).
        """
        src = script.read_text(encoding="utf-8")
        assert 'git fetch origin --quiet -- "$FETCH_BRANCH"' in src, (
            f"{script.name}: git fetch must use -- before $FETCH_BRANCH"
        )

    @pytest.mark.parametrize("script", FETCH_TWINS)
    def test_srd_dt_003_empty_fetch_branch_guarded(self, script: Path) -> None:
        """SRD-DT-003: an empty FETCH_BRANCH (e.g. BASE_BRANCH="origin/") must be
        rejected before `git fetch` -- otherwise `git fetch origin ""` silently
        falls back to the remote's default branch instead of failing.
        """
        src = script.read_text(encoding="utf-8")
        assert '[ -z "$FETCH_BRANCH" ]' in src, f"{script.name}: must guard empty FETCH_BRANCH"

    @pytest.mark.parametrize("script", FETCH_TWINS)
    def test_srd_dt_004_fetch_failure_message_names_origin_constraint(self, script: Path) -> None:
        """SRD-DT-004: the fetch-failure message must name the actual new
        constraint (branch must exist on origin), not just "check your network" --
        a valid local-only unpushed branch now fails here by design.
        """
        src = script.read_text(encoding="utf-8")
        assert "已存在於 origin" in src, f"{script.name}: fetch-failure message must name the origin constraint"


# --------------------------------------------------------------------------- #
# Behavioral integration tests (setup-review-dir.sh)
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", **(env or {})},
    )


@pytest.fixture
def origin_and_clone(tmp_path: Path) -> dict[str, Path]:
    """A bare `origin` repo plus a `repo` clone, both on `main`, seeded with one commit."""
    if not (SCRIPTS_DIR / "setup-review-dir.sh").exists():
        pytest.skip("setup-review-dir.sh not found")

    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare", "-b", "main")

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-qm", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "main")

    repo = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(origin), str(repo))
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feature commit")

    return {"origin": origin, "repo": repo, "seed": seed}


def _run_setup(repo: Path, base_branch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(SETUP_SCRIPT), base_branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )


class TestSetupReviewDirBehavioral:
    def test_srd_st_001_stale_local_base_uses_origin_tip_not_local(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        """SRD-ST-001: local `main` is behind `origin/main` (another commit landed
        on origin after `repo` was cloned, without `repo` re-fetching). The diff
        base must be origin's tip, not the stale local ref -- the PR #22 bug.
        """
        origin, repo, seed = origin_and_clone["origin"], origin_and_clone["repo"], origin_and_clone["seed"]

        # Land a new commit on origin's main via the seed clone, simulating a
        # merge that happened elsewhere -- `repo`'s local `main` never sees it.
        (seed / "upstream-change.txt").write_text("landed on origin after repo cloned\n", encoding="utf-8")
        _git(seed, "add", ".")
        _git(seed, "commit", "-qm", "unrelated upstream commit")
        _git(seed, "push", "-q", "origin", "main")

        result = _run_setup(repo, "main")
        assert result.returncode == 0, result.stderr

        origin_main_sha = _git(seed, "rev-parse", "main").stdout.strip()
        local_main_sha = _git(repo, "rev-parse", "main").stdout.strip()
        assert origin_main_sha != local_main_sha, "test setup invariant: local main must be stale"

        changed = (repo / ".pr-review" / "changed-files.txt").read_text(encoding="utf-8")
        assert "feature.txt" in changed
        assert "upstream-change.txt" not in changed, (
            "diff must be against origin/main's tip, not the stale local main -- "
            "an upstream-only file leaking in means the script diffed against the wrong base"
        )

    def test_srd_st_002_nonexistent_branch_fails_loud(self, origin_and_clone: dict[str, Path]) -> None:
        """SRD-ST-002: a branch that doesn't exist on origin fails with [FAIL], not
        a silently-wrong diff.
        """
        repo = origin_and_clone["repo"]
        result = _run_setup(repo, "does-not-exist")
        assert result.returncode != 0
        assert "[FAIL]" in result.stderr
        assert not (repo / ".pr-review" / "diff.patch").exists()

    def test_srd_st_003_empty_branch_after_origin_strip_fails_loud(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        """SRD-ST-003: `BASE_BRANCH="origin/"` strips to an empty FETCH_BRANCH and
        must fail loud, not silently fetch the remote's default branch.
        """
        repo = origin_and_clone["repo"]
        result = _run_setup(repo, "origin/")
        assert result.returncode != 0
        assert "[FAIL]" in result.stderr
        assert "空字串" in result.stderr

    def test_srd_st_004_dash_prefixed_branch_does_not_execute_as_flag(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        """SRD-ST-004: a branch name starting with "-" must not be parsed as a git
        option (argument-injection regression guard). `--upload-pack=<cmd>` in
        particular would otherwise get exec'd as the remote upload-pack program.
        """
        repo = origin_and_clone["repo"]
        result = _run_setup(repo, "--upload-pack=touch_pwned_sentinel")
        assert result.returncode != 0
        assert "[FAIL]" in result.stderr
        # Must fail as an unresolvable ref, never as an attempt to run the sentinel command.
        assert "touch_pwned_sentinel: command not found" not in result.stderr
        assert not (repo / "touch_pwned_sentinel").exists()

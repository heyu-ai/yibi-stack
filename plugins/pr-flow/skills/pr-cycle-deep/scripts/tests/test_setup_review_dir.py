"""Tests for setup-review-dir.sh's base-branch resolution.

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

# codex-r1-stage1.sh no longer does its own fetch (issue #194: it now reviews the shared
# $REVIEW_DIR/diff.patch via codex exec), so only setup-review-dir.sh still carries the
# fetch+FETCH_HEAD base-resolution block these PR #175 contract tests protect.
FETCH_SCRIPTS = [SETUP_SCRIPT]


# --------------------------------------------------------------------------- #
# Static contract tests
# --------------------------------------------------------------------------- #


class TestBaseResolutionContract:
    @pytest.mark.parametrize("script", FETCH_SCRIPTS)
    def test_srd_dt_001_no_bare_rev_parse_verify_on_base_branch(self, script: Path) -> None:
        """SRD-DT-001: the caller-supplied branch is never validated with a bare
        `git rev-parse --verify "$BASE_BRANCH"` -- that only checks local-ref
        existence, not freshness vs origin, which was PR #22's stale-diff bug.
        """
        src = script.read_text(encoding="utf-8")
        assert 'rev-parse --verify "$BASE_BRANCH"' not in src, (
            f"{script.name}: must not re-introduce local-ref-only validation of BASE_BRANCH"
        )

    @pytest.mark.parametrize("script", FETCH_SCRIPTS)
    def test_srd_dt_002_fetch_uses_end_of_options_separator(self, script: Path) -> None:
        """SRD-DT-002: `git fetch` must terminate options with "--" before the
        caller-derived ref, or a branch name starting with "-" is parsed as a git
        flag (verified command-injection risk, e.g. --upload-pack=<cmd>). The remote
        is now selected into $BASE_REMOTE (issue #196), so the invariant is the "--"
        separator, not a hardcoded `origin`.
        """
        src = script.read_text(encoding="utf-8")
        assert 'git fetch "$BASE_REMOTE" --quiet -- "$FETCH_BRANCH"' in src, (
            f"{script.name}: git fetch must use -- before $FETCH_BRANCH via $BASE_REMOTE"
        )

    @pytest.mark.parametrize("script", FETCH_SCRIPTS)
    def test_srd_dt_003_empty_fetch_branch_guarded(self, script: Path) -> None:
        """SRD-DT-003: an empty FETCH_BRANCH (e.g. BASE_BRANCH="origin/") must be
        rejected before `git fetch` -- otherwise `git fetch origin ""` silently
        falls back to the remote's default branch instead of failing.
        """
        src = script.read_text(encoding="utf-8")
        assert '[ -z "$FETCH_BRANCH" ]' in src, f"{script.name}: must guard empty FETCH_BRANCH"

    @pytest.mark.parametrize("script", FETCH_SCRIPTS)
    def test_srd_dt_004_fetch_failure_message_names_remote_constraint(self, script: Path) -> None:
        """SRD-DT-004: the fetch-failure message must name the actual new
        constraint (branch must exist on the selected base remote), not just "check
        your network" -- a valid local-only unpushed branch now fails here by design.
        The remote is $BASE_REMOTE (issue #196), so the message interpolates it.
        """
        src = script.read_text(encoding="utf-8")
        assert "已存在於 ${BASE_REMOTE}" in src, (
            f"{script.name}: fetch-failure message must name the $BASE_REMOTE constraint"
        )

    @pytest.mark.parametrize("script", FETCH_SCRIPTS)
    def test_srd_dt_005_prefers_upstream_remote_when_present(self, script: Path) -> None:
        """SRD-DT-005: base remote resolution must prefer an `upstream` remote over
        `origin` when one exists (issue #196: origin may be a personal fork whose
        default branch lags the real base repo). Guards against a regression to an
        unconditional `git fetch origin`.
        """
        src = script.read_text(encoding="utf-8")
        assert "BASE_REMOTE=origin" in src, f"{script.name}: must default BASE_REMOTE to origin"
        assert "git remote get-url upstream" in src, (
            f"{script.name}: must probe for an upstream remote"
        )
        assert "BASE_REMOTE=upstream" in src, (
            f"{script.name}: must prefer upstream when the probe succeeds"
        )


# --------------------------------------------------------------------------- #
# Behavioral integration tests (setup-review-dir.sh)
# --------------------------------------------------------------------------- #


def _git(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            **(env or {}),
        },
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
    def test_srd_st_001_stale_local_base_uses_origin_tip_not_local(self, tmp_path: Path) -> None:
        """SRD-ST-001: reproduces the actual PR #22 bug shape. `git diff A...B` is
        computed against the merge-base of A and B, not A directly -- so if the
        stale local `main` is simply an ancestor of both origin/main and `feature`,
        using it as the diff base gives the SAME result as using fresh origin/main
        (merge-base is identical either way), and a naive test would pass against
        both a correct and a buggy script. The real bug only surfaces when
        `feature` already contains commits that also landed on origin/main (e.g.
        other PRs merged after `feature` branched, then squash-merged into main
        with new SHAs) while the *local* `main` ref never advanced past those
        commits -- so `merge-base(stale_local_main, feature)` is OLDER than
        `merge-base(fresh_origin_main, feature)`, and diffing against the stale
        ref pulls in those already-landed commits' content as if it were new.

        Reproduce that precisely: build main = A -> B -> C, branch `feature` off
        C (so C is already an ancestor of feature, mirroring "PR branch created
        after other PRs already merged"), then force the *local* `main` branch
        ref (and the local `origin/main` remote-tracking ref, simulating "haven't
        fetched in a while") back to A. A correct script re-fetches origin fresh
        (bypassing both stale local refs) and gets C as the diff base -- excluding
        B and C's content. A script trusting the local ref would diff from A,
        incorrectly including B and C's content alongside feature's own commit.
        """
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
        _git(seed, "commit", "-qm", "A: seed")
        _git(seed, "remote", "add", "origin", str(origin))
        _git(seed, "push", "-q", "origin", "main")
        sha_a = _git(seed, "rev-parse", "main").stdout.strip()

        (seed / "other-pr-1.txt").write_text("landed via another PR\n", encoding="utf-8")
        _git(seed, "add", ".")
        _git(seed, "commit", "-qm", "B: other PR 1")
        (seed / "other-pr-2.txt").write_text("landed via another PR too\n", encoding="utf-8")
        _git(seed, "add", ".")
        _git(seed, "commit", "-qm", "C: other PR 2")
        _git(seed, "push", "-q", "origin", "main")
        sha_c = _git(seed, "rev-parse", "main").stdout.strip()
        assert sha_a != sha_c

        # `repo` clones at C (matches origin exactly), branches `feature` off C --
        # feature's ancestry already includes B and C, like a PR branch created
        # after other PRs merged.
        repo = tmp_path / "repo"
        _git(tmp_path, "clone", "-q", str(origin), str(repo))
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "D: feature commit")

        # Now simulate staleness: force *local* main (and the local origin/main
        # tracking ref, as if `fetch` hasn't run recently) back to A, without
        # touching the origin bare repo itself (still at C).
        _git(repo, "branch", "-f", "main", sha_a)
        _git(repo, "update-ref", "refs/remotes/origin/main", sha_a)
        assert _git(repo, "rev-parse", "main").stdout.strip() == sha_a
        assert _git(repo, "rev-parse", "origin/main").stdout.strip() == sha_a

        result = _run_setup(repo, "main")
        assert result.returncode == 0, result.stderr

        changed = (repo / ".pr-review" / "changed-files.txt").read_text(encoding="utf-8")
        assert "feature.txt" in changed
        assert "other-pr-1.txt" not in changed, (
            "diff must be against origin's fresh tip (C), not the stale local main (A) -- "
            "B/C's content leaking in means the script diffed against the wrong, stale base"
        )
        assert "other-pr-2.txt" not in changed

    def test_srd_st_002_nonexistent_branch_fails_loud(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
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

    def test_srd_st_005_fork_origin_uses_upstream_base_not_stale_fork(self, tmp_path: Path) -> None:
        """SRD-ST-005: reproduces issue #196. When `origin` is a personal fork whose
        `main` lags the real base repo, and an `upstream` remote points at the true
        base repo, the review diff must resolve against upstream's fresh tip -- not
        the fork's stale main, which would balloon the diff with already-landed
        commits' content.

        Build the true base (upstream) main = A -> B -> C. The fork's main is frozen
        at A (forked before B/C landed). The PR branch `feature` is based off C (as a
        real PR would be), plus its own commit D. A script that fetched base from the
        fork `origin` (A) would compute merge-base(A, feature) = A and pull B and C's
        content into the diff; the fix fetches from `upstream` (C) and gets only D.
        """
        upstream = tmp_path / "upstream.git"
        upstream.mkdir()
        _git(upstream, "init", "-q", "--bare", "-b", "main")

        seed = tmp_path / "seed"
        seed.mkdir()
        _git(seed, "init", "-q", "-b", "main")
        _git(seed, "config", "user.email", "t@t")
        _git(seed, "config", "user.name", "t")
        (seed / "README.md").write_text("seed\n", encoding="utf-8")
        _git(seed, "add", ".")
        _git(seed, "commit", "-qm", "A: seed")
        _git(seed, "remote", "add", "upstream", str(upstream))
        _git(seed, "push", "-q", "upstream", "main")
        sha_a = _git(seed, "rev-parse", "main").stdout.strip()

        # The fork (origin) is created off A, before B/C land upstream.
        fork = tmp_path / "fork.git"
        fork.mkdir()
        _git(fork, "init", "-q", "--bare", "-b", "main")
        _git(seed, "remote", "add", "fork", str(fork))
        _git(seed, "push", "-q", "fork", "main")  # fork/main = A (frozen)

        # B and C land on upstream only.
        (seed / "other-pr-1.txt").write_text("landed via another PR\n", encoding="utf-8")
        _git(seed, "add", ".")
        _git(seed, "commit", "-qm", "B: other PR 1")
        (seed / "other-pr-2.txt").write_text("landed via another PR too\n", encoding="utf-8")
        _git(seed, "add", ".")
        _git(seed, "commit", "-qm", "C: other PR 2")
        _git(seed, "push", "-q", "upstream", "main")
        sha_c = _git(seed, "rev-parse", "main").stdout.strip()
        assert sha_a != sha_c

        # Working checkout: origin = fork (stale A), upstream = true base (C).
        # feature branches off C and adds D.
        repo = tmp_path / "repo"
        _git(tmp_path, "clone", "-q", "--origin", "origin", str(fork), str(repo))
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _git(repo, "remote", "add", "upstream", str(upstream))
        _git(repo, "fetch", "-q", "upstream")
        _git(repo, "checkout", "-q", "-b", "feature", sha_c)
        (repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "D: feature commit")

        # Sanity: origin/main is the stale A, upstream/main is the fresh C.
        assert _git(repo, "rev-parse", "origin/main").stdout.strip() == sha_a
        assert _git(repo, "rev-parse", "upstream/main").stdout.strip() == sha_c

        result = _run_setup(repo, "main")
        assert result.returncode == 0, result.stderr

        changed = (repo / ".pr-review" / "changed-files.txt").read_text(encoding="utf-8")
        assert "feature.txt" in changed
        assert "other-pr-1.txt" not in changed, (
            "diff must resolve against upstream's fresh tip (C), not the fork origin's "
            "stale main (A) -- B/C content leaking in is exactly issue #196"
        )
        assert "other-pr-2.txt" not in changed

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

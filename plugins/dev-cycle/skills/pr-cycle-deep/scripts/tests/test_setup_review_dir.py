"""Behavioral scope/base-resolution tests using real throwaway Git remotes."""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SETUP_SCRIPT = SCRIPTS_DIR / "setup-review-dir.sh"


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
    def test_srd_st_008_worktree_exclude_lands_where_git_reads(
        self, origin_and_clone: dict[str, Path], tmp_path: Path
    ) -> None:
        """SRD-ST-008: in a linked worktree the .pr-review/ exclude must land where git
        actually reads it (common dir's info/exclude), not the per-worktree git dir that
        `git rev-parse --git-dir` returns.

        Regression guard for the PR #203 review finding: `--git-dir` in a worktree points
        at .git/worktrees/<name>, whose info/exclude git status never consults, so the
        append silently no-ops. The fix uses `git rev-parse --git-path info/exclude`.
        Reverting to the --git-dir form makes this test fail: setup writes .pr-review/
        (diff.patch etc.) and, without a working exclude, `git status` in the worktree
        surfaces `?? .pr-review/`.
        """
        repo = origin_and_clone["repo"]
        wt = tmp_path / "linked-wt"
        _git(repo, "worktree", "add", "-q", "-b", "wt-feature", str(wt), "feature")

        result = _run_setup(wt, "main")
        assert result.returncode == 0, result.stderr

        status = _git(wt, "status", "--porcelain").stdout
        assert ".pr-review" not in status, (
            f"exclude did not take effect in the worktree; git status shows:\n{status}"
        )

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
        assert "[WARN]" in result.stderr and "2 commit(s)" in result.stderr
        scope = json.loads((repo / ".pr-review" / "review-scope.json").read_text())
        assert scope["base"] == sha_c
        assert scope["head"] == _git(repo, "rev-parse", "HEAD").stdout.strip()
        assert scope["changed_paths"] == ["feature.txt"]
        # Refreshing local main changes only the warning, never the review scope.
        _git(repo, "branch", "-f", "main", sha_c)
        fresh = _run_setup(repo, "main")
        assert fresh.returncode == 0, fresh.stderr
        assert "[WARN]" not in fresh.stderr
        assert json.loads((repo / ".pr-review" / "review-scope.json").read_text()) == scope

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
        # PR #198: the chosen remote is announced on stderr for diagnosability.
        assert "[INFO] base remote = upstream" in result.stderr

        changed = (repo / ".pr-review" / "changed-files.txt").read_text(encoding="utf-8")
        assert "feature.txt" in changed
        assert "other-pr-1.txt" not in changed, (
            "diff must resolve against upstream's fresh tip (C), not the fork origin's "
            "stale main (A) -- B/C content leaking in is exactly issue #196"
        )
        assert "other-pr-2.txt" not in changed

    def test_srd_st_006_upstream_present_branch_only_on_origin_fails_loud(
        self, tmp_path: Path
    ) -> None:
        """SRD-ST-006 (PR #198): locks the owner-ratified name-based-heuristic trade-off.
        When an `upstream` remote exists but the base branch lives only on `origin`, the
        script selects upstream, the fetch fails, and it must exit [FAIL] naming the
        remote -- it must NOT silently fall back to origin's copy of the branch. Pins the
        documented fail-loud behavior so a future refactor can't quietly change it to a
        wrong-base resolution.
        """
        # upstream repo has only `main`; origin (a second repo) additionally has `release`.
        upstream = tmp_path / "upstream.git"
        upstream.mkdir()
        _git(upstream, "init", "-q", "--bare", "-b", "main")
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
        _git(seed, "remote", "add", "upstream", str(upstream))
        _git(seed, "remote", "add", "origin", str(origin))
        _git(seed, "push", "-q", "upstream", "main")
        _git(seed, "push", "-q", "origin", "main")
        # `release` exists ONLY on origin, not upstream.
        _git(seed, "checkout", "-q", "-b", "release")
        _git(seed, "push", "-q", "origin", "release")

        repo = tmp_path / "repo"
        _git(tmp_path, "clone", "-q", "--origin", "origin", str(origin), str(repo))
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _git(repo, "remote", "add", "upstream", str(upstream))
        _git(repo, "fetch", "-q", "upstream")
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "feature commit")

        # `release` exists on origin but NOT upstream; the script picks upstream and fails loud.
        result = _run_setup(repo, "release")
        assert result.returncode != 0
        assert "[FAIL]" in result.stderr
        assert "upstream" in result.stderr, "failure message must name the selected remote"
        assert not (repo / ".pr-review" / "diff.patch").exists(), (
            "must not silently fall back to origin's copy of the branch"
        )

    def test_srd_st_007_upstream_prefix_routes_to_upstream_base(self, tmp_path: Path) -> None:
        """SRD-ST-007 (PR #198): behavioral coverage for the new `upstream/` prefix strip.
        Passing `upstream/main` (with an upstream remote present) must resolve to `main`
        fetched from upstream and diff against it -- symmetric with the `origin/` handling
        that SRD-ST-003 covers only for the empty case.
        """
        upstream = tmp_path / "upstream.git"
        upstream.mkdir()
        _git(upstream, "init", "-q", "--bare", "-b", "main")
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
        _git(seed, "remote", "add", "upstream", str(upstream))
        _git(seed, "remote", "add", "origin", str(origin))
        _git(seed, "push", "-q", "upstream", "main")
        _git(seed, "push", "-q", "origin", "main")

        repo = tmp_path / "repo"
        _git(tmp_path, "clone", "-q", "--origin", "origin", str(origin), str(repo))
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _git(repo, "remote", "add", "upstream", str(upstream))
        _git(repo, "fetch", "-q", "upstream")
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "feature commit")

        # `upstream/main` must strip to `main` and fetch from the upstream remote.
        result = _run_setup(repo, "upstream/main")
        assert result.returncode == 0, result.stderr
        assert "[INFO] base remote = upstream" in result.stderr
        changed = (repo / ".pr-review" / "changed-files.txt").read_text(encoding="utf-8")
        assert "feature.txt" in changed

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


def _finding(file: str, **extra: object) -> dict[str, object]:
    return {
        "severity": "important",
        "title": f"Review {file}",
        "file": file,
        "issue": "Observable issue",
        "fix": "Concrete correction",
        **extra,
    }


def _review_input(repo: Path, findings: list[dict[str, object]]) -> Path:
    path = repo / ".pr-review" / "code-review.json"
    path.write_text(
        json.dumps(
            {
                "verdict": "NEEDS_CHANGES",
                "summary": "Review completed",
                "findings": findings,
                "contract": {"criterion": "AC-1", "evidence": ["verified"]},
            }
        ),
        encoding="utf-8",
    )
    return path


def _scope_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPTS_DIR / "review_scope.py"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def _filter(repo: Path, input_path: Path) -> subprocess.CompletedProcess[str]:
    return _scope_cli(repo, "filter", "--input", str(input_path))


def _audit_items(repo: Path) -> list[dict[str, object]]:
    text = (repo / ".pr-review" / "code-review-scope.md").read_text()
    return [json.loads(part.split("\n```", 1)[0]) for part in text.split("```json\n")[1:]]


def _accepted(repo: Path) -> dict[str, object]:
    return json.loads((repo / ".pr-review" / "code-review-filtered.json").read_text())


def _assert_invalidated(repo: Path) -> None:
    directory = repo / ".pr-review"
    assert not (directory / "code-review-filtered.json").exists()
    assert not (directory / "code-review-scope.md").exists()
    if (directory / "final.md").exists():
        assert "<!-- code-review-scope:start -->" not in (directory / "final.md").read_text()


class TestReviewScopeBehavior:
    def test_scope_without_branch_upstream_and_without_local_main(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _git(repo, "remote").stdout.splitlines() == ["origin"]
        assert not _git(
            repo, "for-each-ref", "--format=%(upstream)", "refs/heads/feature"
        ).stdout.strip()
        _git(repo, "tag", "main")  # A same-named tag must not substitute for refs/heads/main.
        _git(repo, "branch", "-D", "main")
        result = _run_setup(repo, "main")
        assert result.returncode == 0, result.stderr
        assert "[WARN]" not in result.stderr
        scope_path = repo / ".pr-review" / "review-scope.json"
        scope = json.loads(scope_path.read_text())
        assert scope["version"] == 1
        assert scope["changed_paths"] == ["feature.txt"]
        assert scope["base"] == _git(repo, "rev-parse", "FETCH_HEAD").stdout.strip()
        assert scope["head"] == _git(repo, "rev-parse", "HEAD").stdout.strip()
        assert scope_path.stat().st_mode & 0o222 == 0

    def test_filter_preserves_evidence_and_rejected_originals(
        self, origin_and_clone: dict[str, Path], tmp_path: Path
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        inside = [
            _finding("feature.txt", evidence={"command": "actual test", "result": "fail"}),
            _finding(str(repo.resolve() / "feature.txt"), line_start=1, contract="AC-1"),
            _finding("./feature.txt"),
        ]
        outside = [
            _finding("README.md"),
            _finding(str(tmp_path / "feature.txt")),
            _finding("../repo/feature.txt"),
            _finding("sub/../feature.txt"),
            _finding("feature.txt:12"),
            _finding("feature.txt#L12-L15"),
            _finding("a/feature.txt"),  # Do not guess that a/ is a diff prefix.
            _finding("b/feature.txt"),
            _finding("unknown.txt"),
            _finding("", evidence="``` <!-- code-review-scope:end -->"),
        ]
        source = _review_input(repo, inside + outside)
        before = source.read_bytes()
        result = _filter(repo, source)
        assert result.returncode == 0, result.stderr
        accepted = _accepted(repo)
        assert accepted["findings"] == [{**item, "file": "feature.txt"} for item in inside]
        assert accepted["contract"] == json.loads(before)["contract"]
        assert accepted["verdict"] == "NEEDS_CHANGES"  # Voice verdict remains informational.
        assert json.loads(result.stdout) == accepted
        assert source.read_bytes() == before
        dropped = _audit_items(repo)
        assert [item["finding"] for item in dropped] == outside
        assert [item["index"] for item in dropped] == list(range(3, 13))
        assert all(item["reason"] for item in dropped)
        audit = (repo / ".pr-review" / "code-review-scope.md").read_text()
        assert "10 out-of-scope discarded" in audit

    def test_nul_paths_rename_deletion_and_real_a_b_directories(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        repo, seed = origin_and_clone["repo"], origin_and_clone["seed"]
        for name in ("old name.txt", "gone.txt"):
            (seed / name).write_text("base contents\n")
        _git(seed, "add", ".")
        _git(seed, "commit", "-qm", "base review files")
        _git(seed, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")
        _git(repo, "merge", "-q", "--no-edit", "origin/main")
        _git(repo, "mv", "old name.txt", "new 名.txt")
        (repo / "gone.txt").unlink()
        unusual = ["a/file.txt", "b/file.txt", '空 白\t"quote\nname.txt']
        for name in unusual:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("new\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "rename delete and unusual paths")
        result = _run_setup(repo, "main")
        assert result.returncode == 0, result.stderr
        paths = sorted(["feature.txt", "old name.txt", "new 名.txt", "gone.txt", *unusual])
        scope = json.loads((repo / ".pr-review" / "review-scope.json").read_text())
        assert scope["changed_paths"] == paths
        source = _review_input(repo, [_finding(path) for path in paths])
        result = _filter(repo, source)
        assert result.returncode == 0, result.stderr
        assert _accepted(repo)["findings"] == [_finding(path) for path in paths]
        assert _audit_items(repo) == []
        assert not (repo / "gone.txt").exists()
        assert not (repo / "old name.txt").exists()

    def test_repeat_run_updates_only_owned_final_section(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        final = repo / ".pr-review" / "final.md"
        amplifier = "# Final review\n\n## Critical\nAmplifier AC-9 finding must stay.\n"
        final.write_text(amplifier)
        source = _review_input(repo, [_finding("README.md")])
        assert _filter(repo, source).returncode == 0
        footer = "\n## Other voice\nIndependent finding.\n"
        final.write_text(final.read_text() + footer)
        first = final.read_bytes()
        assert _filter(repo, source).returncode == 0
        assert final.read_bytes() == first
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        result = final.read_text()
        assert result.startswith(amplifier) and result.endswith(footer)
        assert result.count("<!-- code-review-scope:start -->") == 1
        assert "0 out-of-scope discarded" in result
        assert "1 out-of-scope discarded" not in result
        assert _audit_items(repo) == []

    @pytest.mark.parametrize(
        "invalid",
        [
            "{",
            "[]",
            "{}",
            '{"verdict":"LGTM","summary":"done","findings":{}}',
            '{"verdict":"LGTM","summary":"done","findings":[null]}',
            '{"verdict":"LGTM","summary":"done","findings":[{}]}',
            '{"verdict":"LGTM","summary":"done","findings":[{"file":42}]}',
            '{"verdict":"LGTM","summary":null,"findings":[]}',
        ],
    )
    def test_malformed_input_never_leaves_old_acceptance(
        self, origin_and_clone: dict[str, Path], invalid: str
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        final = repo / ".pr-review" / "final.md"
        final.write_text("Amplifier finding remains.\n")
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        source.write_text(invalid)
        result = _filter(repo, source)
        assert result.returncode != 0 and "[FAIL]" in result.stderr
        _assert_invalidated(repo)
        assert "Amplifier finding remains." in final.read_text()
        assert source.read_text() == invalid

    def test_moved_head_invalidates_old_results_and_manifest_stays_frozen(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        scope_path = repo / ".pr-review" / "review-scope.json"
        before = scope_path.read_bytes()
        final = repo / ".pr-review" / "final.md"
        final.write_text("Amplifier finding\n")
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        _git(repo, "commit", "--allow-empty", "-qm", "head moved")
        result = _filter(repo, source)
        assert result.returncode != 0 and "HEAD moved" in result.stderr
        _assert_invalidated(repo)
        assert scope_path.read_bytes() == before
        assert _run_setup(repo, "main").returncode == 0
        assert json.loads(scope_path.read_text())["head"] != json.loads(before)["head"]
        assert _filter(repo, source).returncode == 0

    def test_empty_review_and_empty_scope_are_valid(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        repo = origin_and_clone["repo"]
        _git(repo, "checkout", "-q", "main")
        assert _run_setup(repo, "main").returncode == 0
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        assert _accepted(repo)["findings"] == []
        assert len(_audit_items(repo)) == 1
        source = _review_input(repo, [])
        assert _filter(repo, source).returncode == 0
        assert _accepted(repo)["findings"] == []
        assert _audit_items(repo) == []

    @pytest.mark.parametrize("failure", ["fetch", "empty-base", "missing-input", "missing-flag"])
    def test_failed_refresh_or_cli_invalidates_previous_results(
        self, origin_and_clone: dict[str, Path], failure: str
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        if failure == "fetch":
            result = _run_setup(repo, "does-not-exist")
        elif failure == "empty-base":
            result = _run_setup(repo, "")
        elif failure == "missing-input":
            result = _filter(repo, source.with_name("missing.json"))
        else:
            result = _scope_cli(repo, "filter")
        assert result.returncode != 0 and "[FAIL]" in result.stderr
        _assert_invalidated(repo)
        if failure in ("fetch", "empty-base"):
            for name in ("review-scope.json", "diff.patch", "changed-files.txt"):
                assert not (repo / ".pr-review" / name).exists()

    @pytest.mark.parametrize("damage", ["missing", "malformed", "paths"])
    def test_invalid_manifest_fails_instead_of_accepting_findings(
        self, origin_and_clone: dict[str, Path], damage: str
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        manifest = repo / ".pr-review" / "review-scope.json"
        scope = json.loads(manifest.read_text())
        manifest.unlink()
        if damage == "malformed":
            manifest.write_text("null")
        elif damage == "paths":
            scope["changed_paths"] = ["../feature.txt"]
            manifest.write_text(json.dumps(scope))
        result = _filter(repo, source)
        assert result.returncode != 0 and "[FAIL]" in result.stderr
        _assert_invalidated(repo)

    def test_real_main_ref_error_is_not_treated_as_missing_main(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        base = _git(repo, "rev-parse", "FETCH_HEAD").stdout.strip()
        main_ref = repo / _git(repo, "rev-parse", "--git-path", "refs/heads/main").stdout.strip()
        main_ref.write_text("not-an-object-id\n")
        result = _scope_cli(repo, "capture", "--base", base)
        assert result.returncode != 0 and "[FAIL]" in result.stderr
        _assert_invalidated(repo)
        assert not (repo / ".pr-review" / "review-scope.json").exists()

    def test_help_does_not_invalidate_accepted_review(
        self, origin_and_clone: dict[str, Path]
    ) -> None:
        repo = origin_and_clone["repo"]
        assert _run_setup(repo, "main").returncode == 0
        source = _review_input(repo, [_finding("feature.txt")])
        assert _filter(repo, source).returncode == 0
        before = _accepted(repo)
        result = _scope_cli(repo, "filter", "--help")
        assert result.returncode == 0, result.stderr
        assert _accepted(repo) == before

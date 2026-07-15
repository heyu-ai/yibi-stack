"""Tests for protect-tracked-rm.py hook."""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parent.parent / "protect-tracked-rm.py"


def run_hook(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
    )


def _bash(cmd: str, cwd: str | None = None) -> dict:
    payload: dict = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if cwd is not None:
        payload["cwd"] = cwd
    return payload


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def make_repo(tmp_path: Path) -> Path:
    """A real git repo: tracked/ has a committed file, untracked/ does not."""
    repo = tmp_path / "repo"
    (repo / "tracked").mkdir(parents=True)
    (repo / "untracked").mkdir(parents=True)
    (repo / "tracked" / "keep.txt").write_text("committed\n", encoding="utf-8")
    (repo / "untracked" / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "tracked/keep.txt")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


class TestBlocksTrackedDeletion:
    def test_rmhook_dt_001_blocks_rm_rf_on_tracked_dir(self, tmp_path: Path) -> None:
        """RMHOOK-DT-001: rm -rf <dir with tracked files> -> exit 2 + actionable fix.

        The message must hand back a runnable inspection command, not just refuse.
        """
        repo = make_repo(tmp_path)
        r = run_hook(_bash("rm -rf tracked", cwd=str(repo)))
        assert r.returncode == 2
        assert "git -C tracked ls-files" in r.stdout
        assert "git rm -r tracked" in r.stdout

    def test_rmhook_dt_002_names_the_tracked_file(self, tmp_path: Path) -> None:
        """RMHOOK-DT-002: the block message names the tracked file, not just a count.

        A message that only says "N tracked files" leaves the operator unable to
        judge whether the deletion is the intended one.
        """
        repo = make_repo(tmp_path)
        r = run_hook(_bash("rm -rf tracked", cwd=str(repo)))
        assert r.returncode == 2
        assert "keep.txt" in r.stdout

    def test_rmhook_dt_003_blocks_the_gitkeep_incident(self, tmp_path: Path) -> None:
        """RMHOOK-DT-003: a dir whose ONLY tracked file is a clean .gitkeep.

        The PR #214 incident exactly: `git status --porcelain` showed only `??`
        entries because the tracked .gitkeep was unmodified, so the dir looked
        disposable. This is the case the hook exists for.
        """
        repo = make_repo(tmp_path)
        gen = repo / "generated"
        gen.mkdir()
        (gen / ".gitkeep").write_text("", encoding="utf-8")
        _git(repo, "add", "generated/.gitkeep")
        _git(repo, "commit", "-q", "-m", "add placeholder")
        (gen / "a.py").write_text("# untracked\n", encoding="utf-8")
        (gen / "b.py").write_text("# untracked\n", encoding="utf-8")

        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "generated/"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert ".gitkeep" not in status.stdout, "premise: clean .gitkeep is invisible to status"

        r = run_hook(_bash("rm -rf generated", cwd=str(repo)))
        assert r.returncode == 2
        assert ".gitkeep" in r.stdout


class TestAllowsSafeDeletion:
    def test_rmhook_dt_004_allows_untracked_dir(self, tmp_path: Path) -> None:
        """RMHOOK-DT-004: rm -rf <dir with no tracked files> -> exit 0."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -rf untracked", cwd=str(repo))).returncode == 0

    def test_rmhook_dt_005_allows_outside_git_repo(self, tmp_path: Path) -> None:
        """RMHOOK-DT-005: target outside any git repo -> exit 0 (git ls-files fails)."""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "f.txt").write_text("x\n", encoding="utf-8")
        assert run_hook(_bash("rm -rf plain", cwd=str(tmp_path))).returncode == 0

    def test_rmhook_dt_006_allows_nonexistent_target(self, tmp_path: Path) -> None:
        """RMHOOK-DT-006: target does not exist -> exit 0."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -rf ghost", cwd=str(repo))).returncode == 0

    def test_rmhook_dt_007_allows_non_recursive_rm_on_a_dir(self, tmp_path: Path) -> None:
        """RMHOOK-DT-007: non-recursive rm is out of scope (documented limitation).

        The target must be a DIRECTORY holding tracked files, so that the only
        thing standing between this command and a block is the missing recursive
        flag. Using a file target here would pass even with the flag check removed
        (`_tracked_files` short-circuits on `os.path.isdir`), making the test blind
        to the very branch it names.
        """
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm tracked", cwd=str(repo))).returncode == 0

    def test_rmhook_dt_008_ignores_non_bash_tool(self, tmp_path: Path) -> None:
        """RMHOOK-DT-008: non-Bash tool -> exit 0."""
        payload = {"tool_name": "Write", "tool_input": {"command": "rm -rf tracked"}}
        assert run_hook(payload).returncode == 0


class TestRecursiveFlagForms:
    def test_rmhook_ep_001_combined_rf(self, tmp_path: Path) -> None:
        """RMHOOK-EP-001: -rf (combined short flags)."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -rf tracked", cwd=str(repo))).returncode == 2

    def test_rmhook_ep_002_combined_fr_reversed(self, tmp_path: Path) -> None:
        """RMHOOK-EP-002: -fr (order reversed)."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -fr tracked", cwd=str(repo))).returncode == 2

    def test_rmhook_ep_003_capital_R(self, tmp_path: Path) -> None:
        """RMHOOK-EP-003: -R (capital)."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -R tracked", cwd=str(repo))).returncode == 2

    def test_rmhook_ep_004_long_recursive(self, tmp_path: Path) -> None:
        """RMHOOK-EP-004: --recursive (long form)."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm --recursive tracked", cwd=str(repo))).returncode == 2

    def test_rmhook_ep_005_separate_r_and_f(self, tmp_path: Path) -> None:
        """RMHOOK-EP-005: -r -f (separate flags)."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -r -f tracked", cwd=str(repo))).returncode == 2


class TestCommandComposition:
    def test_rmhook_dt_009_blocks_inside_and_chain(self, tmp_path: Path) -> None:
        """RMHOOK-DT-009: rm buried in an && chain is still caught.

        The PR #214 incident shape: `rm -rf <dir> && tool && git checkout -- <dir>`.
        """
        repo = make_repo(tmp_path)
        cmd = "rm -rf tracked && echo done && git checkout -- tracked"
        assert run_hook(_bash(cmd, cwd=str(repo))).returncode == 2

    def test_rmhook_dt_010_blocks_second_target(self, tmp_path: Path) -> None:
        """RMHOOK-DT-010: rm -rf <safe> <tracked> -- every target is checked."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -rf untracked tracked", cwd=str(repo))).returncode == 2

    def test_rmhook_dt_011_blocks_dash_leading_name_after_double_dash(self, tmp_path: Path) -> None:
        """RMHOOK-DT-011: after `--`, a dash-leading token is a target, not a flag.

        The target is named `-rescue` on purpose: without `--` handling it would be
        skipped by the `startswith("-")` flag filter. A plain name like `tracked`
        cannot exercise this branch -- it is collected as a positional either way,
        so the test would pass even with `--` support removed.
        """
        repo = make_repo(tmp_path)
        odd = repo / "-rescue"
        odd.mkdir()
        (odd / "keep.txt").write_text("committed\n", encoding="utf-8")
        _git(repo, "add", "--", "-rescue/keep.txt")
        _git(repo, "commit", "-q", "-m", "add dash-leading dir")

        r = run_hook(_bash("rm -rf -- -rescue", cwd=str(repo)))
        assert r.returncode == 2
        assert "keep.txt" in r.stdout


class TestUnresolvableTargets:
    def test_rmhook_eg_001_allows_variable_target(self, tmp_path: Path) -> None:
        """RMHOOK-EG-001: `rm -rf "$VAR"` cannot be statically resolved -> exit 0.

        Documented limitation: the hook does not expand the shell.
        """
        repo = make_repo(tmp_path)
        assert run_hook(_bash('rm -rf "$TARGET"', cwd=str(repo))).returncode == 0

    def test_rmhook_eg_002_allows_glob_target(self, tmp_path: Path) -> None:
        """RMHOOK-EG-002: glob target -> exit 0 (documented limitation)."""
        repo = make_repo(tmp_path)
        assert run_hook(_bash("rm -rf tracked/*", cwd=str(repo))).returncode == 0


class TestCrossWorktree:
    def test_rmhook_st_001_detects_tracked_in_other_worktree(self, tmp_path: Path) -> None:
        """RMHOOK-ST-001: a target inside ANOTHER worktree is checked against that
        worktree's index, not the caller's.

        This is why the hook runs `git -C <target> ls-files` rather than
        `git ls-files -- <target>` from cwd: in PR #214 the deletion targeted a
        sibling worktree's tracked content, which the main repo's index does not
        list. Querying from cwd would return empty and wrongly allow it.
        """
        repo = make_repo(tmp_path)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", str(wt), "-b", "side")

        # Sanity: the caller's own index does NOT list the other worktree's path.
        from_cwd = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--", str(wt / "tracked")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert from_cwd.stdout.strip() == "", "premise: cwd's index cannot see the other worktree"

        # The hook must still catch it.
        r = run_hook(_bash(f"rm -rf {wt / 'tracked'}", cwd=str(repo)))
        assert r.returncode == 2
        assert "keep.txt" in r.stdout

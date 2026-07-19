"""parse_git_dir.py unit tests.

Tests the resolve_git_dir() function which extracts the git -C <path> target
from a shell command string. The fail-closed contract (EXIT_UNRESOLVABLE for
command substitution and unbound variables) is safety-critical: a regression
that returns EXIT_OK instead of EXIT_UNRESOLVABLE would silently bypass the
protect-push hook for command-substitution-based worktree paths.
"""

import importlib.util
from pathlib import Path

_SKILL_PATH = (
    Path(__file__).parent.parent.parent.parent / "skills" / "protect-push" / "parse_git_dir.py"
)
_spec = importlib.util.spec_from_file_location("parse_git_dir", _SKILL_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

resolve_git_dir = _mod.resolve_git_dir
EXIT_OK = _mod.EXIT_OK
EXIT_UNRESOLVABLE = _mod.EXIT_UNRESOLVABLE


class TestNoMatch:
    def test_pgd_allow_001_no_git_push(self) -> None:
        """No git push at all -> returns empty, EXIT_OK"""
        assert resolve_git_dir("echo hello") == ("", EXIT_OK)

    def test_pgd_allow_002_bare_git_push(self) -> None:
        """Bare git push (no -C) -> returns empty, EXIT_OK (not our concern)"""
        assert resolve_git_dir("git push origin main") == ("", EXIT_OK)

    def test_pgd_allow_003_git_c_not_push(self) -> None:
        """git -C path commit (not push) -> no match, EXIT_OK"""
        assert resolve_git_dir('git -C /wt commit -m "push changes"') == ("", EXIT_OK)

    def test_pgd_allow_004_git_c_log_grep_push(self) -> None:
        """git -C path log --grep=push -> 'push' inside flag, not a push cmd"""
        assert resolve_git_dir("git -C /wt log --grep=push") == ("", EXIT_OK)

    def test_pgd_allow_005_git_c_add_push_file(self) -> None:
        """git -C /wt add push-config.sh -> 'push' in filename, not a push cmd"""
        assert resolve_git_dir("git -C /wt add push-config.sh") == ("", EXIT_OK)

    def test_pgd_allow_006_git_c_add_pathspec_push(self) -> None:
        """git -C /wt add push -> 'push' is a pathspec arg, not push subcommand"""
        assert resolve_git_dir("git -C /wt add push") == ("", EXIT_OK)

    def test_pgd_allow_007_git_c_commit_message_push(self) -> None:
        """git -C /wt commit -m push -> 'push' is commit message, not subcommand"""
        assert resolve_git_dir("git -C /wt commit -m push") == ("", EXIT_OK)


class TestLiteralPaths:
    def test_pgd_allow_010_unquoted(self) -> None:
        """git -C /path push (unquoted) -> resolves correctly"""
        assert resolve_git_dir("git -C /path/to/repo push") == ("/path/to/repo", EXIT_OK)

    def test_pgd_allow_011_double_quoted(self) -> None:
        """git -C "/path" push (double-quoted) -> strips quotes"""
        assert resolve_git_dir('git -C "/path/to/repo" push') == ("/path/to/repo", EXIT_OK)

    def test_pgd_allow_012_single_quoted(self) -> None:
        """git -C '/path' push (single-quoted) -> strips quotes"""
        assert resolve_git_dir("git -C '/path/to/repo' push") == ("/path/to/repo", EXIT_OK)

    def test_pgd_allow_013_push_with_flags(self) -> None:
        """git -C /path push --force -> push with flags, resolves path"""
        assert resolve_git_dir("git -C /path push --force") == ("/path", EXIT_OK)

    def test_pgd_allow_014_git_global_flag_before_push(self) -> None:
        """git -C /path --no-pager push -> global flag between path and push"""
        assert resolve_git_dir("git -C /path --no-pager push") == ("/path", EXIT_OK)

    def test_pgd_allow_015_git_option_with_argument(self) -> None:
        """git -C /wt -c credential.helper=store push -> option+arg pair, still resolves"""
        assert resolve_git_dir("git -C /wt -c credential.helper=store push") == (
            "/wt",
            EXIT_OK,
        )

    def test_pgd_allow_016_push_default_in_option_value(self) -> None:
        """git -C /wt -c push.default=upstream push -> 'push' in value, not subcommand"""
        assert resolve_git_dir("git -C /wt -c push.default=upstream push") == (
            "/wt",
            EXIT_OK,
        )


class TestVariableResolution:
    def test_pgd_allow_020_dollar_var(self) -> None:
        """$WT with prior assignment -> resolves to assigned value"""
        assert resolve_git_dir('WT=/some/worktree && git -C "$WT" push') == (
            "/some/worktree",
            EXIT_OK,
        )

    def test_pgd_allow_021_brace_var(self) -> None:
        """${WT} brace form -> strips braces, resolves correctly"""
        assert resolve_git_dir('WT=/some/worktree && git -C "${WT}" push') == (
            "/some/worktree",
            EXIT_OK,
        )

    def test_pgd_allow_022_last_wins_semantics(self) -> None:
        """Multiple assignments -> last one before git -C wins (shell semantics)"""
        assert resolve_git_dir('WT=/first && WT=/second && git -C "$WT" push') == (
            "/second",
            EXIT_OK,
        )

    def test_pgd_allow_023_single_quoted_assignment(self) -> None:
        """WT='/path' single-quoted assignment -> resolves correctly"""
        assert resolve_git_dir("WT='/some/path' && git -C \"$WT\" push") == (
            "/some/path",
            EXIT_OK,
        )

    def test_pgd_allow_024_double_quoted_assignment(self) -> None:
        """WT="/path" double-quoted assignment -> resolves correctly"""
        assert resolve_git_dir('WT="/some/path" && git -C "$WT" push') == (
            "/some/path",
            EXIT_OK,
        )


class TestFailClosed:
    def test_pgd_block_001_cmd_subst_at_c(self) -> None:
        """git -C $(pwd) push -> fail closed (command substitution unresolvable)"""
        assert resolve_git_dir("git -C $(pwd) push") == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_002_backtick_at_c(self) -> None:
        """git -C `pwd` push -> fail closed (backtick unresolvable)"""
        assert resolve_git_dir("git -C `pwd` push") == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_003_unbound_var(self) -> None:
        """git -C "$UNBOUND" push (no prior assignment) -> fail closed"""
        assert resolve_git_dir('git -C "$UNBOUND" push') == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_004_unbound_brace_var(self) -> None:
        """git -C "${UNBOUND}" push (no prior assignment, brace form) -> fail closed"""
        assert resolve_git_dir('git -C "${UNBOUND}" push') == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_005_cmd_subst_in_var_value(self) -> None:
        """WT=$(pwd) && git -C "$WT" push -> fail closed (cmd subst in value)"""
        assert resolve_git_dir('WT=$(pwd) && git -C "$WT" push') == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_006_backtick_in_var_value(self) -> None:
        """WT=`pwd` && git -C "$WT" push -> fail closed (backtick in value)"""
        assert resolve_git_dir('WT=`pwd` && git -C "$WT" push') == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_007_assignment_after_git_c(self) -> None:
        """Assignment AFTER git -C position -> unbound (only before-position counts)"""
        assert resolve_git_dir('git -C "$WT" push && WT=/path') == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_008_embedded_var_in_path(self) -> None:
        """git -C /tmp/$WT push -> fail closed (expansion embedded in path)"""
        assert resolve_git_dir("git -C /tmp/$WT push") == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_009_embedded_cmd_subst_in_path(self) -> None:
        """git -C /tmp/$(pwd) push -> fail closed (cmd subst embedded in path)"""
        assert resolve_git_dir("git -C /tmp/$(pwd) push") == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_010_resolved_value_has_embedded_var(self) -> None:
        """WT="$ROOT/wt" (expansion in assignment value) -> fail closed"""
        assert resolve_git_dir('WT="$ROOT/wt" && git -C "$WT" push') == ("", EXIT_UNRESOLVABLE)

    def test_pgd_block_011_resolved_value_has_embedded_cmd_subst(self) -> None:
        """WT="/tmp/$(pwd)" (cmd subst in assignment value) -> fail closed"""
        assert resolve_git_dir('WT="/tmp/$(pwd)" && git -C "$WT" push') == ("", EXIT_UNRESOLVABLE)

"""Tests for the codex shell scripts (codex-r1-stage1).

Static contract tests — read the script source and assert the skill-hijack
guard invariants. These guard against a silent regression where someone reverts
`codex review "$CODEX_GUARD" --base ...` back to a bare `codex review --base ...`,
which reintroduces the agentic-hijack failure documented in the lesson
`codex-review-derails-with-agents-md-scaffolding` (recurred 2026-06-29 / PR #653 /
2026-07-07): a bare `codex review` in a repo whose AGENTS.md routes to gstack /
Codex-CLI plugin skills reads those skill files as instructions and goes agentic,
producing exploration output and no structured findings.
"""

from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STAGE1 = SCRIPTS_DIR / "codex-r1-stage1.sh"

# The four sensitive path prefixes the guard prompt must name (mirrors the
# canonical guard in plugins/3rd-tools/skills/codex/SKILL.md).
_GUARD_PATHS = ("~/.claude/", "~/.agents/", ".claude/skills/", "agents/")


class TestCodexGuardContract:
    def test_cdxs_dt_001_review_receives_positional_guard(self) -> None:
        """CDXS-DT-001: `codex review` is called with the guard as a positional prompt.

        A bare `codex review --base ...` (no positional prompt) is exactly the
        hijack vector; the guard must be the first argument after `codex review`.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert 'codex review "$CODEX_GUARD"' in src, (
            "codex review must pass $CODEX_GUARD as its positional prompt"
        )

    def test_cdxs_dt_002_guard_names_all_sensitive_paths(self) -> None:
        """CDXS-DT-002: the guard prompt names every sensitive skill directory."""
        src = STAGE1.read_text(encoding="utf-8")
        assert "CODEX_GUARD=" in src, "guard prompt variable must be defined"
        for path in _GUARD_PATHS:
            assert path in src, f"guard prompt must name {path}"

    def test_cdxs_dt_003_stdin_closed_on_review(self) -> None:
        """CDXS-DT-003: stdin is closed on the review call.

        `< /dev/null` prevents a hijacking skill from feeding skill-file content
        in as an interactive prompt, and stops the review blocking on a read.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert "< /dev/null" in src, "codex review must close stdin with `< /dev/null`"

    def test_cdxs_dt_004_no_bare_review_invocation(self) -> None:
        """CDXS-DT-004: there is no un-guarded `codex review --base` in the script.

        Locks in the fix: the only `codex review` line must carry the guard, so a
        partial revert (dropping the guard while keeping --base) is caught.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert "codex review --base" not in src, (
            "a bare `codex review --base` (no positional guard) reintroduces the hijack"
        )

"""Tests for the codex shell scripts (codex-r1-stage1).

Static contract tests -- read the script source and assert the skill-hijack guard
invariants for the `codex exec` rewrite (issue #194).

Background: `codex review --base` rejects a positional prompt on codex-cli 0.142.5
(`error: the argument '[PROMPT]' cannot be used with '--base <BRANCH>'`), so the guard
cannot ride on `codex review`. Stage 1 drives the review through `codex exec`, feeding
the guard + prompt-r1.md + diff.patch on stdin. These tests guard against a regression
back to `codex review` (which would re-open the hijack hole and fail at runtime) and
against dropping the guard or the stdin-fed diff.
"""

from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STAGE1 = SCRIPTS_DIR / "codex-r1-stage1.sh"

# The four sensitive path prefixes the guard prompt must name (mirrors the
# canonical guard in plugins/3rd-tools/skills/codex/SKILL.md).
_GUARD_PATHS = ("~/.claude/", "~/.agents/", ".claude/skills/", "agents/")


class TestCodexGuardContract:
    def test_cdxs_dt_001_uses_codex_exec_not_review(self) -> None:
        """CDXS-DT-001: Stage 1 drives the review through `codex exec`, not `codex review`.

        `codex review --base` cannot carry a positional guard prompt, so any `codex review`
        invocation here means the guard is absent and the hijack hole is re-opened.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert "codex exec" in src, "Stage 1 must drive the review through `codex exec`"
        # allow `codex review` only in explanatory comments, never as an executed command.
        for line in src.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert "codex review" not in stripped, (
                f"non-comment line invokes codex review (hijack risk): {line!r}"
            )

    def test_cdxs_dt_002_guard_defined_and_names_all_sensitive_paths(self) -> None:
        """CDXS-DT-002: the guard prompt is defined and names every sensitive skill dir."""
        src = STAGE1.read_text(encoding="utf-8")
        assert "CODEX_GUARD=" in src, "guard prompt variable must be defined"
        for path in _GUARD_PATHS:
            assert path in src, f"guard prompt must name {path}"

    def test_cdxs_dt_003_guard_is_first_line_of_exec_stdin(self) -> None:
        """CDXS-DT-003: the guard is prepended to the stdin prompt fed to codex exec.

        The guard only works if it actually reaches codex; it must be printed into the
        input file that is redirected into `codex exec` on stdin.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert 'printf \'%s\\n\\n\' "$CODEX_GUARD"' in src, (
            "guard must be printed as the leading line of the codex exec stdin prompt"
        )
        assert "< \"$REVIEW_DIR/codex-r1-input.md\"" in src, (
            "codex exec must read the assembled guard+prompt+diff from stdin"
        )

    def test_cdxs_dt_004_reviews_shared_diff_patch(self) -> None:
        """CDXS-DT-004: Stage 1 reviews the shared diff.patch (all voices see one diff)."""
        src = STAGE1.read_text(encoding="utf-8")
        assert 'cat "$REVIEW_DIR/diff.patch"' in src, (
            "Stage 1 must feed the shared $REVIEW_DIR/diff.patch into the review prompt"
        )

    def test_cdxs_dt_005_writes_raw_md_for_stage2(self) -> None:
        """CDXS-DT-005: the review is captured to codex-r1-raw.md (consumed by Stage 2).

        codex exec writes the review to stdout, so stdout must be redirected to the raw
        file that codex-r1-stage2.sh reads; a regression here silently breaks extraction.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert "> \"$REVIEW_DIR/codex-r1-raw.md\"" in src, (
            "codex exec stdout must be redirected to codex-r1-raw.md"
        )

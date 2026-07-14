"""Tests for the codex shell scripts (codex-r1-stage1).

Two layers, mirroring test_agy_scripts.py / test_setup_review_dir.py:
  * Static contract tests -- read the script source and assert the skill-hijack guard
    invariants for the `codex exec` rewrite (issue #194).
  * Behavioral tests -- run codex-r1-stage1.sh end-to-end with a fake `codex` on PATH,
    verifying the guard actually reaches codex on stdin, the missing-input guards fire,
    and the agentic-output detector rejects non-review output.

Background: `codex review --base` rejects a positional prompt on codex-cli 0.142.5
(`error: the argument '[PROMPT]' cannot be used with '--base <BRANCH>'`), so the guard
cannot ride on `codex review`. Stage 1 drives the review through `codex exec`, feeding
the guard + prompt-r1.md + diff.patch on stdin.
"""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STAGE1 = SCRIPTS_DIR / "codex-r1-stage1.sh"
R2 = SCRIPTS_DIR / "codex-r2.sh"

# The frontier model slug both review stages must pin. Sourced from ~/.codex/models_cache.json
# (priority 1, "Latest frontier agentic coding model"), not from developers.openai.com/codex,
# whose docs still listed gpt-5.5 as top days after the GPT-5.6 release.
_FRONTIER_MODEL = "gpt-5.6-sol"

# The sensitive path prefixes the guard prompt must name (mirrors the canonical guard in
# plugins/3rd-tools/skills/codex/SKILL.md). `agents/` is asserted separately as a standalone
# token so it isn't satisfied by the `~/.agents/` substring.
_GUARD_PATHS = ("~/.claude/", "~/.agents/", ".claude/skills/")


def _codex_guard(src: str) -> str:
    """Extract the single-quoted CODEX_GUARD='...' value from the script source."""
    m = re.search(r"CODEX_GUARD='([^']*)'", src)
    assert m, "CODEX_GUARD must be defined as a single-quoted string"
    return m.group(1)


# --------------------------------------------------------------------------- #
# Static contract tests
# --------------------------------------------------------------------------- #


class TestCodexGuardContract:
    def test_cdxs_dt_001_uses_codex_exec_not_review(self) -> None:
        """CDXS-DT-001: Stage 1 drives the review through `codex exec`, not `codex review`.

        `codex review --base` cannot carry a positional guard prompt, so any executed
        `codex review` here means the guard is absent and the hijack hole is re-opened.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert "codex exec" in src, "Stage 1 must drive the review through `codex exec`"
        for line in src.splitlines():
            if line.lstrip().startswith("#"):
                continue
            assert "codex review" not in line, (
                f"non-comment line invokes codex review (hijack risk): {line!r}"
            )

    def test_cdxs_dt_002_guard_names_all_sensitive_paths(self) -> None:
        """CDXS-DT-002: the guard prompt names every sensitive skill dir.

        Checked against the extracted CODEX_GUARD value, with `agents/` matched as a
        standalone token (a plain `"agents/" in src` would be satisfied by `~/.agents/`).
        """
        guard = _codex_guard(STAGE1.read_text(encoding="utf-8"))
        for path in _GUARD_PATHS:
            assert path in guard, f"guard must name {path}"
        assert re.search(r"(?<![.\w])agents/", guard), (
            "guard must name the standalone `agents/` path, not only `~/.agents/`"
        )

    def test_cdxs_dt_003_guard_is_first_line_of_exec_stdin(self) -> None:
        """CDXS-DT-003: the guard is prepended to the stdin prompt fed to codex exec."""
        src = STAGE1.read_text(encoding="utf-8")
        assert "printf '%s\\n\\n' \"$CODEX_GUARD\"" in src, (
            "guard must be printed as the leading line of the codex exec stdin prompt"
        )
        assert '< "$REVIEW_DIR/codex-r1-input.md"' in src, (
            "codex exec must read the assembled guard+prompt+diff from stdin"
        )

    def test_cdxs_dt_004_reviews_shared_diff_patch(self) -> None:
        """CDXS-DT-004: Stage 1 reviews the shared diff.patch (all voices see one diff)."""
        src = STAGE1.read_text(encoding="utf-8")
        assert 'cat "$REVIEW_DIR/diff.patch"' in src, (
            "Stage 1 must feed the shared $REVIEW_DIR/diff.patch into the review prompt"
        )

    def test_cdxs_dt_005_writes_raw_md_for_stage2(self) -> None:
        """CDXS-DT-005: the review is captured to codex-r1-raw.md (consumed by Stage 2)."""
        src = STAGE1.read_text(encoding="utf-8")
        assert '> "$REVIEW_DIR/codex-r1-raw.md"' in src, (
            "codex exec stdout must be redirected to codex-r1-raw.md"
        )

    def test_cdxs_dt_006_exec_flags_pinned(self) -> None:
        """CDXS-DT-006: the -s read-only and -C "$WT_ROOT" flags are pinned.

        Dropping `-s read-only` lets codex mutate the tree; dropping `-C "$WT_ROOT"`
        re-opens the "runs against wrong repo" bug the SKILL.md FAQ documents as fixed
        by exactly this flag.
        """
        src = STAGE1.read_text(encoding="utf-8")
        assert "-s read-only" in src, "codex exec must run -s read-only"
        assert '-C "$WT_ROOT"' in src, "codex exec must pin the repo root with -C"

    @pytest.mark.parametrize("script", [STAGE1, R2])
    def test_cdxs_dt_010_frontier_model_pinned(self, script: Path) -> None:
        """CDXS-DT-010: both review stages pin -m gpt-5.6-sol.

        Without -m, codex inherits the reviewer's ~/.codex/config.toml, so which model
        reviews the PR silently depends on local config -- a skill shipped via the pr-flow
        plugin must not vary that way. Dropping the flag produces no error, just a quieter
        model, which is exactly the class of regression these contract tests exist to catch.
        """
        src = script.read_text(encoding="utf-8")
        assert f"-m {_FRONTIER_MODEL}" in src, (
            f"{script.name}: codex exec must pin -m {_FRONTIER_MODEL}"
        )

    def test_cdxs_dt_011_extract_stage_is_not_pinned_to_frontier(self) -> None:
        """CDXS-DT-011: the extract stage does NOT pin the frontier model.

        Stage 2 only reshapes stage 1's raw markdown into JSON -- no reasoning. Pinning the
        frontier tier there would burn the expensive model on a mechanical transform. This
        asserts the asymmetry is deliberate, so a later "make it consistent" refactor has to
        confront the intent rather than silently upgrading the cheap stage.
        """
        src = (SCRIPTS_DIR / "codex-r1-stage2.sh").read_text(encoding="utf-8")
        assert f"-m {_FRONTIER_MODEL}" not in src, (
            "extract stage must not pin the frontier model; it is a mechanical transform"
        )

    def test_cdxs_dt_007_stage1_does_not_fetch(self) -> None:
        """CDXS-DT-007: stage1 executes no git fetch (issue #194).

        setup-review-dir.sh is the sole owner of the fetch+FETCH_HEAD base resolution;
        re-adding a fetch here would re-introduce the exact duplication #194 removed.
        Comment lines are skipped so an explanatory mention of `git fetch` in a comment
        doesn't fail the contract (parity with DT-001's comment-aware scan).
        """
        for line in STAGE1.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            assert "git fetch" not in line, (
                f"stage1 must not fetch; setup-review-dir.sh owns base resolution: {line!r}"
            )

    def test_cdxs_dt_008_stderr_captured_to_stage1_log(self) -> None:
        """CDXS-DT-008: codex exec stderr is captured to codex-r1.stage1.log (the crux of
        the stdout/stderr swap vs the old codex review)."""
        assert '2>"$REVIEW_DIR/codex-r1.stage1.log"' in STAGE1.read_text(encoding="utf-8")

    def test_cdxs_dt_009_agentic_output_gate(self) -> None:
        """CDXS-DT-009: the raw output is gated on a review-heading marker (agentic-hijack
        detector, parity with agy_validate.py)."""
        src = STAGE1.read_text(encoding="utf-8")
        assert "Summary|Findings|Verdict" in src, (
            "stage1 must reject output lacking a review heading (agentic-output detector)"
        )


# --------------------------------------------------------------------------- #
# Behavioral tests (fake `codex` on PATH)
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    )


@pytest.fixture
def stage1_repo(tmp_path: Path) -> dict[str, Path]:
    """A git repo with a populated .pr-review/ (diff.patch + prompt-r1.md), plus a
    fake-codex bin dir whose behavior is driven by env vars set per test."""
    if not STAGE1.exists():
        pytest.skip("codex-r1-stage1.sh not found")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    review = repo / ".pr-review"
    review.mkdir()
    (review / "diff.patch").write_text(
        "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -0,0 +1 @@\n+hello\n", encoding="utf-8"
    )
    (review / "prompt-r1.md").write_text(
        "Review the diff. Emit ## Summary / ## Verdict.\n", encoding="utf-8"
    )

    # Fake `codex`: saves its stdin to CODEX_STDIN_CAPTURE and prints CODEX_STDOUT_BODY.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    codex = bindir / "codex"
    codex.write_text(
        (
            "#!/usr/bin/env bash\n"
            'cat > "$CODEX_STDIN_CAPTURE"\n'
            'cat "$CODEX_STDOUT_BODY"\n'
            'exit "${CODEX_EXIT:-0}"\n'
        ),
        encoding="utf-8",
    )
    codex.chmod(0o755)
    return {"repo": repo, "review": review, "bindir": bindir, "tmp": tmp_path}


def _run_stage1(
    env_extra: dict[str, str], repo: Path, bindir: Path
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        **env_extra,
    }
    return subprocess.run(  # nosec B603
        ["bash", str(STAGE1)], cwd=str(repo), capture_output=True, text=True, env=env
    )


class TestStage1Behavioral:
    def test_cdxs_st_001_guard_and_diff_reach_codex(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-001: happy path -- the guard is the first line of codex's stdin and the
        diff is included; a valid review passes the agentic gate."""
        capture = stage1_repo["tmp"] / "stdin.txt"
        body = stage1_repo["tmp"] / "body.md"
        body.write_text("## Summary\nok\n## Verdict\nLGTM\n", encoding="utf-8")
        res = _run_stage1(
            {"CODEX_STDIN_CAPTURE": str(capture), "CODEX_STDOUT_BODY": str(body)},
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode == 0, f"expected success, got {res.returncode}: {res.stderr}"
        fed = capture.read_text(encoding="utf-8")
        assert fed.startswith("IMPORTANT: Do NOT read or execute"), (
            "guard must be codex's first stdin line"
        )
        assert "hello" in fed, "the diff.patch content must be included in codex's stdin"

    def test_cdxs_st_002_missing_diff_patch_fails_loud(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-002: a missing diff.patch aborts with a non-zero [FAIL] before codex runs."""
        (stage1_repo["review"] / "diff.patch").unlink()
        body = stage1_repo["tmp"] / "body.md"
        body.write_text("## Summary\n", encoding="utf-8")
        res = _run_stage1(
            {
                "CODEX_STDIN_CAPTURE": str(stage1_repo["tmp"] / "s.txt"),
                "CODEX_STDOUT_BODY": str(body),
            },
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode != 0
        assert "[FAIL]" in res.stderr

    def test_cdxs_st_003_agentic_output_rejected(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-003: non-review (agentic) output -- non-empty but no review heading --
        is rejected by the agentic-output gate instead of flowing to Stage 2."""
        capture = stage1_repo["tmp"] / "stdin.txt"
        body = stage1_repo["tmp"] / "body.md"
        body.write_text(
            "call:read_file{path: node_modules}\nExploring the repository...\n", encoding="utf-8"
        )
        res = _run_stage1(
            {"CODEX_STDIN_CAPTURE": str(capture), "CODEX_STDOUT_BODY": str(body)},
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode != 0, "agentic output (no review heading) must fail loud"
        assert "[FAIL]" in res.stderr

    def _valid_body(self, stage1_repo: dict[str, Path]) -> Path:
        body = stage1_repo["tmp"] / "body.md"
        body.write_text("## Summary\nok\n## Verdict\nLGTM\n", encoding="utf-8")
        return body

    def test_cdxs_st_004_codex_nonzero_exit_fails_loud(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-004: a non-zero `codex exec` exit is caught and reported (primary
        external-call failure mode)."""
        res = _run_stage1(
            {
                "CODEX_STDIN_CAPTURE": str(stage1_repo["tmp"] / "s.txt"),
                "CODEX_STDOUT_BODY": str(self._valid_body(stage1_repo)),
                "CODEX_EXIT": "1",
            },
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode != 0
        assert "[FAIL]" in res.stderr and "codex exec" in res.stderr

    def test_cdxs_st_005_missing_prompt_fails_loud(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-005: a missing prompt-r1.md aborts before codex runs (symmetric with ST-002)."""
        (stage1_repo["review"] / "prompt-r1.md").unlink()
        res = _run_stage1(
            {
                "CODEX_STDIN_CAPTURE": str(stage1_repo["tmp"] / "s.txt"),
                "CODEX_STDOUT_BODY": str(self._valid_body(stage1_repo)),
            },
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode != 0
        assert "[FAIL]" in res.stderr and "prompt-r1.md" in res.stderr

    def test_cdxs_st_006_empty_prompt_fails_loud(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-006: an empty prompt-r1.md fails with its own message, not the agentic
        gate's -- the operator sees the real cause (SFH NIT1)."""
        (stage1_repo["review"] / "prompt-r1.md").write_text("", encoding="utf-8")
        res = _run_stage1(
            {
                "CODEX_STDIN_CAPTURE": str(stage1_repo["tmp"] / "s.txt"),
                "CODEX_STDOUT_BODY": str(self._valid_body(stage1_repo)),
            },
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode != 0
        assert "prompt-r1.md" in res.stderr and "空白" in res.stderr

    def test_cdxs_st_007_empty_diff_fails_loud(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-007: an empty diff.patch fails the non-empty gate before codex runs."""
        (stage1_repo["review"] / "diff.patch").write_text("", encoding="utf-8")
        res = _run_stage1(
            {
                "CODEX_STDIN_CAPTURE": str(stage1_repo["tmp"] / "s.txt"),
                "CODEX_STDOUT_BODY": str(self._valid_body(stage1_repo)),
            },
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode != 0
        assert "diff.patch" in res.stderr

    def test_cdxs_st_008_empty_review_output_fails_loud(self, stage1_repo: dict[str, Path]) -> None:
        """CDXS-ST-008: an empty codex-r1-raw.md (codex produced nothing) fails the -s gate."""
        empty = stage1_repo["tmp"] / "empty.md"
        empty.write_text("", encoding="utf-8")
        res = _run_stage1(
            {
                "CODEX_STDIN_CAPTURE": str(stage1_repo["tmp"] / "s.txt"),
                "CODEX_STDOUT_BODY": str(empty),
            },
            stage1_repo["repo"],
            stage1_repo["bindir"],
        )
        assert res.returncode != 0
        assert "[FAIL]" in res.stderr and "codex-r1-raw.md" in res.stderr

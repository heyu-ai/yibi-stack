"""Tests for plugins/pr-flow/skills/pr-cycle-deep/scripts/agy_validate.py.

Covers the issue #153 fail-loud validation + brain-artifact rescue layer.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from agy_validate import (
    _AGENTIC_SEARCH_PREFIXES,
    _BRAIN_POINTER_PREFIXES,
    _NARRATION_PREFIXES,
    _TOOLCALL_PREFIXES,
    check_agentic_narration,
    check_changed_files,
    check_timeout,
    check_verdict,
    find_brain_pointer,
    has_review_body,
    main,
    rescue_brain_artifact,
    validate,
)

GOOD_REVIEW = """## Verdict
NEEDS_CHANGES

### [important] race in service.py
The handler in tasks/foo/service.py misses a lock.
"""


class TestFindBrainPointer:
    def test_agyv_dt_001_finds_absolute_pointer(self) -> None:
        """AGYV-DT-001: absolute brain path is extracted."""
        text = (
            "I have written the analysis to "
            "/Users/howie/.gemini/antigravity-cli/brain/"
            "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d/analysis_results.md"
        )
        assert find_brain_pointer(text) == (
            "/Users/howie/.gemini/antigravity-cli/brain/"
            "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d/analysis_results.md"
        )

    def test_agyv_dt_002_finds_tilde_pointer(self) -> None:
        """AGYV-DT-002: ~-anchored brain path is extracted."""
        text = "See `~/.gemini/antigravity-cli/brain/abcdef12/result.md` for details."
        assert find_brain_pointer(text) == "~/.gemini/antigravity-cli/brain/abcdef12/result.md"

    def test_agyv_dt_003_none_for_normal_review(self) -> None:
        """AGYV-DT-003: a real review has no brain pointer."""
        assert find_brain_pointer(GOOD_REVIEW) is None


class TestRescueBrainArtifact:
    def _write_brain(self, home: Path, body: str) -> str:
        rel = ".gemini/antigravity-cli/brain/abcdef12/result.md"
        artifact = home / rel
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(body, encoding="utf-8")
        return f"~/{rel}"

    def test_agyv_dt_004_reads_artifact_content(self, tmp_path: Path) -> None:
        """AGYV-DT-004: pointer is replaced by the artifact's real content."""
        pointer = self._write_brain(tmp_path, GOOD_REVIEW)
        text = f"I have finished. Output written to {pointer}"
        content, rescued = rescue_brain_artifact(text, home=tmp_path)
        assert rescued == pointer
        assert content == GOOD_REVIEW

    def test_agyv_eg_001_missing_artifact_returns_original(self, tmp_path: Path) -> None:
        """AGYV-EG-001: a dangling pointer leaves the original text untouched."""
        text = "Output at ~/.gemini/antigravity-cli/brain/deadbeef/missing.md"
        content, rescued = rescue_brain_artifact(text, home=tmp_path)
        assert rescued is None
        assert content == text

    def test_agyv_eg_002_empty_artifact_returns_original(self, tmp_path: Path) -> None:
        """AGYV-EG-002: an empty artifact is not a valid rescue."""
        pointer = self._write_brain(tmp_path, "   \n")
        text = f"done -> {pointer}"
        content, rescued = rescue_brain_artifact(text, home=tmp_path)
        assert rescued is None
        assert content == text

    def test_agyv_dt_005_no_pointer_returns_original(self, tmp_path: Path) -> None:
        """AGYV-DT-005: text without a pointer is returned verbatim."""
        content, rescued = rescue_brain_artifact(GOOD_REVIEW, home=tmp_path)
        assert rescued is None
        assert content == GOOD_REVIEW

    def test_agyv_eg_007_pointer_outside_brain_dir_ignored(self, tmp_path: Path) -> None:
        """AGYV-EG-007: a /brain/ path outside ~/.gemini/.../brain is NOT read.

        Hardening: never read an arbitrary absolute path the model printed, even
        if it exists and is readable.
        """
        outside = tmp_path / "evil" / "brain" / "abcdef12" / "x.md"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text(GOOD_REVIEW, encoding="utf-8")
        text = f"done -> {outside}"
        content, rescued = rescue_brain_artifact(text, home=tmp_path / "home")
        assert rescued is None
        assert content == text

    def test_agyv_eg_008_present_but_unreadable_raises(self, tmp_path: Path) -> None:
        """AGYV-EG-008: an artifact that exists but can't be read propagates OSError.

        A directory at the artifact path makes read_text raise IsADirectoryError
        (an OSError, not FileNotFoundError) — the present-but-blocked condition
        that must surface loudly rather than silently validate the pointer text.
        """
        home = tmp_path / "home"
        artifact = home / ".gemini/antigravity-cli/brain/abcdef12/result.md"
        artifact.mkdir(parents=True, exist_ok=True)  # a directory, not a file
        text = "I have written it to ~/.gemini/antigravity-cli/brain/abcdef12/result.md"
        with pytest.raises(OSError):
            rescue_brain_artifact(text, home=home)


class TestCheckTimeout:
    def test_agyv_dt_006_detects_timeout_marker(self) -> None:
        """AGYV-DT-006: timeout marker leading a line is flagged."""
        assert check_timeout("Error: timed out waiting for response") is not None

    def test_agyv_dt_007_clean_output_passes(self) -> None:
        """AGYV-DT-007: clean output has no timeout error."""
        assert check_timeout(GOOD_REVIEW) is None

    def test_agyv_dt_016_second_marker_standalone_line(self) -> None:
        """AGYV-DT-016: the bare 'timed out waiting...' marker is also flagged."""
        assert check_timeout("...\ntimed out waiting for response\n") is not None

    def test_agyv_eg_005_body_mention_is_not_a_timeout(self) -> None:
        """AGYV-EG-005: a review whose body quotes the marker mid-line is NOT a timeout.

        Line-anchored: only a line that *starts* with the marker counts, so a
        finding about timeout-handling code does not falsely fail the voice.
        """
        text = (
            "## Verdict\nNEEDS_CHANGES\n"
            "### [important] race in tasks/foo/service.py\n"
            "The call returns Error: timed out waiting for response on slow links."
        )
        assert check_timeout(text) is None


class TestCheckAgenticNarration:
    def test_agyv_dt_008_detects_narration_prefix(self) -> None:
        """AGYV-DT-008: 'I will' narration prefix is flagged."""
        text = "I will search the repository for the changed files first."
        assert check_agentic_narration(text) is not None

    def test_agyv_dt_009_detects_toolcall_prefix(self) -> None:
        """AGYV-DT-009: a 'call:' tool-call marker is flagged."""
        assert check_agentic_narration("call:read_file{path: x}") is not None

    def test_agyv_dt_010_normal_review_passes(self) -> None:
        """AGYV-DT-010: a normal review (heading first) is not narration."""
        assert check_agentic_narration(GOOD_REVIEW) is None

    def test_agyv_eg_003_ignores_leading_blank_lines(self) -> None:
        """AGYV-EG-003: leading blank lines do not hide narration."""
        text = "\n\n   \nI'm going to look for the diff."
        assert check_agentic_narration(text) is not None

    def test_agyv_dt_017_detects_brain_pointer_opener(self) -> None:
        """AGYV-DT-017: 'I have written' (canonical brain-pointer opener) is flagged."""
        text = "I have written my analysis to ~/.gemini/.../brain/abcdef12/x.md"
        assert check_agentic_narration(text) is not None

    @pytest.mark.parametrize("prefix", _NARRATION_PREFIXES + _TOOLCALL_PREFIXES)
    def test_agyv_dt_018_every_marker_detected(self, prefix: str) -> None:
        """AGYV-DT-018: each narration/tool-call marker triggers detection.

        A typo in any literal would silently disable that detector; this guards
        the whole tuple, including 'tool_use:' which had no dedicated case.

        Bare ``prefix + "something"`` has no review-structure heading, so even the
        agentic-search prefixes (which are now downgradable) still fail here.
        """
        assert check_agentic_narration(prefix + "something") is not None

    @pytest.mark.parametrize("prefix", _AGENTIC_SEARCH_PREFIXES)
    def test_agyv_dt_020_search_preamble_with_review_body_passes(self, prefix: str) -> None:
        """AGYV-DT-020: agentic-search preamble followed by a real review passes.

        The issue #153 false reject: agy narrates one line then returns a full
        review. A review-structure heading downgrades the narration to harmless.
        """
        text = prefix + "look at the diff first.\n\n" + GOOD_REVIEW
        assert check_agentic_narration(text) is None

    @pytest.mark.parametrize("prefix", _BRAIN_POINTER_PREFIXES)
    def test_agyv_dt_021_brain_pointer_with_path_fails_despite_body(self, prefix: str) -> None:
        """AGYV-DT-021: a brain-pointer opener WITH a brain path hard-fails despite a heading.

        The real review is in a brain artifact (rescue could not recover it); a
        ## Verdict heading on stdout does not make the stdout body a review.
        """
        text = prefix + " to ~/.gemini/antigravity-cli/brain/abcdef12/x.md\n\n" + GOOD_REVIEW
        assert check_agentic_narration(text) is not None

    @pytest.mark.parametrize("prefix", _BRAIN_POINTER_PREFIXES)
    def test_agyv_dt_024_pointerless_brain_opener_with_body_passes(self, prefix: str) -> None:
        """AGYV-DT-024: a brain-phrase opener with NO brain path + a review body passes.

        "I have finished reviewing ..." with no brain-artifact path is an ordinary
        completion-phrase preamble, not the brain detour — the issue #153 false
        reject this fix targets. A review body downgrades it to harmless.
        """
        text = prefix + " reviewing the diff.\n\n" + GOOD_REVIEW
        assert check_agentic_narration(text) is None

    def test_agyv_dt_022_search_preamble_without_body_fails(self) -> None:
        """AGYV-DT-022: agentic-search preamble with no review body still fails."""
        text = "I will search the repo.\n\nStill looking, no review produced."
        assert check_agentic_narration(text) is not None


class TestHasReviewBody:
    @pytest.mark.parametrize(
        "heading",
        [
            "## Verdict",
            "## Summary",
            "## Findings",
            "### Findings",
            "## Cross-review verdict",  # R2 format
            "## New findings",  # R2 format
            "## Final verdict",  # R2 format
            "## Verdicts",  # plural variant
            "## Summaries",  # plural variant
        ],
    )
    def test_agyv_dt_023_review_headings_detected(self, heading: str) -> None:
        """AGYV-DT-023: R1/R2 review-structure headings (incl. plural variants) count as a body."""
        assert has_review_body(heading + "\nbody text") is True

    def test_agyv_eg_010_verdict_in_prose_is_not_a_body(self) -> None:
        """AGYV-EG-010: 'verdict' in plain prose (no heading) is not a review body."""
        assert has_review_body("I will determine the verdict shortly.") is False

    def test_agyv_eg_011_fenced_heading_is_not_a_body(self) -> None:
        """AGYV-EG-011: a '## Verdict' heading inside a code fence is not a review body.

        agy echoing a prompt/diff fragment (which contains these headings) inside a
        fence must not be read as a real review heading.
        """
        text = "I will scan.\n\n```\n## Verdict\n```\nstill searching, no review"
        assert has_review_body(text) is False

    def test_agyv_eg_012_tilde_fenced_heading_is_not_a_body(self) -> None:
        """AGYV-EG-012: ~~~-fenced heading is also stripped before the body search."""
        text = "~~~\n## Summary\nLGTM\n~~~"
        assert has_review_body(text) is False

    def test_agyv_eg_013_real_heading_outside_fence_still_detected(self) -> None:
        """AGYV-EG-013: a real heading outside a fence is still a body even with a fence present."""
        text = "## Verdict\nLGTM\n\n```\ncode sample\n```\n"
        assert has_review_body(text) is True

    def test_agyv_st_008_narration_with_fenced_heading_fails(self, tmp_path: Path) -> None:
        """AGYV-ST-008: agentic narration + a fenced heading (no real review) fails validate."""
        raw = tmp_path / "raw.md"
        raw.write_text(
            "I will scan.\n\n```\n## Verdict\n```\nstill searching",
            encoding="utf-8",
        )
        changed = tmp_path / "changed.txt"
        changed.write_text("tasks/foo/service.py\n", encoding="utf-8")
        rc = main(
            [
                "--raw",
                str(raw),
                "--changed-files",
                str(changed),
                "--require-verdict",
                "--home",
                str(tmp_path),
            ]
        )
        assert rc == 1


class TestCheckVerdict:
    def test_agyv_dt_011_present_passes(self) -> None:
        """AGYV-DT-011: a Verdict section passes."""
        assert check_verdict(GOOD_REVIEW) is None

    def test_agyv_dt_012_absent_fails(self) -> None:
        """AGYV-DT-012: missing Verdict section is flagged."""
        assert check_verdict("### finding\nsome text") is not None


class TestCheckChangedFiles:
    def test_agyv_dt_013_full_path_match_passes(self) -> None:
        """AGYV-DT-013: mentioning a full changed path passes."""
        assert check_changed_files(GOOD_REVIEW, ["tasks/foo/service.py"]) is None

    def test_agyv_dt_014_basename_match_passes(self) -> None:
        """AGYV-DT-014: mentioning just the basename passes."""
        text = "The bug is in service.py near the lock."
        assert check_changed_files(text, ["tasks/foo/service.py"]) is None

    def test_agyv_dt_015_no_match_fails_wrong_target(self) -> None:
        """AGYV-DT-015: citing other files but none of ours = wrong target."""
        text = "## Verdict\nLGTM\nReviewed src/unrelated/other.ts thoroughly."
        err = check_changed_files(text, ["tasks/foo/service.py"])
        assert err is not None
        assert "WRONG target" in err

    def test_agyv_eg_004_empty_list_never_blocks(self) -> None:
        """AGYV-EG-004: an empty changed-files list does not block."""
        assert check_changed_files("anything", []) is None

    def test_agyv_dt_019_clean_lgtm_without_file_refs_passes(self) -> None:
        """AGYV-DT-019: a terse clean LGTM (no file references) is NOT wrong-target.

        Resolves the Codex finding: requiring a changed-file mention would
        falsely fail legitimate no-findings reviews (esp. R2 over r1-aggregate).
        """
        text = "## Verdict\nLGTM\n## Summary\nNo issues found; the change is sound."
        assert check_changed_files(text, ["tasks/foo/service.py"]) is None

    def test_agyv_eg_006_other_file_refs_only_fails(self) -> None:
        """AGYV-EG-006: a review citing only foreign paths is wrong-target."""
        text = "## Verdict\nNEEDS_CHANGES\nBug in lib/other/handler.go at line 5."
        assert check_changed_files(text, ["tasks/foo/service.py"]) is not None

    def test_agyv_eg_009_no_redos_on_long_slash_run(self) -> None:
        """AGYV-EG-009: _FILE_REF is linear on a long slash-run (ReDoS regression).

        The earlier `[\\w.\\-/]+/[\\w.\\-/]+` form took >7s at ~1500 slashes; the
        separator-anchored form must finish near-instantly on a much larger input.
        """
        payload = ("a/" * 5000) + "!"  # long slash-run, no terminal extension
        start = time.perf_counter()
        result = check_changed_files(payload, ["tasks/foo/service.py"])
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"check_changed_files took {elapsed:.2f}s (possible ReDoS)"
        assert result is None  # no real file reference -> not wrong-target


class TestValidateAggregation:
    def test_agyv_vl_001_aggregates_multiple_errors(self) -> None:
        """AGYV-VL-001: timeout + missing verdict + wrong target all reported."""
        # Needs a file reference (other/wrong.py) so the wrong-target check fires;
        # the timeout marker must lead a line so the line-anchored check catches it.
        text = "Error: timed out waiting for response\nReviewed other/wrong.py instead."
        errors = validate(
            text,
            require_verdict=True,
            changed_files=["tasks/foo/service.py"],
        )
        # timeout + no-verdict + wrong-target
        assert len(errors) == 3

    def test_agyv_vl_002_clean_review_no_errors(self) -> None:
        """AGYV-VL-002: a clean review with all checks on yields no errors."""
        errors = validate(
            GOOD_REVIEW,
            require_verdict=True,
            changed_files=["tasks/foo/service.py"],
        )
        assert errors == []


class TestMain:
    def test_agyv_st_001_pass_returns_zero(self, tmp_path: Path) -> None:
        """AGYV-ST-001: a clean review passes end-to-end (exit 0)."""
        raw = tmp_path / "raw.md"
        raw.write_text(GOOD_REVIEW, encoding="utf-8")
        changed = tmp_path / "changed.txt"
        changed.write_text("tasks/foo/service.py\n", encoding="utf-8")
        rc = main(
            [
                "--raw",
                str(raw),
                "--changed-files",
                str(changed),
                "--require-verdict",
                "--label",
                "R1 Stage 1",
            ]
        )
        assert rc == 0

    def test_agyv_st_002_wrong_target_returns_one(self, tmp_path: Path) -> None:
        """AGYV-ST-002: wrong-target review fails (exit 1)."""
        raw = tmp_path / "raw.md"
        raw.write_text("## Verdict\nLGTM\nReviewed src/other/unrelated.ts.", encoding="utf-8")
        changed = tmp_path / "changed.txt"
        changed.write_text("tasks/foo/service.py\n", encoding="utf-8")
        rc = main(["--raw", str(raw), "--changed-files", str(changed)])
        assert rc == 1

    def test_agyv_st_003_brain_rescue_rewrites_raw(self, tmp_path: Path) -> None:
        """AGYV-ST-003: a brain pointer is rescued, raw file rewritten, then validated."""
        home = tmp_path / "home"
        artifact = home / ".gemini/antigravity-cli/brain/abcdef12/analysis_results.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(GOOD_REVIEW, encoding="utf-8")

        raw = tmp_path / "raw.md"
        raw.write_text(
            "I have written my analysis to "
            "~/.gemini/antigravity-cli/brain/abcdef12/analysis_results.md",
            encoding="utf-8",
        )
        changed = tmp_path / "changed.txt"
        changed.write_text("tasks/foo/service.py\n", encoding="utf-8")

        rc = main(
            [
                "--raw",
                str(raw),
                "--changed-files",
                str(changed),
                "--require-verdict",
                "--home",
                str(home),
            ]
        )
        assert rc == 0
        # raw file now holds the rescued real review, not the pointer
        assert raw.read_text(encoding="utf-8") == GOOD_REVIEW

    def test_agyv_st_004_missing_raw_returns_two(self, tmp_path: Path) -> None:
        """AGYV-ST-004: an unreadable raw file is a usage error (exit 2)."""
        rc = main(["--raw", str(tmp_path / "nope.md")])
        assert rc == 2

    def test_agyv_st_005_timeout_output_returns_one(self, tmp_path: Path) -> None:
        """AGYV-ST-005: a timeout output fails even without other flags."""
        raw = tmp_path / "raw.md"
        raw.write_text("Error: timed out waiting for response", encoding="utf-8")
        rc = main(["--raw", str(raw)])
        assert rc == 1

    def test_agyv_st_006_missing_changed_files_returns_two(self, tmp_path: Path) -> None:
        """AGYV-ST-006: an unreadable --changed-files is a usage error (exit 2)."""
        raw = tmp_path / "raw.md"
        raw.write_text(GOOD_REVIEW, encoding="utf-8")
        rc = main(["--raw", str(raw), "--changed-files", str(tmp_path / "nope.txt")])
        assert rc == 2

    def test_agyv_st_007_unreadable_brain_artifact_returns_two(self, tmp_path: Path) -> None:
        """AGYV-ST-007: a present-but-unreadable brain artifact exits 2 (loud)."""
        home = tmp_path / "home"
        artifact = home / ".gemini/antigravity-cli/brain/abcdef12/analysis_results.md"
        artifact.mkdir(parents=True, exist_ok=True)  # directory -> IsADirectoryError
        raw = tmp_path / "raw.md"
        raw.write_text(
            "I have written it to ~/.gemini/antigravity-cli/brain/abcdef12/analysis_results.md",
            encoding="utf-8",
        )
        rc = main(["--raw", str(raw), "--home", str(home)])
        assert rc == 2

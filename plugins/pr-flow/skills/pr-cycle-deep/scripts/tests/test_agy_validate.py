"""Tests for plugins/pr-flow/skills/pr-cycle-deep/scripts/agy_validate.py.

Covers the issue #153 fail-loud validation + brain-artifact rescue layer.
"""

from __future__ import annotations

from pathlib import Path

from agy_validate import (
    check_agentic_narration,
    check_changed_files,
    check_timeout,
    check_verdict,
    find_brain_pointer,
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
        assert (
            find_brain_pointer(text)
            == "~/.gemini/antigravity-cli/brain/abcdef12/result.md"
        )

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

    def test_agyv_eg_001_missing_artifact_returns_original(
        self, tmp_path: Path
    ) -> None:
        """AGYV-EG-001: a dangling pointer leaves the original text untouched."""
        text = "Output at ~/.gemini/antigravity-cli/brain/deadbeef/missing.md"
        content, rescued = rescue_brain_artifact(text, home=tmp_path)
        assert rescued is None
        assert content == text

    def test_agyv_eg_002_empty_artifact_returns_original(
        self, tmp_path: Path
    ) -> None:
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


class TestCheckTimeout:
    def test_agyv_dt_006_detects_timeout_marker(self) -> None:
        """AGYV-DT-006: timeout marker is flagged."""
        assert check_timeout("Error: timed out waiting for response") is not None

    def test_agyv_dt_007_clean_output_passes(self) -> None:
        """AGYV-DT-007: clean output has no timeout error."""
        assert check_timeout(GOOD_REVIEW) is None


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
        """AGYV-DT-015: mentioning none of the changed files = wrong target."""
        text = "## Verdict\nLGTM\nReviewed src/unrelated/other.ts thoroughly."
        err = check_changed_files(text, ["tasks/foo/service.py"])
        assert err is not None
        assert "WRONG target" in err

    def test_agyv_eg_004_empty_list_never_blocks(self) -> None:
        """AGYV-EG-004: an empty changed-files list does not block."""
        assert check_changed_files("anything", []) is None


class TestValidateAggregation:
    def test_agyv_vl_001_aggregates_multiple_errors(self) -> None:
        """AGYV-VL-001: timeout + missing verdict + wrong target all reported."""
        text = "Error: timed out waiting for response"
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
        raw.write_text(
            "## Verdict\nLGTM\nReviewed src/other/unrelated.ts.", encoding="utf-8"
        )
        changed = tmp_path / "changed.txt"
        changed.write_text("tasks/foo/service.py\n", encoding="utf-8")
        rc = main(["--raw", str(raw), "--changed-files", str(changed)])
        assert rc == 1

    def test_agyv_st_003_brain_rescue_rewrites_raw(self, tmp_path: Path) -> None:
        """AGYV-ST-003: a brain pointer is rescued, raw file rewritten, then validated."""
        home = tmp_path / "home"
        artifact = (
            home / ".gemini/antigravity-cli/brain/abcdef12/analysis_results.md"
        )
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

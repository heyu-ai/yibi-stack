"""harness_eval scanner 決策表測試。"""

from pathlib import Path

from tasks.harness_eval.scanners.claude_md import scan_claude_md


def make_target(tmp_path: Path, *, claude_md: str | None = None) -> Path:
    if claude_md is not None:
        (tmp_path / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    return tmp_path


class TestScanClaudeMd:
    def test_heval_dt_001_empty_repo(self, tmp_path: Path) -> None:
        """HEVAL-DT-001: 無 CLAUDE.md → score=0, findings 含 WARN。"""
        result = scan_claude_md(tmp_path)
        assert result.score == 0
        assert result.dimension == "D1"
        assert any("WARN" in f for f in result.findings)

    def test_heval_dt_002_claude_md_exists(self, tmp_path: Path) -> None:
        """HEVAL-DT-002: CLAUDE.md 存在 → score >= 3。"""
        content = "\n".join(["# Test"] + [f"line {i}" for i in range(50)])
        result = scan_claude_md(make_target(tmp_path, claude_md=content))
        assert result.score >= 3

    def test_heval_dt_003_under_200_lines(self, tmp_path: Path) -> None:
        """HEVAL-DT-003: CLAUDE.md 100 行 → 機械分 6/6。"""
        content = "\n".join([f"line {i}" for i in range(100)])
        result = scan_claude_md(make_target(tmp_path, claude_md=content))
        assert result.score == 6

    def test_heval_dt_004_over_200_lines(self, tmp_path: Path) -> None:
        """HEVAL-DT-004: CLAUDE.md 250 行 → score = 3（只得存在分）。"""
        content = "\n".join([f"line {i}" for i in range(250)])
        result = scan_claude_md(make_target(tmp_path, claude_md=content))
        assert result.score == 3

    def test_heval_dt_005_semantic_targets_populated(self, tmp_path: Path) -> None:
        """HEVAL-DT-005: CLAUDE.md 存在時 semantic_targets 含路徑。"""
        content = "# Test\nsome rule"
        result = scan_claude_md(make_target(tmp_path, claude_md=content))
        assert len(result.semantic_targets) >= 1

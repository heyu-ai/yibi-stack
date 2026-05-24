"""check_blank_proposal.py 的單元測試。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "scripts" / "check_blank_proposal.py"


def _run_script(*args: str, tmp_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    """在 tmp_path 建立 proposal.md 後執行 script。"""
    cmd = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(  # nosec B603
        cmd,
        capture_output=True,
        text=True,
        cwd=str(tmp_path) if tmp_path else None,
        timeout=30,
    )


def _write_proposal(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "proposal.md"
    path.write_text(content, encoding="utf-8")
    return path


class TestCheckFile:
    def test_blank_proposal_001_filled_proposal_passes(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-001: 沒有 HTML comment 的 proposal 通過，exit 0。"""
        proposal = _write_proposal(
            tmp_path, "## Why\n\nThis is why.\n\n## What Changes\n\n- Something changed.\n"
        )
        result = _run_script(str(proposal))
        assert result.returncode == 0
        assert "[FAIL]" not in result.stderr

    def test_blank_proposal_002_blank_placeholder_fails(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-002: 含 <!-- --> 佔位符的 proposal 被攔截，exit 1。"""
        proposal = _write_proposal(
            tmp_path,
            "## Why\n\n<!-- Explain the motivation -->\n\n## What Changes\n\n- Something.\n",
        )
        result = _run_script(str(proposal))
        assert result.returncode == 1
        assert "[FAIL]" in result.stderr

    def test_blank_proposal_003_error_shows_filename(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-003: 錯誤訊息含違規檔案路徑。"""
        proposal = _write_proposal(tmp_path, "<!-- placeholder -->\n")
        result = _run_script(str(proposal))
        assert str(proposal) in result.stderr

    def test_blank_proposal_004_error_shows_line_number(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-004: 錯誤訊息含違規行號。"""
        proposal = _write_proposal(tmp_path, "## Why\n\n<!-- placeholder -->\n")
        result = _run_script(str(proposal))
        assert "行 3" in result.stderr

    def test_blank_proposal_005_multiple_violations_all_reported(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-005: 多個 <!-- --> 全部被回報。"""
        proposal = _write_proposal(
            tmp_path,
            "<!-- reason -->\n\n## What Changes\n\n<!-- changes -->\n",
        )
        result = _run_script(str(proposal))
        assert result.returncode == 1
        assert "行 1" in result.stderr
        assert "行 5" in result.stderr

    def test_blank_proposal_006_no_args_scans_glob(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-006: 無引數時掃描 openspec/changes/*/proposal.md。"""
        proposal_dir = tmp_path / "openspec" / "changes" / "my-change"
        proposal_dir.mkdir(parents=True)
        proposal = proposal_dir / "proposal.md"
        proposal.write_text("<!-- placeholder -->\n")
        result = _run_script(tmp_path=tmp_path)
        assert result.returncode == 1

    def test_blank_proposal_007_no_args_no_violations_passes(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-007: 無引數且沒有違規時 exit 0。"""
        proposal_dir = tmp_path / "openspec" / "changes" / "my-change"
        proposal_dir.mkdir(parents=True)
        proposal = proposal_dir / "proposal.md"
        proposal.write_text("## Why\n\nFilled in.\n")
        result = _run_script(tmp_path=tmp_path)
        assert result.returncode == 0

    def test_blank_proposal_008_non_proposal_files_ignored(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-008: 無引數時只檢查 proposal.md，忽略其他 md 檔。"""
        proposal_dir = tmp_path / "openspec" / "changes" / "my-change"
        proposal_dir.mkdir(parents=True)
        # 空 proposal.md（但沒有 HTML comment — 只是空白）
        (proposal_dir / "proposal.md").write_text("## Why\n\nFilled.\n")
        # 其他 md 含 HTML comment，不應觸發
        (proposal_dir / "spec.md").write_text("<!-- spec placeholder -->\n")
        result = _run_script(tmp_path=tmp_path)
        assert result.returncode == 0

    def test_blank_proposal_009_empty_file_passes(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-009: 空檔案沒有 HTML comment，通過。"""
        proposal = _write_proposal(tmp_path, "")
        result = _run_script(str(proposal))
        assert result.returncode == 0

    def test_blank_proposal_010_fix_hint_in_stderr(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-010: 錯誤訊息含修復提示。"""
        proposal = _write_proposal(tmp_path, "<!-- placeholder -->\n")
        result = _run_script(str(proposal))
        assert "修復" in result.stderr

    def test_blank_proposal_011_nonexistent_path_fails(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-011: 不存在的路徑回傳 exit 1 並含錯誤訊息。"""
        result = _run_script(str(tmp_path / "proposal.md"))
        assert result.returncode == 1
        assert "無法讀取" in result.stderr

    def test_blank_proposal_012_from_index_reads_staged_content(self, tmp_path: Path) -> None:
        """BLANK-PROPOSAL-012: --from-index 讀取 staged 內容，而非 working tree。"""
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)  # nosec B603 B607
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"],
            check=True,
            capture_output=True,
        )  # nosec B603 B607
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "T"],
            check=True,
            capture_output=True,
        )  # nosec B603 B607

        proposal_rel = Path("openspec") / "changes" / "my-change" / "proposal.md"
        proposal_abs = tmp_path / proposal_rel
        proposal_abs.parent.mkdir(parents=True)

        proposal_abs.write_text("<!-- placeholder -->\n")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", str(proposal_rel)], check=True, capture_output=True
        )  # nosec B603 B607

        # working tree 改成乾淨版本（模擬 partial staging）
        proposal_abs.write_text("## Filled content\n")

        # --from-index 讀 staged 版本（含 placeholder），應 fail
        result = _run_script(str(proposal_rel), "--from-index", tmp_path=tmp_path)
        assert result.returncode == 1
        assert "佔位符" in result.stderr

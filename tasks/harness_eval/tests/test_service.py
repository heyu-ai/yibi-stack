"""harness_eval service 整合測試。"""

from pathlib import Path

from tasks.harness_eval.models import ScanOutput
from tasks.harness_eval.service import run_scan


class TestRunScan:
    def test_heval_st_001_returns_scan_output(self, tmp_path: Path) -> None:
        """HEVAL-ST-001: run_scan 回傳 ScanOutput。"""
        assert isinstance(run_scan(tmp_path), ScanOutput)

    def test_heval_st_002_ten_dimensions(self, tmp_path: Path) -> None:
        """HEVAL-ST-002: 結果含 D1~D11 共 11 個維度。"""
        result = run_scan(tmp_path)
        expected = {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11"}
        assert {d.dimension for d in result.dimensions} == expected

    def test_heval_st_003_total_max_is_69(self, tmp_path: Path) -> None:
        """HEVAL-ST-003: 機械總滿分固定為 77（D11 加入後）。

        D1=8 + D2=13 + D3=6 + D4=8 + D5=7 + D6=6 + D7=7 + D8=7 + D9=4 + D10=3 + D11=8
        """
        assert run_scan(tmp_path).total_mechanical_max == 77

    def test_heval_st_004_target_dir_recorded(self, tmp_path: Path) -> None:
        """HEVAL-ST-004: target_dir 與傳入路徑一致（resolved）。"""
        result = run_scan(tmp_path)
        assert result.target_dir == str(tmp_path.resolve())

    def test_heval_st_005_empty_repo_low_score(self, tmp_path: Path) -> None:
        """HEVAL-ST-005: 空目錄機械分 < 20。"""
        assert run_scan(tmp_path).total_mechanical < 20

    def test_heval_st_006_json_serializable(self, tmp_path: Path) -> None:
        """HEVAL-ST-006: ScanOutput 可 JSON 往返。"""
        result = run_scan(tmp_path)
        restored = ScanOutput.model_validate_json(result.model_dump_json())
        assert len(restored.dimensions) == 11

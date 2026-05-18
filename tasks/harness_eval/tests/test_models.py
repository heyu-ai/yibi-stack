"""harness_eval 資料模型測試。"""

import pytest
from pydantic import ValidationError

from tasks.harness_eval.models import DimensionStatus, MechanicalFinding, ScanOutput


class TestDimensionStatus:
    def test_heval_vl_001_enum_values(self) -> None:
        """HEVAL-VL-001: DimensionStatus 含 pass/warn/fail 三值。"""
        assert str(DimensionStatus.PASS) == "pass"
        assert str(DimensionStatus.WARN) == "warn"
        assert str(DimensionStatus.FAIL) == "fail"


class TestMechanicalFinding:
    def test_heval_vl_002_defaults(self) -> None:
        """HEVAL-VL-002: MechanicalFinding 有合理預設值。"""
        f = MechanicalFinding(dimension="D1", label="test", score=3, max_score=6)
        assert f.findings == []
        assert f.semantic_targets == []

    def test_heval_vl_003_findings_list(self) -> None:
        """HEVAL-VL-003: findings 支援任意字串清單。"""
        f = MechanicalFinding(
            dimension="D1",
            label="test",
            score=6,
            max_score=6,
            findings=["CLAUDE.md 存在", "147 行"],
        )
        assert len(f.findings) == 2

    def test_heval_vl_004_score_not_negative(self) -> None:
        """HEVAL-VL-004: score 不可為負數。"""
        with pytest.raises(ValidationError):
            MechanicalFinding(dimension="D1", label="test", score=-1, max_score=6)


class TestScanOutput:
    def test_heval_vl_005_total_computation(self) -> None:
        """HEVAL-VL-005: total_mechanical = sum of all dimension scores。"""
        d1 = MechanicalFinding(dimension="D1", label="CLAUDE.md", score=4, max_score=6)
        d2 = MechanicalFinding(dimension="D2", label="Hooks", score=8, max_score=12)
        out = ScanOutput(
            target_dir="/tmp/test",
            scanned_at="2026-05-18T00:00:00",
            dimensions=[d1, d2],
        )
        assert out.total_mechanical == 12
        assert out.total_mechanical_max == 18

    def test_heval_vl_006_json_roundtrip(self) -> None:
        """HEVAL-VL-006: ScanOutput JSON 往返一致。"""
        d1 = MechanicalFinding(dimension="D1", label="CLAUDE.md", score=4, max_score=6)
        out = ScanOutput(
            target_dir="/tmp/test",
            scanned_at="2026-05-18T00:00:00",
            dimensions=[d1],
        )
        json_str = out.model_dump_json()
        restored = ScanOutput.model_validate_json(json_str)
        assert restored.target_dir == "/tmp/test"
        assert restored.dimensions[0].score == 4

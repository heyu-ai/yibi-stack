"""Control log service 測試（CTL-ST-001~016, CTL-DT-001~011）。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from tasks.mycelium.control_log_service import (
    compute_grouped_stats,
    compute_stats,
    generate_advice,
    read_control_log,
    write_control_log,
)
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.models import ControlLogCategory, ControlLogEntry


def make_entry(db_path: Path, **kwargs: object) -> int:
    defaults: dict[str, object] = {
        "pr_number": 1,
        "category": ControlLogCategory.autonomous_decision,
        "summary": "test decision",
        "user_requested": 0,
    }
    entry = ControlLogEntry(**{**defaults, **kwargs})
    return write_control_log(entry, db_path=db_path)


class TestWriteReadControlLog:
    def test_ctl_st_001_write_single_entry(self, tmp_path: Path) -> None:
        """CTL-ST-001: write_control_log 寫入單筆 entry 回傳正整數 id。"""
        db = tmp_path / "t.db"
        entry = ControlLogEntry(
            pr_number=42,
            category=ControlLogCategory.autonomous_decision,
            summary="Chose SQLite WAL mode",
            user_requested=0,
        )
        new_id = write_control_log(entry, db_path=db)
        assert isinstance(new_id, int)
        assert new_id > 0

    def test_ctl_st_002_read_returns_written_entry(self, tmp_path: Path) -> None:
        """CTL-ST-002: read_control_log 回傳 write_control_log 寫入的 entry。"""
        db = tmp_path / "t.db"
        entry = ControlLogEntry(
            pr_number=7,
            category=ControlLogCategory.tradeoff,
            summary="Skip unit tests for speed",
            user_requested=0,
        )
        write_control_log(entry, db_path=db)
        rows = read_control_log(7, db_path=db)
        assert len(rows) == 1
        assert rows[0]["summary"] == "Skip unit tests for speed"
        assert rows[0]["category"] == "tradeoff"

    def test_ctl_st_003_read_filters_by_pr(self, tmp_path: Path) -> None:
        """CTL-ST-003: read_control_log 只回傳指定 pr_number 的 entries。"""
        db = tmp_path / "t.db"
        for pr in [1, 2, 1]:
            make_entry(db, pr_number=pr, summary=f"entry for pr {pr}")
        rows = read_control_log(1, db_path=db)
        assert len(rows) == 2
        assert all(r["pr_number"] == 1 for r in rows)

    def test_ctl_vl_002_optional_fields_default_null(self, tmp_path: Path) -> None:
        """CTL-VL-002: 只傳必填欄位時，選填欄位存為 NULL。"""
        db = tmp_path / "t.db"
        entry = ControlLogEntry(
            pr_number=5,
            category=ControlLogCategory.assumption,
            summary="S",
            user_requested=0,
        )
        write_control_log(entry, db_path=db)
        rows = read_control_log(5, db_path=db)
        r = rows[0]
        assert r["evidence"] is None
        assert r["severity"] is None
        assert r["verification_status"] is None
        assert r["test_type"] is None
        assert r["handover_id"] is None

    def test_ctl_vl_003_all_optional_fields_stored(self, tmp_path: Path) -> None:
        """CTL-VL-003: 傳入所有選填欄位時，全部正確儲存。"""
        db = tmp_path / "t.db"
        entry = ControlLogEntry(
            pr_number=42,
            category=ControlLogCategory.verification,
            summary="Ran smoke test",
            user_requested=1,
            evidence="pytest output",
            severity="low",
            files=["tasks/mycelium/cli.py"],
            verification_status="verified",
            test_type="unit",
            handover_id="abc123",
            project="yibi-stack",
        )
        write_control_log(entry, db_path=db)
        rows = read_control_log(42, db_path=db)
        r = rows[0]
        assert r["evidence"] == "pytest output"
        assert r["severity"] == "low"
        assert r["verification_status"] == "verified"
        assert r["test_type"] == "unit"
        assert r["handover_id"] == "abc123"
        assert r["project"] == "yibi-stack"


class TestComputeStats:
    def test_ctl_st_014_autonomy_ratio_calculation(self, tmp_path: Path) -> None:
        """CTL-ST-014: autonomy_ratio = autonomous / (autonomous + user_requested=1)。"""
        db = tmp_path / "t.db"
        for _ in range(2):
            make_entry(db, category=ControlLogCategory.autonomous_decision, user_requested=0)
        for _ in range(6):
            make_entry(db, category=ControlLogCategory.assumption, user_requested=1)
        stats = compute_stats(since_days=30, db_path=db)
        assert stats["autonomy_ratio"] == pytest.approx(2 / 8)

    def test_ctl_dt_001_autonomy_zero_denominator_returns_none(self, tmp_path: Path) -> None:
        """CTL-DT-001: autonomous_decision=0, user_requested=0 時 autonomy_ratio 為 None。"""
        db = tmp_path / "t.db"
        make_entry(db, category=ControlLogCategory.assumption, user_requested=0)
        stats = compute_stats(since_days=30, db_path=db)
        assert stats["autonomy_ratio"] is None

    def test_ctl_dt_003_autonomy_full_autonomous(self, tmp_path: Path) -> None:
        """CTL-DT-003: 全部為 autonomous_decision, user_requested=0 → ratio=1.0。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.autonomous_decision, user_requested=0)
        stats = compute_stats(since_days=30, db_path=db)
        assert stats["autonomy_ratio"] == pytest.approx(1.0)

    def test_ctl_dt_005_empty_window_all_none(self, tmp_path: Path) -> None:
        """CTL-DT-005: 空 DB，四個指標均為 None，irreversible_op_count=0，total_entries=0。"""
        db = tmp_path / "t.db"
        db_obj = AgentsDB(db)
        db_obj.init_db()
        db_obj.close()
        stats = compute_stats(since_days=30, db_path=db)
        assert stats["total_entries"] == 0
        assert stats["autonomy_ratio"] is None
        assert stats["deviation_ratio"] is None
        assert stats["verification_score"] is None
        assert stats["irreversible_op_count"] == 0

    def test_ctl_st_015_grouped_by_category(self, tmp_path: Path) -> None:
        """CTL-ST-015: compute_grouped_stats by=category 回傳各類別計數。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.assumption)
        for _ in range(2):
            make_entry(db, category=ControlLogCategory.autonomous_decision)
        result = compute_grouped_stats(since_days=30, by="category", db_path=db)
        groups = {r["group"]: r["count"] for r in result}
        assert groups["assumption"] == 3
        assert groups["autonomous_decision"] == 2

    def test_ctl_st_016_grouped_by_project(self, tmp_path: Path) -> None:
        """CTL-ST-016: compute_grouped_stats by=project 回傳各 project 計數。"""
        db = tmp_path / "t.db"
        for _ in range(2):
            make_entry(db, project="proj-a")
        make_entry(db, project="proj-b")
        result = compute_grouped_stats(since_days=30, by="project", db_path=db)
        groups = {r["group"]: r["count"] for r in result}
        assert groups["proj-a"] == 2
        assert groups["proj-b"] == 1


class TestGenerateAdvice:
    def test_ctl_dt_002_r1_fires_above_threshold(self, tmp_path: Path) -> None:
        """CTL-DT-002: autonomy_ratio > 0.30 觸發 R1。"""
        db = tmp_path / "t.db"
        for _ in range(4):
            make_entry(db, category=ControlLogCategory.autonomous_decision, user_requested=0)
        for _ in range(6):
            make_entry(db, category=ControlLogCategory.assumption, user_requested=1)
        advice = generate_advice(since_days=30, db_path=db)
        assert any("R1" in a for a in advice)

    def test_ctl_dt_004_r2_fires_above_threshold(self, tmp_path: Path) -> None:
        """CTL-DT-004: deviation_ratio > 0.20 觸發 R2。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.spec_deviation)
        for _ in range(7):
            make_entry(db, category=ControlLogCategory.assumption)
        advice = generate_advice(since_days=30, db_path=db)
        assert any("R2" in a for a in advice)

    def test_ctl_dt_006_r1_not_fires_at_boundary(self, tmp_path: Path) -> None:
        """CTL-DT-006: autonomy_ratio = 0.30 不觸發 R1（嚴格大於）。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.autonomous_decision, user_requested=0)
        for _ in range(7):
            make_entry(db, category=ControlLogCategory.assumption, user_requested=1)
        advice = generate_advice(since_days=30, db_path=db)
        assert not any("R1" in a for a in advice)

    def test_ctl_dt_008_r4_fires_below_threshold(self, tmp_path: Path) -> None:
        """CTL-DT-008: verification_score < 0.60 觸發 R4。"""
        db = tmp_path / "t.db"
        for _ in range(5):
            make_entry(
                db, category=ControlLogCategory.verification, verification_status="unverified"
            )
        for _ in range(5):
            make_entry(db, category=ControlLogCategory.verification, verification_status="verified")
        advice = generate_advice(since_days=30, db_path=db)
        assert any("R4" in a for a in advice)

    def test_ctl_dt_010_no_advice_all_within_threshold(self, tmp_path: Path) -> None:
        """CTL-DT-010: 所有指標在閾值內，回傳 ['目前無建議']。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.assumption, user_requested=0)
        advice = generate_advice(since_days=30, db_path=db)
        assert advice == ["目前無建議"]

    def test_ctl_dt_011_insufficient_data(self, tmp_path: Path) -> None:
        """CTL-DT-011: < 3 筆時回傳資料不足提示，不評估閾值。"""
        db = tmp_path / "t.db"
        make_entry(db, category=ControlLogCategory.autonomous_decision, user_requested=0)
        make_entry(db, category=ControlLogCategory.autonomous_decision, user_requested=0)
        advice = generate_advice(since_days=30, db_path=db)
        assert len(advice) == 1
        assert "資料不足" in advice[0]
        assert not any("R1" in a or "R2" in a or "R4" in a for a in advice)

    def test_ctl_vl_004_r3_fires_same_pattern_three_times(self, tmp_path: Path) -> None:
        """CTL-VL-004: 相同 irreversible_op summary 出現 >= 3 次觸發 R3。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.irreversible_op, summary="git push --force")
        advice = generate_advice(since_days=30, db_path=db)
        assert any("R3" in a for a in advice)

    def test_ctl_dt_007_r3_not_fires_below_three(self, tmp_path: Path) -> None:
        """CTL-DT-007: 相同 irreversible_op summary 出現 2 次不觸發 R3（< 3）。"""
        db = tmp_path / "t.db"
        for _ in range(2):
            make_entry(db, category=ControlLogCategory.irreversible_op, summary="git push --force")
        make_entry(db, category=ControlLogCategory.assumption)
        advice = generate_advice(since_days=30, db_path=db)
        assert not any("R3" in a for a in advice)

    def test_ctl_dt_009_r3_not_fires_no_irreversible_entries(self, tmp_path: Path) -> None:
        """CTL-DT-009: DB 無 irreversible_op entries 時不觸發 R3。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.assumption)
        advice = generate_advice(since_days=30, db_path=db)
        assert not any("R3" in a for a in advice)

    def test_ctl_eg_001_r1_skipped_when_autonomy_ratio_none(self, tmp_path: Path) -> None:
        """CTL-EG-001: autonomy_ratio=None 不觸發 R1。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.assumption, user_requested=0)
        stats = compute_stats(since_days=30, db_path=db)
        assert stats["autonomy_ratio"] is None
        advice = generate_advice(since_days=30, db_path=db)
        assert not any("R1" in a for a in advice)

    def test_ctl_eg_002_r4_skipped_when_verification_score_none(self, tmp_path: Path) -> None:
        """CTL-EG-002: verification_score=None（無驗證欄位）不觸發 R4。"""
        db = tmp_path / "t.db"
        for _ in range(3):
            make_entry(db, category=ControlLogCategory.assumption, verification_status=None)
        stats = compute_stats(since_days=30, db_path=db)
        assert stats["verification_score"] is None
        advice = generate_advice(since_days=30, db_path=db)
        assert not any("R4" in a for a in advice)

    def test_ctl_eg_003_grouped_stats_empty_returns_empty_list(self, tmp_path: Path) -> None:
        """CTL-EG-003: DB 空時 compute_grouped_stats 回傳空 list。"""
        db = tmp_path / "t.db"
        db_obj = AgentsDB(db)
        db_obj.init_db()
        db_obj.close()
        result = compute_grouped_stats(since_days=30, by="category", db_path=db)
        assert result == []

    def test_ctl_dt_012_r2_not_fires_at_boundary(self, tmp_path: Path) -> None:
        """CTL-DT-012: deviation_ratio = 0.20 不觸發 R2（嚴格大於）。"""
        db = tmp_path / "t.db"
        for _ in range(2):
            make_entry(db, category=ControlLogCategory.spec_deviation)
        for _ in range(8):
            make_entry(db, category=ControlLogCategory.assumption)
        advice = generate_advice(since_days=30, db_path=db)
        assert not any("R2" in a for a in advice)

    def test_ctl_dt_013_r4_not_fires_at_boundary(self, tmp_path: Path) -> None:
        """CTL-DT-013: verification_score = 0.60 不觸發 R4（嚴格小於）。"""
        db = tmp_path / "t.db"
        for _ in range(6):
            make_entry(db, category=ControlLogCategory.verification, verification_status="verified")
        for _ in range(4):
            make_entry(
                db, category=ControlLogCategory.verification, verification_status="unverified"
            )
        advice = generate_advice(since_days=30, db_path=db)
        assert not any("R4" in a for a in advice)

    def test_ctl_eg_004_r3_normalization_case_insensitive(self, tmp_path: Path) -> None:
        """CTL-EG-004: _normalize_summary 統一大小寫讓 'Git Push' 和 'git push' 算同一 pattern。"""
        db = tmp_path / "t.db"
        for summary in ["Git Push --Force", "git push --force", "GIT PUSH --FORCE"]:
            make_entry(db, category=ControlLogCategory.irreversible_op, summary=summary)
        advice = generate_advice(since_days=30, db_path=db)
        assert any("R3" in a for a in advice)

    def test_ctl_eg_005_time_window_excludes_old_entries(self, tmp_path: Path) -> None:
        """CTL-EG-005: since_days 窗口外的 entry 不計入統計。"""
        db = tmp_path / "t.db"
        from datetime import timedelta

        old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        make_entry(db, category=ControlLogCategory.autonomous_decision, user_requested=0)
        db_obj = AgentsDB(db)
        db_obj.init_db()
        db_obj.conn.execute("UPDATE control_log_entries SET created_at = ?", (old_ts,))
        db_obj.conn.commit()
        db_obj.close()
        stats = compute_stats(since_days=30, db_path=db)
        assert stats["total_entries"] == 0


class TestControlLogEntryValidation:
    def test_ctl_vl_005_user_requested_invalid_raises(self) -> None:
        """CTL-VL-005: user_requested 非 0/1 觸發 ValidationError。"""
        with pytest.raises(ValidationError):
            ControlLogEntry(
                pr_number=1,
                category=ControlLogCategory.assumption,
                summary="test",
                user_requested=2,
            )

    def test_ctl_vl_006_severity_invalid_raises(self) -> None:
        """CTL-VL-006: severity 非 low/medium/high 觸發 ValidationError。"""
        with pytest.raises(ValidationError):
            ControlLogEntry(
                pr_number=1,
                category=ControlLogCategory.assumption,
                summary="test",
                user_requested=0,
                severity="critical",
            )

    def test_ctl_vl_007_verification_status_invalid_raises(self) -> None:
        """CTL-VL-007: verification_status 非 verified/partial/unverified 觸發 ValidationError。"""
        with pytest.raises(ValidationError):
            ControlLogEntry(
                pr_number=1,
                category=ControlLogCategory.assumption,
                summary="test",
                user_requested=0,
                verification_status="done",
            )

    def test_ctl_vl_008_test_type_invalid_raises(self) -> None:
        """CTL-VL-008: test_type 非有效值觸發 ValidationError。"""
        with pytest.raises(ValidationError):
            ControlLogEntry(
                pr_number=1,
                category=ControlLogCategory.assumption,
                summary="test",
                user_requested=0,
                test_type="smoke",
            )

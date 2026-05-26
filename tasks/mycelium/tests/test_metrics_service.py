"""測試 metrics_service：事件記錄、統計聚合、rule-based 建議。"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.metrics_service import (
    _append_jsonl,
    compute_stats,
    generate_advice,
    list_events,
    log_event,
)
from tasks.mycelium.models import EventType, HandoverEvent, MetricsReport, SourceLayer

_skip_if_root = pytest.mark.skipif(
    os.getuid() == 0,
    reason="root 無視 chmod 限制，唯讀目錄測試需非 root 身份執行",
)

# ── 測試資料工廠 ───────────────────────────────────────────────────────────────


def make_event(**overrides: object) -> HandoverEvent:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).astimezone().replace(microsecond=0).isoformat(),
        "session_id": "sess-001",
        "event_type": EventType.layer2_intercept,
        "source_layer": SourceLayer.layer2,
    }
    return HandoverEvent.model_validate({**defaults, **overrides})


def insert_events(db: AgentsDB, events: list[HandoverEvent]) -> None:
    for e in events:
        db.insert_event(e)


# ── log_event ─────────────────────────────────────────────────────────────────


class TestLogEvent:
    def test_metrics_st_001_write_and_read_back(self, tmp_path: Path) -> None:
        """METRICS-ST-001: log_event 寫入後可從 DB 讀回。"""
        db_path = tmp_path / "ev.db"
        jsonl_path = tmp_path / "ev.jsonl"
        result = log_event(
            EventType.layer2_intercept,
            session_id="sess-abc",
            source_layer=SourceLayer.layer2,
            db_path=db_path,
            jsonl_path=jsonl_path,
        )
        assert result is not None
        assert result.event_type == EventType.layer2_intercept

        rows = list_events(db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "layer2_intercept"
        assert rows[0]["session_id"] == "sess-abc"

    def test_metrics_st_002_jsonl_backup_written(self, tmp_path: Path) -> None:
        """METRICS-ST-002: log_event 同時寫入 JSONL 備份。"""
        db_path = tmp_path / "ev.db"
        jsonl_path = tmp_path / "ev.jsonl"
        log_event(
            EventType.handover_written,
            session_id="sess-xyz",
            db_path=db_path,
            jsonl_path=jsonl_path,
        )
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "handover_written"

    def test_metrics_eg_001_invalid_event_type_returns_none(self, tmp_path: Path) -> None:
        """METRICS-EG-001: 非法 event_type 回傳 None，不 raise。"""
        with pytest.warns(UserWarning, match="not_a_valid_event"):
            result = log_event(
                "not_a_valid_event",
                db_path=tmp_path / "ev.db",
                jsonl_path=tmp_path / "ev.jsonl",
            )
        assert result is None

    @_skip_if_root
    def test_metrics_eg_002_broken_db_returns_none_with_warning(self, tmp_path: Path) -> None:
        """METRICS-EG-002: DB 不可寫時回傳 None 並發出 UserWarning，不 raise。"""
        import stat

        bad_dir = tmp_path / "ro_dir"
        bad_dir.mkdir()
        bad_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # 唯讀目錄，無法在裡面建立檔案
        bad_db = bad_dir / "ev.db"
        try:
            with pytest.warns(UserWarning, match="DB 寫入失敗"):
                result = log_event(
                    EventType.layer2_intercept,
                    db_path=bad_db,
                    jsonl_path=tmp_path / "ev.jsonl",
                )
            assert result is None
        finally:
            bad_dir.chmod(stat.S_IRWXU)  # 還原權限讓 pytest 清理 tmp_path


# ── list_events ───────────────────────────────────────────────────────────────


class TestListEvents:
    def test_metrics_st_010_filter_by_session_id(self, tmp_path: Path) -> None:
        """METRICS-ST-010: list_events 依 session_id 過濾。"""
        db_path = tmp_path / "ev.db"
        db = AgentsDB(db_path)
        db.init_db()
        insert_events(
            db,
            [
                make_event(id="e1", session_id="s1", event_type=EventType.layer2_intercept),
                make_event(id="e2", session_id="s2", event_type=EventType.handover_written),
            ],
        )
        db.close()

        rows = list_events(session_id="s1", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["session_id"] == "s1"

    def test_metrics_st_011_filter_by_event_type(self, tmp_path: Path) -> None:
        """METRICS-ST-011: list_events 依 event_type 過濾。"""
        db_path = tmp_path / "ev.db"
        db = AgentsDB(db_path)
        db.init_db()
        insert_events(
            db,
            [
                make_event(id="e1", event_type=EventType.layer2_intercept),
                make_event(id="e2", event_type=EventType.handover_written),
                make_event(id="e3", event_type=EventType.handover_written),
            ],
        )
        db.close()

        rows = list_events(event_type=EventType.handover_written, db_path=db_path)
        assert len(rows) == 2

    def test_metrics_eg_010_last_zero_raises(self, tmp_path: Path) -> None:
        """METRICS-EG-010: last=0 raise ValueError。"""
        db_path = tmp_path / "ev.db"
        with pytest.raises(ValueError, match="正整數"):
            list_events(last=0, db_path=db_path)


# ── aggregate_success_counts（透過 compute_stats）─────────────────────────────


class TestComputeStats:
    def _setup_db(self, tmp_path: Path, events: list[HandoverEvent]) -> Path:
        db_path = tmp_path / "ev.db"
        db = AgentsDB(db_path)
        db.init_db()
        insert_events(db, events)
        db.close()
        return db_path

    def test_metrics_dt_001_empty_db_returns_zeros(self, tmp_path: Path) -> None:
        """METRICS-DT-001: 空 DB 回傳全零 MetricsReport。"""
        db_path = self._setup_db(tmp_path, [])
        report = compute_stats(db_path=db_path)
        assert report.total_intercepts == 0
        assert report.sessions_observed == 0

    def test_metrics_dt_002_wrote_after_intercept(self, tmp_path: Path) -> None:
        """METRICS-DT-002: 同 session 有 intercept + handover_written → wrote_after_intercept=1。"""
        ts_base = datetime.now(UTC) - timedelta(hours=1)
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(
                    id="e1",
                    session_id="s1",
                    event_type=EventType.layer2_intercept,
                    timestamp=ts_base.isoformat(),
                ),
                make_event(
                    id="e2",
                    session_id="s1",
                    event_type=EventType.handover_written,
                    timestamp=(ts_base + timedelta(minutes=1)).isoformat(),
                ),
            ],
        )
        report = compute_stats(db_path=db_path)
        assert report.wrote_after_intercept == 1
        assert report.silent_fail == 0

    def test_metrics_dt_003_silent_fail(self, tmp_path: Path) -> None:
        """METRICS-DT-003: intercept + passthrough 無 handover_written → silent_fail=1。"""
        ts = datetime.now(UTC) - timedelta(hours=1)
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(
                    id="e1",
                    session_id="s1",
                    event_type=EventType.layer2_intercept,
                    timestamp=ts.isoformat(),
                ),
                make_event(
                    id="e2",
                    session_id="s1",
                    event_type=EventType.layer2_passthrough,
                    timestamp=(ts + timedelta(minutes=5)).isoformat(),
                ),
            ],
        )
        report = compute_stats(db_path=db_path)
        assert report.silent_fail == 1
        assert report.wrote_after_intercept == 0

    def test_metrics_dt_004_hard_fail(self, tmp_path: Path) -> None:
        """METRICS-DT-004: layer3_session_start 無 handover_written → hard_fail=1。"""
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(id="e1", session_id="s1", event_type=EventType.layer3_session_start),
            ],
        )
        report = compute_stats(db_path=db_path)
        assert report.hard_fail == 1

    def test_metrics_dt_005_layer1_win(self, tmp_path: Path) -> None:
        """METRICS-DT-005: handover_written 但無 layer2_intercept → layer1_win=1。"""
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(id="e1", session_id="s1", event_type=EventType.handover_written),
            ],
        )
        report = compute_stats(db_path=db_path)
        assert report.layer1_win == 1
        assert report.wrote_after_intercept == 0

    def test_metrics_dt_006_null_session_excluded(self, tmp_path: Path) -> None:
        """METRICS-DT-006: session_id IS NULL 的事件不列入聚合。"""
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(id="e1", session_id=None, event_type=EventType.layer2_intercept),
            ],
        )
        report = compute_stats(db_path=db_path)
        assert report.sessions_observed == 0

    def test_metrics_dt_007_stale_resetsed(self, tmp_path: Path) -> None:
        """METRICS-DT-007: layer2_stale_reset 事件計入 stale_resets。"""
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(id="e1", session_id="s1", event_type=EventType.layer2_stale_reset),
            ],
        )
        report = compute_stats(db_path=db_path)
        assert report.stale_resets == 1

    def test_metrics_dt_008_project_filter(self, tmp_path: Path) -> None:
        """METRICS-DT-008: project 參數只聚合符合的事件。"""
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(
                    id="e1",
                    session_id="s1",
                    event_type=EventType.handover_written,
                    project="proj-a",
                ),
                make_event(
                    id="e2",
                    session_id="s2",
                    event_type=EventType.handover_written,
                    project="proj-b",
                ),
            ],
        )
        report = compute_stats(project="proj-a", db_path=db_path)
        assert report.sessions_observed == 1
        assert report.layer1_win == 1

    def test_metrics_cv_001_success_rate_calculation(self, tmp_path: Path) -> None:
        """METRICS-CV-001: success_rate = (wrote + layer1_win) / sessions_observed。"""
        ts = datetime.now(UTC) - timedelta(hours=1)
        # sess-1: intercept + wrote（成功）; sess-2: layer1 win（成功）; sess-3: silent fail
        db_path = self._setup_db(
            tmp_path,
            [
                make_event(
                    id="e1",
                    session_id="s1",
                    event_type=EventType.layer2_intercept,
                    timestamp=ts.isoformat(),
                ),
                make_event(
                    id="e2",
                    session_id="s1",
                    event_type=EventType.handover_written,
                    timestamp=(ts + timedelta(minutes=1)).isoformat(),
                ),
                make_event(
                    id="e3",
                    session_id="s2",
                    event_type=EventType.handover_written,
                    timestamp=ts.isoformat(),
                ),
                make_event(
                    id="e4",
                    session_id="s3",
                    event_type=EventType.layer2_intercept,
                    timestamp=ts.isoformat(),
                ),
                make_event(
                    id="e5",
                    session_id="s3",
                    event_type=EventType.layer2_passthrough,
                    timestamp=(ts + timedelta(minutes=5)).isoformat(),
                ),
            ],
        )
        report = compute_stats(db_path=db_path)
        assert report.sessions_observed == 3
        assert report.wrote_after_intercept == 1
        assert report.layer1_win == 1
        assert report.silent_fail == 1
        # success_rate = (1+1)/3
        assert abs(report.success_rate - round(2 / 3, 4)) < 1e-6


# ── generate_advice ───────────────────────────────────────────────────────────


class TestGenerateAdvice:
    def test_metrics_dt_020_insufficient_samples(self) -> None:
        """METRICS-DT-020: sessions_observed < 5 → 回傳「資料不足」。"""
        report = MetricsReport(sessions_observed=3)
        advice = generate_advice(report)
        assert len(advice) == 1
        assert "樣本不足" in advice[0]

    def test_metrics_dt_021_high_silent_fail_rate(self) -> None:
        """METRICS-DT-021: silent_fail_rate > 30% → 建議強化 Layer 2 語氣。"""
        report = MetricsReport(
            sessions_observed=10,
            total_intercepts=10,
            silent_fail=4,
            silent_fail_rate=0.40,
        )
        advice = generate_advice(report)
        assert any("Silent-fail" in a for a in advice)

    def test_metrics_dt_022_high_hard_fail_rate(self) -> None:
        """METRICS-DT-022: hard_fail_rate > 10% → 建議縮短 TTL。"""
        report = MetricsReport(
            sessions_observed=10,
            hard_fail=2,
            hard_fail_rate=0.20,
        )
        advice = generate_advice(report)
        assert any("Hard-fail" in a for a in advice)

    def test_metrics_dt_023_high_layer1_win_rate(self) -> None:
        """METRICS-DT-023: layer1_win_rate > 50% → 建議降低 70% 閾值。"""
        report = MetricsReport(
            sessions_observed=10,
            layer1_win=6,
            layer1_win_rate=0.60,
        )
        advice = generate_advice(report)
        assert any("Layer 1" in a and "50%" in a for a in advice)

    def test_metrics_dt_024_low_layer1_win_rate(self) -> None:
        """METRICS-DT-024: layer1_win_rate < 10% 且樣本 > 20 → 建議放寬觸發條件。"""
        report = MetricsReport(
            sessions_observed=25,
            layer1_win=1,
            layer1_win_rate=0.04,
        )
        advice = generate_advice(report)
        assert any("< 10%" in a for a in advice)

    def test_metrics_dt_025_no_issues_returns_ok(self) -> None:
        """METRICS-DT-025: 無異常時回傳正常狀態訊息。"""
        report = MetricsReport(
            sessions_observed=20,
            success_rate=0.85,
            silent_fail_rate=0.10,
            hard_fail_rate=0.05,
            layer1_win_rate=0.30,
        )
        advice = generate_advice(report)
        assert len(advice) == 1
        assert "無明顯異常" in advice[0]


# ── _append_jsonl（輔助函式）──────────────────────────────────────────────────


class TestAppendJsonl:
    def test_metrics_eg_020_parent_dir_created_automatically(self, tmp_path: Path) -> None:
        """METRICS-EG-020: 目標目錄不存在時自動建立。"""
        path = tmp_path / "nested" / "dir" / "events.jsonl"
        event = make_event()
        _append_jsonl(event, path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8").strip())
        assert data["id"] == event.id

    def test_metrics_eg_021_multiple_appends(self, tmp_path: Path) -> None:
        """METRICS-EG-021: 多次 append 每次寫一行。"""
        path = tmp_path / "events.jsonl"
        for i in range(3):
            _append_jsonl(make_event(id=f"ev-{i}"), path)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    @_skip_if_root
    def test_metrics_eg_022_oserror_swallowed_with_warning(self, tmp_path: Path) -> None:
        """METRICS-EG-022: 唯讀目錄無法寫入時發出 UserWarning，不 raise。"""
        import stat

        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        path = ro_dir / "events.jsonl"
        try:
            with pytest.warns(UserWarning, match="JSONL 備份寫入失敗"):
                _append_jsonl(make_event(), path)
        finally:
            ro_dir.chmod(stat.S_IRWXU)


# ── compute_stats since filter ─────────────────────────────────────────────────


class TestComputeStatsSinceFilter:
    def test_metrics_dt_009_since_filter_excludes_old_events(self, tmp_path: Path) -> None:
        """METRICS-DT-009: since 參數過濾掉時間範圍外的事件。"""
        from datetime import timedelta

        db_path = tmp_path / "ev.db"
        db = AgentsDB(db_path)
        db.init_db()
        old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        recent_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        insert_events(
            db,
            [
                # 60 天前的事件，超出 30 天 window
                make_event(
                    id="old1",
                    session_id="s-old",
                    event_type=EventType.handover_written,
                    timestamp=old_ts,
                ),
                # 近期事件
                make_event(
                    id="new1",
                    session_id="s-new",
                    event_type=EventType.handover_written,
                    timestamp=recent_ts,
                ),
            ],
        )
        db.close()

        # since = 7 天前，只應看到 s-new
        cutoff = datetime.now(UTC) - timedelta(days=7)
        report = compute_stats(since=cutoff, db_path=db_path)
        assert report.sessions_observed == 1
        assert report.layer1_win == 1


# ── generate_advice stale_reset branch ────────────────────────────────────────


class TestGenerateAdviceStaleReset:
    def test_metrics_dt_026_high_stale_reset_rate(self) -> None:
        """METRICS-DT-026: stale_resets > total_intercepts*20% → 建議調整 TTL。"""
        report = MetricsReport(
            sessions_observed=10,
            total_intercepts=10,
            stale_resets=3,
        )
        advice = generate_advice(report)
        assert any("過期" in a for a in advice)

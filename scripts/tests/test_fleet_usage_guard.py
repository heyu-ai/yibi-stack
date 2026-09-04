"""FUG: fleet-usage-guard 的 transcript 成本估算與觸發測試。

Test ID 規則見 .claude/rules/09-test-conventions.md。

覆蓋對映（Issue #421）：
- 06:00 UTC 已知高用量小時 $216.78/hr：FUG-DT-001
- 04:00 UTC 已知低用量小時 $0.54/hr：FUG-DT-002
- (message.id, requestId) 去重不可移除：FUG-DT-003
- Claude Fable 5.1 cache-read 特價與視窗外推：FUG-DT-004 / FUG-DT-005
- 未定價 model 不得靜默通過：FUG-EG-001
- CLI 輸出可供 skill 決定廣播，且設定缺失會 fail loud：FUG-ST-001 / FUG-VL-001
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    REPO_ROOT
    / "plugins"
    / "harness"
    / "skills"
    / "fleet-usage-guard"
    / "scripts"
    / "fleet_usage_guard.py"
)
_FIXTURES = Path(__file__).parent / "fixtures" / "fleet_usage_guard"

_spec = importlib.util.spec_from_file_location("fleet_usage_guard", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
fleet_usage_guard = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("fleet_usage_guard", fleet_usage_guard)
_spec.loader.exec_module(fleet_usage_guard)


def _at(hour: int) -> datetime:
    return datetime(2026, 9, 3, hour, tzinfo=UTC)


def _write_usage_row(
    path: Path,
    *,
    model: str,
    cache_read_tokens: int,
    message_id: str = "msg_test",
    request_id: str = "req_test",
) -> None:
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": cache_read_tokens,
        "cache_creation_input_tokens": 0,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 0,
            "ephemeral_1h_input_tokens": 0,
        },
    }
    row = {
        "type": "assistant",
        "timestamp": "2026-09-03T06:30:00Z",
        "requestId": request_id,
        "message": {
            "id": message_id,
            "model": model,
            "role": "assistant",
            "content": [],
            "usage": usage,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


class TestKnownHourlyControls:
    def test_fug_dt_001_high_usage_hour_triggers_at_known_cost(self) -> None:
        """FUG-DT-001: 06:00 UTC replay 為 $216.78/hr，超過 $50/hr。"""
        result = fleet_usage_guard.evaluate_burn_rate(
            _FIXTURES,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.status == "burn_rate_exceeded"
        assert result.estimated_cost_usd == Decimal("216.78")
        assert result.estimated_usd_per_hour == Decimal("216.78")

    def test_fug_dt_002_low_usage_hour_does_not_trigger(self) -> None:
        """FUG-DT-002: 04:00 UTC replay 為 $0.54/hr，不得誤觸發。"""
        result = fleet_usage_guard.evaluate_burn_rate(
            _FIXTURES,
            now=_at(5),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.status == "below_threshold"
        assert result.estimated_cost_usd == Decimal("0.54")
        assert result.estimated_usd_per_hour == Decimal("0.54")
        assert fleet_usage_guard.build_broadcast_message(result) is None

    def test_fug_dt_003_duplicate_rows_do_not_inflate_known_cost(self) -> None:
        """FUG-DT-003: 移除 request 去重會把 $216.78 高估為 $231.78 並讓此測試變紅。"""
        result = fleet_usage_guard.evaluate_burn_rate(
            _FIXTURES,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.rows_with_usage == 155
        assert result.unique_requests == 145
        assert result.duplicate_rows == 10
        assert result.estimated_cost_usd == Decimal("216.78")


class TestPricingRules:
    def test_fug_dt_004_fable_5_1_cache_read_uses_quarter_standard_rate(
        self, tmp_path: Path
    ) -> None:
        """FUG-DT-004: Fable 5.1 cache read 是 input 的 0.025x，而非標準 0.1x。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-fable-5-1",
            cache_read_tokens=1_000_000,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("1"),
        )

        assert result.status == "below_threshold"
        assert result.estimated_cost_usd == Decimal("0.25")

    def test_fug_dt_005_short_window_extrapolates_to_hourly_rate(self, tmp_path: Path) -> None:
        """FUG-DT-005: 30 分鐘內 $0.25 外推為 $0.50/hr。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-fable-5-1",
            cache_read_tokens=1_000_000,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=datetime(2026, 9, 3, 6, 45, tzinfo=UTC),
            window_minutes=30,
            threshold_usd_per_hour=Decimal("0.4"),
        )

        assert result.status == "burn_rate_exceeded"
        assert result.estimated_cost_usd == Decimal("0.25")
        assert result.estimated_usd_per_hour == Decimal("0.50")

    def test_fug_eg_001_unknown_model_is_measurement_incomplete(self, tmp_path: Path) -> None:
        """FUG-EG-001: 未定價 model 的部分金額不得被當作低於閾值。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-unknown-9000",
            cache_read_tokens=1_000_000,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.status == "measurement_incomplete"
        assert result.unpriced_models == ("claude-unknown-9000",)
        assert fleet_usage_guard.build_broadcast_message(result) is None


class TestSkillContract:
    def test_fug_st_001_cli_emits_distinct_burn_rate_broadcast(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """FUG-ST-001: CLI 超標時以專用 exit code 與 burn-rate 理由交給 skill 廣播。"""
        config = tmp_path / "fleet-usage-guard.json"
        config.write_text(
            json.dumps({"window_minutes": 60, "max_usd_per_hour": 50}),
            encoding="utf-8",
        )

        exit_code = fleet_usage_guard.main(
            [
                "--config",
                str(config),
                "--projects-dir",
                str(_FIXTURES),
                "--now",
                "2026-09-03T07:00:00Z",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == fleet_usage_guard.EXIT_BURN_RATE_EXCEEDED
        assert payload["reason"] == "burn_rate"
        assert payload["estimated_usd_per_hour"] == 216.78
        assert "燒錢速率" in payload["broadcast_message"]
        assert "$216.78/hr" in payload["broadcast_message"]
        assert "不是額度" in payload["broadcast_message"]

    def test_fug_vl_001_missing_config_fails_loud(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """FUG-VL-001: 沒有使用者閾值設定時，不得套用隱藏預設值。"""
        exit_code = fleet_usage_guard.main(
            [
                "--config",
                str(tmp_path / "missing.json"),
                "--projects-dir",
                str(_FIXTURES),
            ]
        )

        payload = json.loads(capsys.readouterr().err)
        assert exit_code == fleet_usage_guard.EXIT_CONFIG_ERROR
        assert payload["status"] == "config_error"
        assert "config not found" in payload["error"]

"""FUG: fleet-usage-guard 的 transcript 成本估算與觸發測試。

Test ID 規則見 .claude/rules/09-test-conventions.md。

覆蓋對映（Issue #421）：
- 06:00 UTC 已知高用量小時 $216.78/hr：FUG-DT-001
- 04:00 UTC 已知低用量小時 $0.54/hr：FUG-DT-002
- (message.id, requestId) 去重不可移除：FUG-DT-003
- Claude Fable 特價／標準價、context suffix、視窗與全 pricing formula：FUG-DT-004..009
- 未定價 model、未知 qualifier、缺欄位與非 object usage 不得靜默通過：FUG-EG-001..004, FUG-EG-007
- 不一致 signature 的重複 request 排除且回報 incomplete：FUG-EG-005
- 高用量超標 + 未定價 model 並存時超標判定不得被 incomplete 壓過：FUG-EG-006
- CLI 輸出可供 skill 決定廣播，設定缺失／時間戳無效會 fail loud：FUG-ST-001..002 / FUG-VL-001
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
_DEFAULT_USAGE = object()

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
    timestamp: str = "2026-09-03T06:30:00Z",
    usage_override: object = _DEFAULT_USAGE,
) -> None:
    usage: object = (
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": 0,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 0,
                "ephemeral_1h_input_tokens": 0,
            },
        }
        if usage_override is _DEFAULT_USAGE
        else usage_override
    )
    row = {
        "type": "assistant",
        "timestamp": timestamp,
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

    def test_fug_dt_006_non_5_1_fable_uses_standard_cache_read_rate(self, tmp_path: Path) -> None:
        """FUG-DT-006: Fable 5.2 不得誤用 5.1 的 0.025x cache-read 特價。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-fable-5-2",
            cache_read_tokens=1_000_000,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("0.5"),
        )

        assert result.status == "burn_rate_exceeded"
        assert result.estimated_cost_usd == Decimal("1.0")

    def test_fug_eg_002_missing_core_counters_is_measurement_incomplete(
        self, tmp_path: Path
    ) -> None:
        """FUG-EG-002: 空 usage object 不得被當成零成本有效 request。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-opus-5",
            cache_read_tokens=0,
            usage_override={},
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.status == "measurement_incomplete"
        assert result.invalid_recent_rows == 1

    def test_fug_dt_007_context_suffix_preserves_fable_5_1_discount(self, tmp_path: Path) -> None:
        """FUG-DT-007: `[1m]` context suffix 不得讓 Fable 5.1 落到標準價。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-fable-5-1[1m]",
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

    def test_fug_eg_004_unknown_model_suffix_is_measurement_incomplete(
        self, tmp_path: Path
    ) -> None:
        """FUG-EG-004: 僅已知 context suffix 可沿用基礎 model 定價。"""
        model = "claude-opus-5[unpriced-preview]"
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model=model,
            cache_read_tokens=1_000_000,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("100"),
        )

        assert result.status == "measurement_incomplete"
        assert result.unpriced_models == (model,)

    def test_fug_eg_007_word_only_qualifier_is_measurement_incomplete(self, tmp_path: Path) -> None:
        """FUG-EG-007: 非數值 context qualifier（如 [beta]）不得沿用基礎 model 定價。"""
        model = "claude-opus-5[beta]"
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model=model,
            cache_read_tokens=1_000_000,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("100"),
        )

        assert result.status == "measurement_incomplete"
        assert result.unpriced_models == (model,)

    def test_fug_dt_009_numeric_context_suffix_inherits_base_pricing(self, tmp_path: Path) -> None:
        """FUG-DT-009: 數值 context suffix（如 [200k]）沿用基礎 model 定價。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-opus-5[200k]",
            cache_read_tokens=1_000_000,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("100"),
        )

        assert result.status == "below_threshold"
        assert result.estimated_cost_usd == Decimal("1.50")

    def test_fug_dt_008_all_pricing_terms_contribute_to_exact_cost(self, tmp_path: Path) -> None:
        """FUG-DT-008: input/output/read/5m-write/1h-write 任何一項消失都會變紅。"""
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
            "cache_creation_input_tokens": 2_000_000,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 1_000_000,
                "ephemeral_1h_input_tokens": 1_000_000,
            },
        }
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-opus-5",
            cache_read_tokens=0,
            usage_override=usage,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("200"),
        )

        assert result.status == "below_threshold"
        assert result.estimated_cost_usd == Decimal("140.25")

    def test_fug_eg_003_non_object_usage_is_measurement_incomplete(self, tmp_path: Path) -> None:
        """FUG-EG-003: `usage: null` 不得被當成沒有 usage 的普通 row。"""
        _write_usage_row(
            tmp_path / "project" / "session.jsonl",
            model="claude-opus-5",
            cache_read_tokens=0,
            usage_override=None,
        )

        result = fleet_usage_guard.evaluate_burn_rate(
            tmp_path,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.status == "measurement_incomplete"
        assert result.invalid_recent_rows == 1


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

    def test_fug_st_002_timezone_less_recent_usage_exits_incomplete(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """FUG-ST-002: 近期 transcript 的 timezone-less timestamp 必須 exit 3。"""
        projects_dir = tmp_path / "projects"
        _write_usage_row(
            projects_dir / "project" / "session.jsonl",
            model="claude-opus-5",
            cache_read_tokens=1_000_000,
            timestamp="2026-09-03T06:30:00",
        )
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
                str(projects_dir),
                "--now",
                "2026-09-03T07:00:00Z",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == fleet_usage_guard.EXIT_MEASUREMENT_INCOMPLETE
        assert payload["status"] == "measurement_incomplete"
        assert payload["invalid_recent_rows"] == 1

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


class TestEdgeCaseDedup:
    def test_fug_eg_005_inconsistent_signatures_excluded_and_flagged(self, tmp_path: Path) -> None:
        """FUG-EG-005: 同 (message.id, requestId) 但 token 不同時排除並回報 incomplete。"""
        projects = tmp_path / "projects"
        transcript = projects / "project" / "session.jsonl"
        transcript.parent.mkdir(parents=True)
        row_a = json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-09-03T06:30:00Z",
                "requestId": "req_dup",
                "message": {
                    "id": "msg_dup",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 500,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 0,
                            "ephemeral_1h_input_tokens": 0,
                        },
                    },
                },
            }
        )
        row_b = json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-09-03T06:31:00Z",
                "requestId": "req_dup",
                "message": {
                    "id": "msg_dup",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 2000,
                        "output_tokens": 500,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 0,
                            "ephemeral_1h_input_tokens": 0,
                        },
                    },
                },
            }
        )
        transcript.write_text(row_a + "\n" + row_b + "\n", encoding="utf-8")

        result = fleet_usage_guard.evaluate_burn_rate(
            projects,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.inconsistent_requests == 1
        assert result.status == "measurement_incomplete"
        assert result.estimated_cost_usd == Decimal(0)

    def test_fug_eg_006_breach_wins_over_incomplete_measurement(self, tmp_path: Path) -> None:
        """FUG-EG-006: 高用量超標同時有未定價 model 時，超標判定優先。"""
        projects = tmp_path / "projects"
        transcript = projects / "project" / "session.jsonl"
        transcript.parent.mkdir(parents=True)
        high_cost_row = json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-09-03T06:30:00Z",
                "requestId": "req_expensive",
                "message": {
                    "id": "msg_expensive",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 10_000_000,
                        "output_tokens": 5_000_000,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 0,
                            "ephemeral_1h_input_tokens": 0,
                        },
                    },
                },
            }
        )
        unpriced_row = json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-09-03T06:31:00Z",
                "requestId": "req_unknown",
                "message": {
                    "id": "msg_unknown",
                    "model": "claude-mystery-99",
                    "role": "assistant",
                    "content": [],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 0,
                            "ephemeral_1h_input_tokens": 0,
                        },
                    },
                },
            }
        )
        transcript.write_text(high_cost_row + "\n" + unpriced_row + "\n", encoding="utf-8")

        result = fleet_usage_guard.evaluate_burn_rate(
            projects,
            now=_at(7),
            window_minutes=60,
            threshold_usd_per_hour=Decimal("50"),
        )

        assert result.status == "burn_rate_exceeded"
        assert result.unpriced_models == ("claude-mystery-99",)
        assert result.estimated_usd_per_hour > Decimal("50")

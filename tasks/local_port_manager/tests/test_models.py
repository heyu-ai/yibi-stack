"""LPM 資料模型測試。"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tasks.local_port_manager.models import Category, PortEntry, PortRegistry


def make_entry(**kwargs: object) -> PortEntry:
    defaults: dict[str, object] = {
        "project": "test-proj",
        "service": "postgres",
        "category": Category.DB,
        "port": 5432,
        "registered_at": datetime(2026, 4, 28, tzinfo=UTC),
    }
    return PortEntry(**{**defaults, **kwargs})


class TestCategory:
    def test_lpm_dt_001_str_enum_value(self) -> None:
        """LPM-DT-001: Category 序列化為字串值。"""
        assert Category.DB.value == "db"
        assert Category.CACHE.value == "cache"
        assert Category.BACKEND.value == "backend"
        assert Category.FRONTEND.value == "frontend"
        assert Category.QUEUE.value == "queue"
        assert Category.OTHER.value == "other"

    def test_lpm_dt_002_invalid_category_raises(self) -> None:
        """LPM-DT-002: 無效 category 欄位值觸發 ValidationError。"""
        with pytest.raises(ValidationError):
            make_entry(category="invalid")


class TestPortEntry:
    def test_lpm_dt_003_default_note_is_empty(self) -> None:
        """LPM-DT-003: note 欄位預設為空字串。"""
        entry = make_entry()
        assert entry.note == ""

    def test_lpm_dt_004_missing_registered_at_raises(self) -> None:
        """LPM-DT-004: 缺少 registered_at 觸發 ValidationError。"""
        with pytest.raises(ValidationError):
            PortEntry(  # type: ignore[call-arg]
                project="p", service="s", category=Category.DB, port=5432
            )


class TestPortRegistry:
    def test_lpm_dt_005_default_entries_empty(self) -> None:
        """LPM-DT-005: 新建 registry entries 預設為空 list。"""
        registry = PortRegistry(
            ranges={"db": [5400, 5499]},
        )
        assert registry.entries == []
        assert registry.version == "1.0"

    def test_lpm_dt_006_roundtrip_json(self) -> None:
        """LPM-DT-006: PortRegistry JSON 序列化與反序列化一致。"""
        entry = make_entry()
        registry = PortRegistry(
            ranges={"db": [5400, 5499]},
            entries=[entry],
        )
        json_str = registry.model_dump_json()
        restored = PortRegistry.model_validate_json(json_str)
        assert restored.entries[0].port == 5432
        assert restored.entries[0].category == Category.DB  # noqa: PGH003

    def test_lpm_vl_001_ranges_single_element_raises(self) -> None:
        """LPM-VL-001: ranges 只有一個元素時 ValidationError。"""
        with pytest.raises(ValidationError):
            PortRegistry(ranges={"db": [5400]})

    def test_lpm_vl_002_ranges_reversed_bounds_raises(self) -> None:
        """LPM-VL-002: ranges 上界小於下界時 ValidationError。"""
        with pytest.raises(ValidationError):
            PortRegistry(ranges={"db": [5499, 5400]})

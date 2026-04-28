"""LPM service 邏輯測試。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tasks.local_port_manager.models import Category, PortEntry, PortRegistry
from tasks.local_port_manager.service import (
    find_next_available,
    get_entry,
    is_port_taken,
    load_registry,
    release,
    reserve,
    save_registry,
    suggest,
)


def _entry(project: str, service: str, port: int, category: Category) -> PortEntry:
    return PortEntry(
        project=project,
        service=service,
        category=category,
        port=port,
        registered_at=datetime(2026, 4, 28, tzinfo=UTC),
    )


def _registry(*entries: PortEntry) -> PortRegistry:
    return PortRegistry(
        ranges={
            "db": [5400, 5499],
            "cache": [6300, 6399],
            "backend": [3000, 3099],
            "frontend": [4000, 4099],
            "queue": [5600, 5699],
            "other": [9000, 9099],
        },
        entries=list(entries),
    )


class TestLoadSaveRegistry:
    def test_lpm_dt_007_roundtrip_via_file(self, tmp_path: Path) -> None:
        """LPM-DT-007: save_registry → load_registry 往返一致。"""
        path = tmp_path / "ports.json"
        reg = _registry(_entry("proj", "postgres", 5432, Category.DB))
        save_registry(reg, path)
        loaded = load_registry(path)
        assert loaded.entries[0].port == 5432
        assert loaded.entries[0].project == "proj"

    def test_lpm_eg_001_load_missing_file_raises(self, tmp_path: Path) -> None:
        """LPM-EG-001: 載入不存在的 registry 觸發 RuntimeError。"""
        with pytest.raises(RuntimeError, match="missing.json"):
            load_registry(tmp_path / "missing.json")

    def test_lpm_eg_001b_corrupt_json_raises(self, tmp_path: Path) -> None:
        """LPM-EG-001b: 損壞的 JSON 觸發 RuntimeError 而非原始 ValidationError。"""
        path = tmp_path / "ports.json"
        path.write_text("not-json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="格式錯誤"):
            load_registry(path)


class TestIsPortTaken:
    def test_lpm_dt_008_returns_entry_when_taken(self) -> None:
        """LPM-DT-008: port 已被登記時回傳對應 PortEntry。"""
        entry = _entry("yibi", "postgres", 5432, Category.DB)
        reg = _registry(entry)
        result = is_port_taken(reg, 5432)
        assert result is not None
        assert result.project == "yibi"

    def test_lpm_dt_009_returns_none_when_free(self) -> None:
        """LPM-DT-009: port 未被使用時回傳 None。"""
        reg = _registry()
        assert is_port_taken(reg, 5432) is None


class TestFindNextAvailable:
    def test_lpm_dt_010_returns_range_start_when_empty(self) -> None:
        """LPM-DT-010: registry 空白時回傳 category range 起始值。"""
        reg = _registry()
        assert find_next_available(reg, Category.DB) == 5400

    def test_lpm_dt_011_skips_taken_ports(self) -> None:
        """LPM-DT-011: 跳過已被佔用的 port，回傳第一個空閒值。"""
        reg = _registry(
            _entry("a", "pg", 5400, Category.DB),
            _entry("b", "pg", 5401, Category.DB),
        )
        assert find_next_available(reg, Category.DB) == 5402

    def test_lpm_eg_002_raises_when_range_full(self) -> None:
        """LPM-EG-002: category range 全滿時 raise RuntimeError。"""
        entries = [
            _entry(f"p{i}", "svc", 5400 + i, Category.DB)
            for i in range(100)  # db range 5400-5499 共 100 個
        ]
        reg = _registry(*entries)
        with pytest.raises(RuntimeError, match="db"):
            find_next_available(reg, Category.DB)

    def test_lpm_eg_003_raises_when_category_not_in_ranges(self) -> None:
        """LPM-EG-003: registry.ranges 缺少 category 時 raise RuntimeError。"""
        reg = PortRegistry(ranges={}, entries=[])
        with pytest.raises(RuntimeError, match="未定義的 category range"):
            find_next_available(reg, Category.DB)


class TestGetEntry:
    def test_lpm_dt_012_returns_entry_when_found(self) -> None:
        """LPM-DT-012: get_entry 找到 (project, service) 時回傳 entry。"""
        entry = _entry("yibi", "postgres", 5432, Category.DB)
        reg = _registry(entry)
        result = get_entry(reg, "yibi", "postgres")
        assert result is not None
        assert result.port == 5432

    def test_lpm_dt_013_returns_none_when_not_found(self) -> None:
        """LPM-DT-013: get_entry 找不到時回傳 None。"""
        reg = _registry()
        assert get_entry(reg, "unknown", "postgres") is None


class TestSuggest:
    def test_lpm_dt_014_returns_default_when_free(self) -> None:
        """LPM-DT-014: 慣例 port 未被佔用時 suggest 回傳慣例 port。"""
        reg = _registry()
        result = suggest(reg, "new-proj", "postgres")
        assert result.suggested_port == 5432
        assert result.conflict is None
        assert result.is_default is True

    def test_lpm_dt_015_returns_fallback_when_default_taken(self) -> None:
        """LPM-DT-015: 慣例 port 已被佔用時 suggest 回傳 range 內下一個空閒 port。"""
        reg = _registry(_entry("yibi", "postgres", 5432, Category.DB))
        result = suggest(reg, "new-proj", "postgres")
        assert result.suggested_port == 5400
        assert result.conflict is not None
        assert result.conflict.project == "yibi"
        assert result.is_default is False

    def test_lpm_dt_015b_fallback_uses_override_category_when_provided(self) -> None:
        """LPM-DT-015b: fallback 從指定 category range 取 port。"""
        reg = _registry(_entry("yibi", "postgres", 5432, Category.DB))
        result = suggest(reg, "new-proj", "postgres", category=Category.BACKEND)
        assert result.suggested_port == 3000
        assert result.is_default is False

    def test_lpm_dt_016_unknown_service_uses_category(self) -> None:
        """LPM-DT-016: 無慣例 port 的服務以指定 category range 起始值為建議。"""
        reg = _registry()
        result = suggest(reg, "proj", "custom-db", category=Category.DB)
        assert result.suggested_port == 5400
        assert result.is_default is False

    def test_lpm_eg_004_no_category_for_unknown_service_raises(self) -> None:
        """LPM-EG-004: 無慣例 port 且未指定 category 時 raise ValueError。"""
        reg = _registry()
        with pytest.raises(ValueError, match="category"):
            suggest(reg, "proj", "unknown-svc")


class TestReserve:
    def test_lpm_dt_017_adds_new_entry(self) -> None:
        """LPM-DT-017: reserve 新增 entry 至 registry。"""
        reg = _registry()
        entry = _entry("proj", "postgres", 5432, Category.DB)
        updated = reserve(reg, entry)
        assert len(updated.entries) == 1
        assert updated.entries[0].port == 5432

    def test_lpm_dt_018_raises_when_port_taken_by_different(self) -> None:
        """LPM-DT-018: port 已被其他 (project, service) 佔用時 raise ValueError。"""
        existing = _entry("yibi", "postgres", 5432, Category.DB)
        reg = _registry(existing)
        new_entry = _entry("voice-lab", "postgres", 5432, Category.DB)
        with pytest.raises(ValueError, match="5432"):
            reserve(reg, new_entry)

    def test_lpm_dt_019_overwrites_same_project_service(self) -> None:
        """LPM-DT-019: 相同 (project, service) 可覆寫更新 port。"""
        existing = _entry("proj", "postgres", 5432, Category.DB)
        reg = _registry(existing)
        updated_entry = _entry("proj", "postgres", 5433, Category.DB)
        updated = reserve(reg, updated_entry)
        assert len(updated.entries) == 1
        assert updated.entries[0].port == 5433

    def test_lpm_dt_019b_overwrites_keeps_other_entries(self) -> None:
        """LPM-DT-019b: 覆寫同一 entry 時不影響其他 entry。"""
        existing = _entry("proj", "postgres", 5432, Category.DB)
        other = _entry("proj", "redis", 6379, Category.CACHE)
        reg = _registry(existing, other)
        updated_entry = _entry("proj", "postgres", 5433, Category.DB)
        updated = reserve(reg, updated_entry)
        assert len(updated.entries) == 2
        assert {e.port for e in updated.entries} == {5433, 6379}


class TestRelease:
    def test_lpm_dt_020_removes_entry(self) -> None:
        """LPM-DT-020: release 移除 (project, service) entry。"""
        entry = _entry("proj", "postgres", 5432, Category.DB)
        reg = _registry(entry)
        updated = release(reg, "proj", "postgres")
        assert updated.entries == []

    def test_lpm_dt_020b_release_keeps_other_services(self) -> None:
        """LPM-DT-020b: release 不影響同 project 其他服務的 entry。"""
        postgres = _entry("proj", "postgres", 5432, Category.DB)
        redis = _entry("proj", "redis", 6379, Category.CACHE)
        reg = _registry(postgres, redis)
        updated = release(reg, "proj", "postgres")
        assert len(updated.entries) == 1
        assert updated.entries[0].service == "redis"

    def test_lpm_eg_005_release_idempotent_when_not_found(self) -> None:
        """LPM-EG-005: 釋放不存在的 entry 時冪等回傳原 registry。"""
        reg = _registry()
        updated = release(reg, "proj", "postgres")
        assert updated.entries == []

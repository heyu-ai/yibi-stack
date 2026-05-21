"""BHAUDIT-VL 模型驗證測試。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tasks.bash_hygiene_audit.models import AuditConfig, AuditRecord, AuditStats


def make_record(**kwargs: object) -> AuditRecord:
    defaults: dict[str, object] = {
        "ts": "2026-05-21T00:00:00Z",
        "hook": "ap1",
        "exit_code": 0,
        "verdict": "allow",
        "command_preview": "echo hello",
        "command_hash": "abc123",
    }
    return AuditRecord(**{**defaults, **kwargs})


class TestAuditConfig:
    def test_bhaudit_vl_001_default_disabled(self) -> None:
        """BHAUDIT-VL-001: 預設 audit_enabled=False。"""
        c = AuditConfig()
        assert c.audit_enabled is False

    def test_bhaudit_vl_002_enable(self) -> None:
        """BHAUDIT-VL-002: 可設為 True。"""
        c = AuditConfig(audit_enabled=True)
        assert c.audit_enabled is True


class TestAuditRecord:
    def test_bhaudit_vl_003_required_fields(self) -> None:
        """BHAUDIT-VL-003: 必填欄位缺失時拋 ValidationError。"""
        with pytest.raises(ValidationError):
            AuditRecord.model_validate({})

    def test_bhaudit_vl_004_optional_block_reason(self) -> None:
        """BHAUDIT-VL-004: block_reason 選填，預設 None。"""
        r = make_record()
        assert r.block_reason is None

    def test_bhaudit_vl_005_block_record(self) -> None:
        """BHAUDIT-VL-005: block 記錄包含 block_reason。"""
        r = make_record(exit_code=2, verdict="block", block_reason="ap2-unicode")
        assert r.verdict == "block"
        assert r.block_reason == "ap2-unicode"


class TestAuditStats:
    def test_bhaudit_vl_006_defaults(self) -> None:
        """BHAUDIT-VL-006: AuditStats 預設值全為 0/None/空 dict。"""
        s = AuditStats()
        assert s.total == 0
        assert s.block_count == 0
        assert s.by_hook == {}
        assert s.avg_duration_ms is None

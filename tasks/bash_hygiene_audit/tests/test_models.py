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
        "cmd_snippet": "echo hello",
        "command_hash": "abc123",
        "hook_version": "2",
    }
    return AuditRecord.model_validate({**defaults, **kwargs})


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

    def test_bhaudit_vl_007_alias_command_preview_accepted(self) -> None:
        """BHAUDIT-VL-007: v1 log 用 command_preview key 反序列化後填入 cmd_snippet。"""
        r = AuditRecord.model_validate(
            {
                "ts": "2026-05-21T00:00:00Z",
                "hook": "ap1",
                "exit_code": 0,
                "verdict": "allow",
                "command_preview": "echo hello",
                "command_hash": "abc123",
            }
        )
        assert r.cmd_snippet == "echo hello"

    def test_bhaudit_vl_008_new_cmd_snippet_key_accepted(self) -> None:
        """BHAUDIT-VL-008: v2 log 用 cmd_snippet key 正確反序列化。"""
        r = AuditRecord.model_validate(
            {
                "ts": "2026-05-21T00:00:00Z",
                "hook": "ap2",
                "exit_code": 2,
                "verdict": "block",
                "cmd_snippet": "git status",
                "command_hash": "abc123",
            }
        )
        assert r.cmd_snippet == "git status"

    def test_bhaudit_vl_009_hook_version_default_v2(self) -> None:
        """BHAUDIT-VL-009: hook_version 預設為 '2'。"""
        r = make_record()
        assert r.hook_version == "2"

    def test_bhaudit_vl_010_rule_id_default_empty(self) -> None:
        """BHAUDIT-VL-010: rule_id 預設為空字串（不為 None），避免 sh 傳 null 被 reject。"""
        r = make_record()
        assert r.rule_id == ""


class TestAuditStats:
    def test_bhaudit_vl_006_defaults(self) -> None:
        """BHAUDIT-VL-006: AuditStats 預設值全為 0/None/空 dict。"""
        s = AuditStats()
        assert s.total == 0
        assert s.block_count == 0
        assert s.by_hook == {}
        assert s.avg_duration_ms is None

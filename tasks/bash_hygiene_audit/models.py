"""bash-hygiene audit log 資料模型。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AliasChoices, BaseModel, Field


class Verdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ERROR = "error"


class AuditConfig(BaseModel):
    """User-level toggle config（~/.agents/bash-hygiene.json）。"""

    audit_enabled: bool = False


class AuditRecord(BaseModel):
    """JSONL audit log 單筆記錄。"""

    ts: str
    hook: str
    hook_version: str = "2"
    exit_code: int
    verdict: Verdict
    block_reason: str | None = None
    rule_id: str = ""
    cmd_snippet: str = Field(
        default="",
        validation_alias=AliasChoices("cmd_snippet", "command_preview"),
        description="Command preview; v1 key 'command_preview' accepted for back-compat",
    )
    command_hash: str = ""
    session_id: str | None = None
    duration_ms: int | None = None


class AuditStats(BaseModel):
    """多筆 AuditRecord 的聚合統計。"""

    total: int = 0
    allow_count: int = 0
    block_count: int = 0
    error_count: int = 0
    by_hook: dict[str, int] = Field(default_factory=dict)
    by_reason: dict[str, int] = Field(default_factory=dict)
    avg_duration_ms: float | None = None

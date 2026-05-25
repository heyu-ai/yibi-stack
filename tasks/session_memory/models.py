"""Agents 資料模型：AgentsConfig、HandoverRecord、InsightRecord、SessionType、HandoverEvent。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_non_empty(v: str) -> str:
    stripped = v.strip()
    if not stripped:
        raise ValueError("欄位不可為空字串")
    return stripped


def _validate_iso_timestamp(v: str) -> str:
    try:
        datetime.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"timestamp 必須為 ISO 8601 格式：{v!r}") from e
    return v


class SessionType(StrEnum):
    """交班 session 類型。對應 handover table 的 CHECK constraint。"""

    sdd = "sdd"
    debug = "debug"
    discussion = "discussion"
    admin = "admin"


class EventType(StrEnum):
    """Handover 事件類型。用於量測 auto-handover 成功率與三層防護的實際觸發效果。"""

    layer2_intercept = "layer2_intercept"
    layer2_passthrough = "layer2_passthrough"
    layer2_stale_reset = "layer2_stale_reset"
    handover_written = "handover_written"
    layer3_session_start = "layer3_session_start"
    layer1_self_suggest = "layer1_self_suggest"
    handover_back_invoked = "handover_back_invoked"
    cli_metrics_query = "cli_metrics_query"


class SourceLayer(StrEnum):
    """事件觸發來源層。"""

    layer1 = "layer1"
    layer2 = "layer2"
    layer3 = "layer3"
    cli = "cli"


class AgentsConfig(BaseModel):
    """~/.agents/config.json 本機設定。"""

    model_config = ConfigDict(frozen=True)

    version: str = "1.0"
    device_id: str
    default_account: str | None = None
    default_agent: str = "claude"
    operator: str = "howie"
    # make install 時寫入；供跨機器 command 找到 uv 專案。
    # 機器本地絕對路徑，不套用 to_portable_path（不應跨機器同步）。
    skill_repo: str | None = None

    @field_validator("device_id")
    @classmethod
    def check_device_id_non_empty(cls, v: str) -> str:
        """device_id 不可為空字串（用作機器識別符與 DB key）；自動 strip 前後空白。"""
        stripped = v.strip()
        if not stripped:
            raise ValueError("device_id 不可為空")
        return stripped

    @field_validator("skill_repo")
    @classmethod
    def check_absolute_path(cls, v: str | None) -> str | None:
        """skill_repo 若有值必須為絕對路徑；未設定時傳 None，不接受空字串。"""
        if v is None:
            return v
        if not v:
            raise ValueError("skill_repo 不可為空字串，未設定時請傳 None")
        if not Path(v).is_absolute():
            raise ValueError("skill_repo 必須為絕對路徑")
        return v


class HandoverRecord(BaseModel):
    """Handover 單筆記錄。Layer 1 為核心語意，Layer 2 為環境復原資訊。"""

    # Layer 1: Universal
    id: str
    timestamp: str
    operator: str = "howie"
    session_type: SessionType
    topic: str
    conversation_summary: str
    completed: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    next_priorities: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    attempted_approaches: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Layer 2: Environment-specific
    device: str | None = None
    agent_type: str = "claude"
    subscription_account: str | None = None
    branch: str | None = None
    working_dir: str | None = None
    last_files: list[str] = Field(default_factory=list)
    test_status: str | None = None
    token_usage_estimate: str | None = None
    project: str | None = None


class HandoverEvent(BaseModel):
    """Handover 生命週期事件記錄（寫入 handover_events table）。"""

    model_config = ConfigDict(frozen=True)

    id: str
    timestamp: str
    session_id: str | None = None
    event_type: EventType
    source_layer: SourceLayer | None = None
    matcher: str | None = None
    handover_id: str | None = None
    project: str | None = None
    device: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def check_id_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id 不可為空")
        return v

    @field_validator("timestamp")
    @classmethod
    def check_timestamp_iso(cls, v: str) -> str:
        return _validate_iso_timestamp(v)

    @field_validator("session_id")
    @classmethod
    def check_session_id_not_empty_string(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("session_id 若有值不可為空字串，請傳 None")
        return v


class TagEntry(BaseModel):
    """單一 tag 統計項目。"""

    model_config = ConfigDict(frozen=True)

    tag: str
    count: int
    latest_at: str | None = None
    projects: list[str] = Field(default_factory=list)

    @field_validator("tag")
    @classmethod
    def check_tag_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("tag 不可為空字串")
        return v.strip()

    @field_validator("count")
    @classmethod
    def check_count_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("count 不可為負數")
        return v


class TagStats(BaseModel):
    """全域 tag 使用統計報告。"""

    model_config = ConfigDict(frozen=True)

    total_unique_tags: int = 0
    total_handovers_with_tags: int = 0
    entries: list[TagEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_consistency(self) -> TagStats:
        if self.total_unique_tags < 0:
            raise ValueError("total_unique_tags 不可為負數")
        if len(self.entries) > self.total_unique_tags:
            raise ValueError("entries 數量不可超過 total_unique_tags")
        return self


class MetricsReport(BaseModel):
    """Auto-handover 成功率統計報告。"""

    model_config = ConfigDict(frozen=True)

    since: str | None = None
    project: str | None = None
    total_intercepts: int = 0
    wrote_after_intercept: int = 0
    silent_fail: int = 0
    hard_fail: int = 0
    layer1_win: int = 0
    stale_resets: int = 0
    sessions_observed: int = 0
    success_rate: float = 0.0
    silent_fail_rate: float = 0.0
    hard_fail_rate: float = 0.0
    layer1_win_rate: float = 0.0

    @model_validator(mode="after")
    def check_non_negative(self) -> MetricsReport:
        for field in (
            "total_intercepts",
            "wrote_after_intercept",
            "silent_fail",
            "hard_fail",
            "layer1_win",
            "stale_resets",
            "sessions_observed",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} 不可為負數")
        for field in ("success_rate", "silent_fail_rate", "hard_fail_rate", "layer1_win_rate"):
            v = getattr(self, field)
            if v < 0.0 or v > 1.0:
                raise ValueError(f"{field} 必須在 0.0 ~ 1.0 之間，收到 {v}")
        return self


class InsightRecord(BaseModel):
    """Insight 單筆記錄（JSONL 內 schema）。"""

    id: str
    timestamp: str
    session_id: str
    project: str
    working_dir: str
    branch: str
    agent_type: str = "claude"
    account: str = "unknown"
    device: str | None = None
    insight_text: str
    session_reason: str = ""


class RecapRecord(BaseModel):
    """Away summary 單筆記錄（JSONL 內 schema）。

    id 使用 transcript entry 自帶的 uuid，以確保冪等性（同筆不重複寫入）。
    timestamp 使用 entry 自帶的時間，保留正確時序。
    """

    id: str
    timestamp: str
    session_id: str
    project: str
    working_dir: str
    branch: str
    agent_type: str = "claude"
    account: str = "unknown"
    device: str | None = None
    recap_text: str
    cc_version: str = ""
    session_reason: str = ""

    @field_validator("id", "session_id", "recap_text")
    @classmethod
    def check_non_empty(cls, v: str) -> str:
        return _validate_non_empty(v)

    @field_validator("timestamp")
    @classmethod
    def check_timestamp_iso(cls, v: str) -> str:
        return _validate_iso_timestamp(v)


class DebugReportRecord(BaseModel):
    """Debug report 單筆記錄（JSONL 內 schema）。

    全文 Markdown 存 debugs/<date>_<keyword>_debug_report.md；
    此模型只存跨專案搜尋用的摘要欄位。
    """

    id: str
    timestamp: str
    project: str
    working_dir: str
    branch: str
    keyword: str
    report_path: str
    symptom_summary: str
    root_cause: str
    prevention_tags: list[str] = Field(default_factory=list)
    agent_type: str = "claude"
    account: str = "unknown"
    device: str | None = None

    @field_validator("id", "project", "keyword", "report_path", "symptom_summary", "root_cause")
    @classmethod
    def check_non_empty(cls, v: str) -> str:
        return _validate_non_empty(v)

    @field_validator("timestamp")
    @classmethod
    def check_timestamp_iso(cls, v: str) -> str:
        return _validate_iso_timestamp(v)

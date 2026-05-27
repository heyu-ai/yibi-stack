"""PR Orchestrator 資料模型。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PRState(StrEnum):
    DETECTED = "DETECTED"
    REVIEWING = "REVIEWING"
    REVIEW_DONE = "REVIEW_DONE"
    CI_WAIT = "CI_WAIT"
    AUTO_FIX = "AUTO_FIX"
    CI_PASS = "CI_PASS"  # nosec B105
    CONFLICT = "CONFLICT"
    MERGEABLE = "MERGEABLE"
    MERGED = "MERGED"
    RETRO_DONE = "RETRO_DONE"
    CLEANED = "CLEANED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class FixResult(StrEnum):
    applied = "applied"
    no_change = "no_change"
    failed = "failed"


class Transition(BaseModel):
    """單次 state transition 記錄。"""

    from_state: PRState
    to_state: PRState
    at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reason: str = ""
    actor: str = "orchestrator"


class FixAttempt(BaseModel):
    """一次 auto-fix 嘗試的結果。"""

    iteration: int
    fixer: str
    commit: str | None = None
    result: FixResult
    files_changed: list[str] = Field(default_factory=list)


class Artifacts(BaseModel):
    """各階段產生的路徑參照。"""

    review_dir: str | None = None
    spawn_manifest: str | None = None
    ci_logs: list[str] = Field(default_factory=list)
    merge_commit: str | None = None
    retro_handover_id: str | None = None


class Blocker(BaseModel):
    """人工介入需求說明。"""

    at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reason: str
    suggested_action: str = ""


class OrchestratorState(BaseModel):
    """PR Orchestrator 完整執行狀態，持久化到 .runtime/pr_orchestrator/<pr>.json。"""

    schema_version: int = 1
    pr_number: int
    branch: str
    head_sha: str
    base_branch: str = "main"
    repo: str = ""
    current_state: PRState = PRState.DETECTED
    last_transition_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    transitions: list[Transition] = Field(default_factory=list)
    artifacts: Artifacts = Field(default_factory=Artifacts)
    fix_attempts: list[FixAttempt] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def fix_iteration_count(self) -> int:
        return len({a.iteration for a in self.fix_attempts})


class PRInfo(BaseModel):
    """`gh pr view` 回傳的 PR 摘要。"""

    number: int
    head_ref_name: str
    head_ref_oid: str
    base_ref_name: str
    mergeable: str = "UNKNOWN"
    merge_state_status: str = "UNKNOWN"
    author_login: str = ""


class CIFailure(BaseModel):
    """單一 CI job 失敗資訊。"""

    run_id: str
    job_name: str
    log_text: str
    workflow_name: str = ""

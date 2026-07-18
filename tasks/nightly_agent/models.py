"""夜間 Agent 資料模型。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FrictionType(StrEnum):
    AP2_BLOCK = "ap2_block"
    WORKTREE_CONFLICT = "worktree_conflict"
    WRONG_APPROACH = "wrong_approach"
    BUGGY_CODE = "buggy_code"
    LANGUAGE_MISMATCH = "language_mismatch"


class ArtifactType(StrEnum):
    HOOKIFY_RULE = "hookify_rule"
    CLAUDE_MD_GOTCHA = "claude_md_gotcha"
    SKILL_UPDATE = "skill_update"


# Maps friction type to preferred artifact type
FRICTION_TO_ARTIFACT: dict[FrictionType, ArtifactType] = {
    FrictionType.AP2_BLOCK: ArtifactType.HOOKIFY_RULE,
    FrictionType.WORKTREE_CONFLICT: ArtifactType.CLAUDE_MD_GOTCHA,
    FrictionType.WRONG_APPROACH: ArtifactType.CLAUDE_MD_GOTCHA,
    FrictionType.BUGGY_CODE: ArtifactType.CLAUDE_MD_GOTCHA,
    FrictionType.LANGUAGE_MISMATCH: ArtifactType.CLAUDE_MD_GOTCHA,
}


class FrictionEvent(BaseModel):
    """從 transcript 或 mycelium 提取的單一 friction 事件。"""

    id: str
    session_id: str
    timestamp: str
    project: str
    friction_type: FrictionType
    description: str
    raw_text: str
    source_file: str
    line_number: int = 0


class FrictionCluster(BaseModel):
    """語意相近的 friction events 聚合。"""

    id: str
    friction_type: FrictionType
    events: list[FrictionEvent] = Field(default_factory=list)
    common_keywords: list[str] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def source_session_ids(self) -> list[str]:
        return list({e.session_id for e in self.events})


class ArtifactProposal(BaseModel):
    """聚類後產生的預防性 artifact 草稿。"""

    id: str
    cluster_id: str
    artifact_type: ArtifactType
    title: str
    content: str  # artifact 本文（hook script、gotcha text、或 skill 段落）
    target_file: str  # 要寫入的檔案路徑（相對於 repo root）
    source_session_ids: list[str] = Field(default_factory=list)
    friction_descriptions: list[str] = Field(default_factory=list)

    # 由 TestValidator 填入
    test_file: str = ""
    test_content: str = ""


class TestResult(BaseModel):
    """failing-then-passing test 執行結果。"""

    proposal_id: str
    test_file: str
    passed: bool
    previously_failed: bool
    before_output: str = ""
    after_output: str = ""
    error: str = ""


class PRRecord(BaseModel):
    """已建立的 PR 資訊。"""

    proposal_id: str
    cluster_id: str = ""
    pr_url: str
    pr_number: int
    branch: str
    artifact_file: str
    test_file: str


class NightlyDigest(BaseModel):
    """每日執行摘要。"""

    date: str
    lookback_hours: int
    friction_events_found: int
    clusters_found: int
    clusters_eligible: int  # count >= 2
    artifacts_drafted: int
    tests_validated: int
    prs_opened: int
    skipped_no_test: int
    prs: list[PRRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    digest_text: str = ""


class NightlyAgentConfig(BaseModel):
    """執行設定。"""

    version: str = "1.0"
    lookback_hours: int = 24
    min_cluster_size: int = 2
    jaccard_threshold: float = 0.25
    # Claude model for artifact drafting
    draft_model: str = "claude-sonnet-4-6"
    draft_max_tokens: int = 2048
    # GitHub repo for PRs
    github_repo: str = ""
    # PR branch prefix
    pr_branch_prefix: str = "nightly-agent"
    # Where to write digests
    digest_dir: str = ".runtime/nightly-agent/digests"
    # Where to write ephemeral validation records (outside pytest testpaths)
    generated_tests_dir: str = ".runtime/nightly_agent/generated_tests"
    # Cross-night friction fingerprint state
    friction_state_file: str = ".runtime/nightly_agent/frictions.json"
    # Extra project scan paths (beyond ~/.claude/projects/<project_slug>)
    extra_transcript_paths: list[str] = Field(default_factory=list)
    # Mycelium lesson source types to include
    lesson_types: list[str] = Field(default_factory=lambda: ["pitfall", "pattern"])
    # extra metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

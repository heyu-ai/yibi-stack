"""harness_eval 資料模型。"""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class DimensionStatus(StrEnum):
    """維度健康狀態。"""

    PASS = "pass"  # nosec B105
    WARN = "warn"
    FAIL = "fail"


class MechanicalFinding(BaseModel):
    """單一維度的機械掃描結果（Python scanner 產出）。"""

    dimension: str
    label: str
    score: int
    max_score: int
    findings: list[str] = Field(default_factory=list)
    semantic_targets: list[str] = Field(default_factory=list)

    @field_validator("score")
    @classmethod
    def score_not_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("score 不可為負數")
        return v


class ScanOutput(BaseModel):
    """Python scanner 輸出的完整機械掃描報告。"""

    version: str = "1.0"
    target_dir: str
    scanned_at: str
    dimensions: list[MechanicalFinding] = Field(default_factory=list)
    total_mechanical: int = 0
    total_mechanical_max: int = 0

    def model_post_init(self, __context: object) -> None:
        self.total_mechanical = sum(d.score for d in self.dimensions)
        self.total_mechanical_max = sum(d.max_score for d in self.dimensions)

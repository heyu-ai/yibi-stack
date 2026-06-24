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
    extra: dict[str, list[str]] = Field(default_factory=dict)

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
    # 規模調整分數（task-demand 正規化，issue #136）。
    # d_repo 為 repo 複雜度因子（>=1），抵銷「artifact 越多分越高」的膨脹。
    d_repo: float = 1.0
    d_repo_components: list[str] = Field(default_factory=list)
    size_adjusted_score: float = 0.0
    # provisional：未經 outcome 校準，僅供相對規模比較；真正校準見 issue #143。
    size_adjusted_note: str = "provisional（未校準，見 #143）"

    def model_post_init(self, __context: object) -> None:
        self.total_mechanical = sum(d.score for d in self.dimensions)
        self.total_mechanical_max = sum(d.max_score for d in self.dimensions)
        d_repo = self.d_repo if self.d_repo >= 1.0 else 1.0
        self.size_adjusted_score = round(self.total_mechanical / d_repo, 1)

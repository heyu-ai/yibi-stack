"""skill_eval 資料模型：觸發評測 fixture、judge 任務、verdict 與報告。"""

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field, model_validator


class TriggerPromptClass(StrEnum):
    """觸發評測的三類 prompt（對映 rule 11 direct/indirect/negative 三軸）。"""

    DIRECT = "direct"  # 字面觸發詞，應觸發（召回 baseline）
    INDIRECT = "indirect"  # 換句話說仍應觸發（召回廣度）
    NEGATIVE = "negative"  # 鄰近但不該觸發（精確度，通常對映 sibling skill）


class TriggerPrompt(BaseModel):
    """單一評測 prompt 與其期望是否觸發目標 skill。"""

    prompt: str
    expect_trigger: bool


class TriggerEvalFixture(BaseModel):
    """單一 skill 的觸發評測 fixture（存於 SKILL.md 旁的 trigger_eval.json）。"""

    version: str = "1.0"
    skill: str
    direct: list[TriggerPrompt] = Field(default_factory=list)
    indirect: list[TriggerPrompt] = Field(default_factory=list)
    negative: list[TriggerPrompt] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_expect_trigger(self) -> "TriggerEvalFixture":
        for p in self.direct:
            if not p.expect_trigger:
                raise ValueError("direct prompt 的 expect_trigger 必須為 true")
        for p in self.indirect:
            if not p.expect_trigger:
                raise ValueError("indirect prompt 的 expect_trigger 必須為 true")
        for p in self.negative:
            if p.expect_trigger:
                raise ValueError("negative prompt 的 expect_trigger 必須為 false")
        return self

    def prompts_for(self, cls: TriggerPromptClass) -> list[TriggerPrompt]:
        """取指定類別的 prompt 清單。"""
        return {
            TriggerPromptClass.DIRECT: self.direct,
            TriggerPromptClass.INDIRECT: self.indirect,
            TriggerPromptClass.NEGATIVE: self.negative,
        }[cls]


class JudgeTask(BaseModel):
    """交給 judge backend 判斷的單一任務（manifest 元素）。

    刻意不帶 skill 的 description——agent-driven backend 的 subagent 會自行讀取
    `skills/<skill>/SKILL.md`，Python 端因此不需複製 frontmatter parser。
    """

    index: int
    skill: str
    cls: TriggerPromptClass
    prompt: str
    expect_trigger: bool


class PromptVerdict(BaseModel):
    """單一 prompt 的判斷結果。passed 由 triggered 與 expect_trigger 推導。"""

    skill: str
    cls: TriggerPromptClass
    prompt: str
    triggered: bool
    expect_trigger: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return self.triggered == self.expect_trigger


class ClassScore(BaseModel):
    """單一 skill 單一類別的計分。"""

    cls: TriggerPromptClass
    total: int
    passed: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pass_rate(self) -> float:
        """passed / total；類別無 prompt 時視為 1.0（vacuously pass）。"""
        return self.passed / self.total if self.total else 1.0


class SkillEvalResult(BaseModel):
    """單一 skill 的評測結果：逐類計分 + 明細 verdict。"""

    skill: str
    scores: list[ClassScore] = Field(default_factory=list)
    verdicts: list[PromptVerdict] = Field(default_factory=list)


class Regression(BaseModel):
    """一筆 pass rate 回歸（current 低於 baseline - tolerance）。"""

    skill: str
    cls: TriggerPromptClass
    baseline: float
    current: float


class EvalReport(BaseModel):
    """多 skill 評測彙整報告。"""

    version: str = "1.0"
    results: list[SkillEvalResult] = Field(default_factory=list)
    regressions: list[Regression] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_regression(self) -> bool:
        return bool(self.regressions)

"""skill_eval 資料模型測試。"""

import pytest
from pydantic import ValidationError

from tasks.skill_eval.models import (
    ClassScore,
    PromptVerdict,
    TriggerEvalFixture,
    TriggerPrompt,
    TriggerPromptClass,
)


def make_fixture(**kwargs: object) -> TriggerEvalFixture:
    defaults: dict[str, object] = {
        "skill": "demo",
        "direct": [TriggerPrompt(prompt="run demo", expect_trigger=True)],
        "indirect": [TriggerPrompt(prompt="kick off the demo", expect_trigger=True)],
        "negative": [TriggerPrompt(prompt="do something else", expect_trigger=False)],
    }
    return TriggerEvalFixture(**{**defaults, **kwargs})


class TestTriggerPromptClass:
    def test_seval_vl_001_enum_values(self) -> None:
        """SEVAL-VL-001: 三軸 StrEnum 值為 direct/indirect/negative。
        spec: skill-trigger-eval#valid-fixture-loads"""
        assert str(TriggerPromptClass.DIRECT) == "direct"
        assert str(TriggerPromptClass.INDIRECT) == "indirect"
        assert str(TriggerPromptClass.NEGATIVE) == "negative"


class TestTriggerEvalFixture:
    def test_seval_vl_002_valid_fixture(self) -> None:
        """SEVAL-VL-002: 合法 fixture 三類皆可存取。
        spec: skill-trigger-eval#valid-fixture-loads"""
        fx = make_fixture()
        assert fx.prompts_for(TriggerPromptClass.DIRECT)[0].prompt == "run demo"
        assert len(fx.prompts_for(TriggerPromptClass.NEGATIVE)) == 1

    def test_seval_vl_003_negative_expect_trigger_true_rejected(self) -> None:
        """SEVAL-VL-003: negative prompt expect_trigger=true 被拒。
        spec: skill-trigger-eval#negative-expect-trigger-true-rejected"""
        with pytest.raises(ValidationError):
            make_fixture(negative=[TriggerPrompt(prompt="x", expect_trigger=True)])

    def test_seval_vl_004_direct_expect_trigger_false_rejected(self) -> None:
        """SEVAL-VL-004: direct prompt expect_trigger=false 被拒。
        spec: skill-trigger-eval#negative-expect-trigger-true-rejected"""
        with pytest.raises(ValidationError):
            make_fixture(direct=[TriggerPrompt(prompt="x", expect_trigger=False)])


class TestPromptVerdict:
    def test_seval_vl_005_negative_not_triggered_passes(self) -> None:
        """SEVAL-VL-005: negative 未觸發 -> passed（由 triggered==expect 推導）。
        spec: skill-trigger-eval#negative-not-triggered-passes"""
        v = PromptVerdict(
            skill="demo",
            cls=TriggerPromptClass.NEGATIVE,
            prompt="x",
            triggered=False,
            expect_trigger=False,
        )
        assert v.passed is True

    def test_seval_vl_006_direct_not_triggered_fails(self) -> None:
        """SEVAL-VL-006: direct 未觸發 -> not passed。
        spec: skill-trigger-eval#negative-not-triggered-passes"""
        v = PromptVerdict(
            skill="demo",
            cls=TriggerPromptClass.DIRECT,
            prompt="x",
            triggered=False,
            expect_trigger=True,
        )
        assert v.passed is False


class TestClassScore:
    def test_seval_vl_007_pass_rate(self) -> None:
        """SEVAL-VL-007: pass_rate = passed/total。
        spec: skill-trigger-eval#negative-not-triggered-passes"""
        assert ClassScore(cls=TriggerPromptClass.DIRECT, total=4, passed=3).pass_rate == 0.75

    def test_seval_vl_008_empty_class_is_vacuously_one(self) -> None:
        """SEVAL-VL-008: 類別無 prompt 時 pass_rate=1.0，不除以零。
        spec: skill-trigger-eval#negative-not-triggered-passes"""
        assert ClassScore(cls=TriggerPromptClass.DIRECT, total=0, passed=0).pass_rate == 1.0

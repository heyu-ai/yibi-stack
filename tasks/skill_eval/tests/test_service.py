"""skill_eval 評測核心測試（judge 以 stub / AgentJudge，不打真 LLM）。"""

import pytest

from tasks.skill_eval.config import load_fixture
from tasks.skill_eval.judges import AgentJudge
from tasks.skill_eval.judges.base import Judge
from tasks.skill_eval.models import (
    JudgeTask,
    PromptVerdict,
    TriggerEvalFixture,
    TriggerPrompt,
    TriggerPromptClass,
)
from tasks.skill_eval.service import (
    build_tasks,
    compare_baseline,
    manifest_signature,
    results_to_baseline,
    run_eval,
    score_verdicts,
)


def make_fixture(skill: str = "demo") -> TriggerEvalFixture:
    return TriggerEvalFixture(
        skill=skill,
        direct=[TriggerPrompt(prompt="run demo", expect_trigger=True)],
        indirect=[TriggerPrompt(prompt="start the demo", expect_trigger=True)],
        negative=[
            TriggerPrompt(prompt="unrelated", expect_trigger=False),
            TriggerPrompt(prompt="sibling territory", expect_trigger=False),
        ],
    )


def verdicts(fixture: TriggerEvalFixture, triggered: list[bool]) -> list[PromptVerdict]:
    """以純 AgentJudge 把 triggered 布林陣列映為 verdict（測試共用 helper）。"""
    tasks = build_tasks([fixture])
    judge = AgentJudge()
    return judge.score(judge.build_manifest(tasks), triggered)


class FixedJudge(Judge):
    """忽略傳入 judgments、回傳固定 verdict 的 stub，用來證明核心只依賴 Judge 介面、無 LLM。"""

    name = "fixed"

    def __init__(self, triggered: list[bool]) -> None:
        self._triggered = triggered

    def build_manifest(self, tasks: list[JudgeTask]) -> list[JudgeTask]:
        return list(tasks)

    def score(self, manifest: list[JudgeTask], judgments: list[bool]) -> list[PromptVerdict]:
        return [
            PromptVerdict(
                skill=t.skill,
                cls=t.cls,
                prompt=t.prompt,
                triggered=trig,
                expect_trigger=t.expect_trigger,
            )
            for t, trig in zip(manifest, self._triggered, strict=True)
        ]


class TestBuildTasks:
    def test_seval_dt_005_stable_order_and_index(self) -> None:
        """SEVAL-DT-005: build_tasks 依 direct/indirect/negative 展平、index 連續。
        spec: skill-trigger-eval#verdict-count-mismatch-surfaced"""
        tasks = build_tasks([make_fixture()])
        assert [t.cls for t in tasks] == [
            TriggerPromptClass.DIRECT,
            TriggerPromptClass.INDIRECT,
            TriggerPromptClass.NEGATIVE,
            TriggerPromptClass.NEGATIVE,
        ]
        assert [t.index for t in tasks] == [0, 1, 2, 3]

    def test_seval_cv_002_manifest_signature_tracks_fixture(self) -> None:
        """SEVAL-CV-002: manifest_signature 隨 fixture prompt 變動而改變（綁定基礎）。
        spec: skill-trigger-eval#verdict-count-mismatch-surfaced"""
        base = manifest_signature(build_tasks([make_fixture()]))
        changed = TriggerEvalFixture(
            skill="demo",
            direct=[TriggerPrompt(prompt="run demo CHANGED", expect_trigger=True)],
        )
        assert base != manifest_signature(build_tasks([changed]))


class TestScoreVerdicts:
    def test_seval_dt_001_per_class_pass_rate(self) -> None:
        """SEVAL-DT-001: 逐類 pass rate 正確（negative 未觸發=pass）。
        spec: skill-trigger-eval#negative-not-triggered-passes"""
        # direct 觸發(pass)、indirect 未觸發(fail)、兩個 negative 皆未觸發(pass)
        results = score_verdicts(verdicts(make_fixture(), [True, False, False, False]))
        scores = {str(s.cls): s.pass_rate for s in results[0].scores}
        assert scores == {"direct": 1.0, "indirect": 0.0, "negative": 1.0}

    def test_seval_dt_002_negative_triggered_fails(self) -> None:
        """SEVAL-DT-002: negative 被觸發 -> 該類 pass rate 下降。
        spec: skill-trigger-eval#negative-not-triggered-passes"""
        results = score_verdicts(verdicts(make_fixture(), [True, True, True, False]))
        neg = next(s for s in results[0].scores if str(s.cls) == "negative")
        assert neg.pass_rate == 0.5


class TestScoresThroughInterface:
    def test_seval_st_004_core_scores_via_stub_judge(self) -> None:
        """SEVAL-ST-004: 核心只透過 Judge 介面計分（stub 回固定 verdict，無 LLM）。
        spec: skill-trigger-eval#core-scores-via-interface"""
        tasks = build_tasks([make_fixture()])
        judge = FixedJudge([True, True, False, False])
        report = run_eval(judge, tasks, [False, False, False, False], {}, tolerance=0.1)
        # FixedJudge 忽略傳入 judgments，回其固定值：direct/indirect 觸發、negative 未觸發
        scores = {str(s.cls): s.pass_rate for s in report.results[0].scores}
        assert scores == {"direct": 1.0, "indirect": 1.0, "negative": 1.0}


class TestCompareBaseline:
    def test_seval_dt_003_regression_below_tolerance(self) -> None:
        """SEVAL-DT-003: pass rate 低於 baseline-tolerance -> 回歸。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        results = score_verdicts(
            verdicts(make_fixture(), [True, True, True, False])
        )  # negative 0.5
        regs = compare_baseline(results, {"demo": {"negative": 1.0}}, tolerance=0.1)
        assert len(regs) == 1
        assert regs[0].cls == TriggerPromptClass.NEGATIVE

    def test_seval_dt_004_within_tolerance_no_regression(self) -> None:
        """SEVAL-DT-004: 在容忍門檻內 -> 無回歸。
        spec: skill-trigger-eval#within-tolerance-passes"""
        results = score_verdicts(
            verdicts(make_fixture(), [True, True, False, False])
        )  # negative 1.0
        regs = compare_baseline(results, {"demo": {"negative": 1.0}}, tolerance=0.1)
        assert regs == []

    def test_seval_eg_001_no_baseline_no_regression(self) -> None:
        """SEVAL-EG-001: baseline 無此 skill -> 首評不誤報回歸。
        spec: skill-trigger-eval#within-tolerance-passes"""
        results = score_verdicts(verdicts(make_fixture(), [False, False, True, True]))  # 全爛
        assert compare_baseline(results, {}, tolerance=0.1) == []


class TestRunEval:
    def test_seval_st_002_end_to_end_with_agent_judge(self) -> None:
        """SEVAL-ST-002: AgentJudge + 注入 judgments 端到端跑出報告與回歸。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        tasks = build_tasks([make_fixture()])
        report = run_eval(
            AgentJudge(),
            tasks,
            [True, True, True, False],  # indirect ok, 一個 negative 被誤觸發
            {"demo": {"negative": 1.0}},
            tolerance=0.1,
        )
        assert report.has_regression is True
        assert report.regressions[0].cls == TriggerPromptClass.NEGATIVE


class TestAgentJudgeContract:
    def test_seval_eg_002_verdict_count_mismatch_raises(self) -> None:
        """SEVAL-EG-002: judgments 數與 manifest 不符 -> RuntimeError（不補零）。
        spec: skill-trigger-eval#verdict-count-mismatch-surfaced"""
        tasks = build_tasks([make_fixture()])
        judge = AgentJudge()
        with pytest.raises(RuntimeError, match="不符"):
            judge.score(judge.build_manifest(tasks), [True, False])


class TestFixtureLoading:
    def test_seval_eg_003_missing_fixture_surfaced(self, tmp_path: object) -> None:
        """SEVAL-EG-003: fixture 缺失 -> RuntimeError（不當作通過）。
        spec: skill-trigger-eval#absent-fixture-fails-loud"""
        with pytest.raises(RuntimeError, match="找不到 fixture"):
            load_fixture("nonexistent", skills_dir=tmp_path)  # type: ignore[arg-type]

    def test_seval_st_003_real_example_fixture_loads(self) -> None:
        """SEVAL-ST-003: 內附示範 fixture 可被載入並計分（rule 09 用真檔）。
        spec: skill-trigger-eval#valid-fixture-loads"""
        fx = load_fixture("pr-cycle-fast")
        tasks = build_tasks([fx])
        assert tasks, "示範 fixture 應產出至少一個評測任務"
        # 全部答對時 pass rate 皆為 1.0（重用 tasks，不重算 build_tasks）
        verdicts_all = AgentJudge().score(tasks, [t.expect_trigger for t in tasks])
        results = score_verdicts(verdicts_all)
        assert all(s.pass_rate == 1.0 for s in results[0].scores)


class TestResultsToBaseline:
    def test_seval_cv_001_baseline_shape(self) -> None:
        """SEVAL-CV-001: results_to_baseline 產出 skill->class->pass_rate。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        baseline = results_to_baseline(
            score_verdicts(verdicts(make_fixture(), [True, True, False, False]))
        )
        assert baseline["demo"]["direct"] == 1.0
        assert baseline["demo"]["negative"] == 1.0

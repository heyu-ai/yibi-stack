"""skill_eval 評測核心：建構任務、計分、baseline 比對。全程無 LLM 呼叫。"""

from .judges.base import Judge
from .models import (
    ClassScore,
    EvalReport,
    JudgeTask,
    PromptVerdict,
    Regression,
    SkillEvalResult,
    TriggerEvalFixture,
    TriggerPromptClass,
)

# 逐類計分與比對的固定順序（direct -> indirect -> negative）。
_CLASSES: tuple[TriggerPromptClass, ...] = (
    TriggerPromptClass.DIRECT,
    TriggerPromptClass.INDIRECT,
    TriggerPromptClass.NEGATIVE,
)

DEFAULT_TOLERANCE = 0.1


def build_tasks(fixtures: list[TriggerEvalFixture]) -> list[JudgeTask]:
    """把 fixtures 展平成穩定排序的 judge 任務清單（供 backend 判斷）。"""
    tasks: list[JudgeTask] = []
    for fixture in fixtures:
        for cls in _CLASSES:
            for prompt in fixture.prompts_for(cls):
                tasks.append(
                    JudgeTask(
                        index=len(tasks),
                        skill=fixture.skill,
                        cls=cls,
                        prompt=prompt.prompt,
                        expect_trigger=prompt.expect_trigger,
                    )
                )
    return tasks


def manifest_signature(tasks: list[JudgeTask]) -> list[list[object]]:
    """任務清單的穩定簽章（index+skill+cls+prompt+expect_trigger）。

    用來把 emit-manifest 當下的 fixture 狀態綁到 score 當下：兩次 build_tasks 之間若
    fixture 變動（W4 假設失效），簽章不符即可攔截 index 對位錯亂造成的靜默錯誤結果。
    """
    return [[t.index, t.skill, str(t.cls), t.prompt, t.expect_trigger] for t in tasks]


def score_verdicts(verdicts: list[PromptVerdict]) -> list[SkillEvalResult]:
    """把 verdict 依 skill 分組、逐類算 pass rate。direct/indirect pass=觸發，
    negative pass=未觸發（由 PromptVerdict.passed 推導，此處只彙總）。"""
    by_skill: dict[str, list[PromptVerdict]] = {}
    for verdict in verdicts:
        by_skill.setdefault(verdict.skill, []).append(verdict)

    results: list[SkillEvalResult] = []
    for skill in sorted(by_skill):
        skill_verdicts = by_skill[skill]
        scores: list[ClassScore] = []
        for cls in _CLASSES:
            cls_verdicts = [v for v in skill_verdicts if v.cls == cls]
            if not cls_verdicts:
                continue
            scores.append(
                ClassScore(
                    cls=cls,
                    total=len(cls_verdicts),
                    passed=sum(1 for v in cls_verdicts if v.passed),
                )
            )
        results.append(SkillEvalResult(skill=skill, scores=scores, verdicts=skill_verdicts))
    return results


def compare_baseline(
    results: list[SkillEvalResult],
    baseline: dict[str, dict[str, float]],
    tolerance: float = DEFAULT_TOLERANCE,
    evaluated_skills: set[str] | None = None,
) -> list[Regression]:
    """比對每個 skill 每個類別的 pass rate 與 baseline；低於 baseline-tolerance 記回歸。

    baseline 沒有該 skill/類別時視為無基準，不判回歸（首次評測不應誤報）。反向則**是**
    回歸：baseline 有、當前缺席，代表該類 prompt 被清空。走 baseline ∪ current 才能攔到，
    只走 results 會讓清空某一類成為無聲的 gate 繞道（issue #219）。

    `evaluated_skills` 界定 union 的範圍，必須是「本次真的有評的 skill」。少了它，
    `--skill foo` 會把 baseline 裡其他 31 個 skill 全判成缺席——那不是回歸，只是沒評到。
    預設取 results 的 skill 集合（等同舊行為的範圍）。
    """
    scope = evaluated_skills if evaluated_skills is not None else {r.skill for r in results}
    regressions: list[Regression] = []
    for result in results:
        if result.skill not in scope:
            continue
        skill_base = baseline.get(result.skill, {})
        for score in result.scores:
            base = skill_base.get(str(score.cls))
            if base is None:
                continue
            if score.pass_rate < base - tolerance:
                regressions.append(
                    Regression(
                        skill=result.skill,
                        cls=score.cls,
                        baseline=base,
                        current=score.pass_rate,
                    )
                )

    scored: set[tuple[str, str]] = {
        (result.skill, str(score.cls)) for result in results for score in result.scores
    }
    for skill in sorted(scope):
        for cls in _CLASSES:
            base = baseline.get(skill, {}).get(str(cls))
            if base is None or (skill, str(cls)) in scored:
                continue
            regressions.append(Regression(skill=skill, cls=cls, baseline=base, current=None))
    return regressions


def results_to_baseline(
    results: list[SkillEvalResult],
) -> dict[str, dict[str, float]]:
    """把評測結果轉為 baseline 形狀（skill -> class -> pass_rate）。"""
    return {
        result.skill: {str(score.cls): score.pass_rate for score in result.scores}
        for result in results
    }


def run_eval(
    judge: Judge,
    tasks: list[JudgeTask],
    judgments: list[bool],
    baseline: dict[str, dict[str, float]],
    tolerance: float = DEFAULT_TOLERANCE,
    evaluated_skills: set[str] | None = None,
) -> EvalReport:
    """完整評測流程：build_manifest -> score -> 計分 -> baseline 比對。

    judge 只需符合 Judge 介面（build_manifest / score），核心不依賴具體 backend。
    """
    manifest = judge.build_manifest(tasks)
    verdicts = judge.score(manifest, judgments)
    results = score_verdicts(verdicts)
    regressions = compare_baseline(results, baseline, tolerance, evaluated_skills)
    return EvalReport(results=results, regressions=regressions)

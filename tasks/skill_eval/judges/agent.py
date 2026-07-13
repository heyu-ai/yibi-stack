"""AgentJudge（Design B）：agent-driven 觸發判斷後端，無需 API key。

build_manifest 只回傳穩定排序的任務清單（純資料，無 LLM 呼叫）；實際判斷由
skills/skill-trigger-eval/SKILL.md 的 runbook 派 subagent 完成，judgments 再經
CLI 回饋給 score()。Python 端因此不含 LLM 依賴，核心可完整單元測試。
"""

from ..models import JudgeTask, PromptVerdict
from .base import Judge, verdicts_from_judgments


class AgentJudge(Judge):
    """由 agent session（SKILL.md 派 subagent）產生 judgments 的後端。"""

    name = "agent"

    def build_manifest(self, tasks: list[JudgeTask]) -> list[JudgeTask]:
        """agent backend 不重排，直接回傳原任務清單（index 已是穩定順序）。"""
        return list(tasks)

    def score(self, manifest: list[JudgeTask], judgments: list[bool]) -> list[PromptVerdict]:
        return verdicts_from_judgments(manifest, judgments)

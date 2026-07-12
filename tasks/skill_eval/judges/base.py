"""Judge 抽象介面：把「用哪個 LLM／認證判斷觸發」與計分核心解耦。

核心（service.py）只依賴此介面，不 import 任何 LLM client。Design A（api / acp）
與 Design B（agent）因此是同一模組的可替換 backend，run cadence 是上層編排選擇。
"""

from abc import ABC, abstractmethod

from ..models import JudgeTask, PromptVerdict


class Judge(ABC):
    """觸發判斷後端介面。"""

    name: str = ""

    @abstractmethod
    def build_manifest(self, tasks: list[JudgeTask]) -> list[JudgeTask]:
        """從評測任務建構要送去判斷的 manifest（可重排/批次；order 需穩定）。"""

    @abstractmethod
    def score(
        self, manifest: list[JudgeTask], judgments: list[bool]
    ) -> list[PromptVerdict]:
        """把回饋的 judgments（每個 task 是否觸發）映為 PromptVerdict。

        judgments 數與 manifest 不符時必須抛 RuntimeError，不得補零或截斷。
        """


def verdicts_from_judgments(
    manifest: list[JudgeTask], judgments: list[bool]
) -> list[PromptVerdict]:
    """共用計分：驗證長度一致後逐一組成 PromptVerdict。

    供各 backend 的 score() 重用——長度驗證是所有 backend 的共同契約。
    """
    if len(judgments) != len(manifest):
        raise RuntimeError(
            f"judgments 數（{len(judgments)}）與 manifest 數（{len(manifest)}）不符"
        )
    return [
        PromptVerdict(
            skill=task.skill,
            cls=task.cls,
            prompt=task.prompt,
            triggered=triggered,
            expect_trigger=task.expect_trigger,
        )
        for task, triggered in zip(manifest, judgments, strict=True)
    ]

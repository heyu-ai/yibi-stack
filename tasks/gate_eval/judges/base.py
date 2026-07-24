"""DispositionJudge 抽象介面：把 disposition 判定後端與計分核心解耦。

核心（service.py）只依賴此介面，不 import 任何 LLM client。實際判定由
skills 層的 runbook 派 subagent 完成，disposition 再經 CLI 帶回，故核心可完整單元測試。
"""

from abc import ABC, abstractmethod

from ..models import ConformanceFixture, RunOutcome


class DispositionJudge(ABC):
    """單一 fixture 的 disposition 判定後端介面。"""

    name: str = ""

    @abstractmethod
    def judge(self, fixture: ConformanceFixture) -> RunOutcome:
        """對一個 fixture 產生單次 disposition 判定，或回報執行失敗的 RunOutcome。"""

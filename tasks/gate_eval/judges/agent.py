"""AgentJudge：agent-driven disposition 後端，無需 API key。

實際判定由 skills 層 runbook 派 subagent 讀 pr-cycle-deep SKILL.md Step 5 後產生，
disposition 經 CLI 以 dispositions 檔帶回、綁到各 fixture 的 run。AgentJudge 只是把那些
已記錄的 outcome 依序回放，故 Python 端不含 LLM 依賴、核心可完整單元測試。

判定移入 Python 是 sunset 觸發條件三（被更好機制取代），故此後端刻意不自行推導 disposition。
"""

from ..models import ConformanceFixture, RunOutcome
from .base import DispositionJudge


class AgentJudge(DispositionJudge):
    """回放 agent session 產生（out-of-band）之 disposition 的後端。"""

    name = "agent"

    def __init__(self, recorded: dict[str, list[RunOutcome]]) -> None:
        # fixture_id -> 尚未回放的 outcome 佇列（會被逐次 pop）。
        self._queues: dict[str, list[RunOutcome]] = {
            fid: list(outcomes) for fid, outcomes in recorded.items()
        }

    def judge(self, fixture: ConformanceFixture) -> RunOutcome:
        queue = self._queues.get(fixture.id)
        if not queue:
            raise RuntimeError(
                f"fixture {fixture.id} 的已記錄 disposition 不足；"
                "請重新以 agent session 產生足夠次數的判定"
            )
        return queue.pop(0)

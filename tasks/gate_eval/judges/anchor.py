"""AnchorPresenceJudge：harness 自我測試用的 judge，非量測真實 agent 的生產後端。

它只判斷 fixture 綁定的 mutation anchor（一條 SKILL.md 矩陣列）是否仍在目標檔中：
在場即回傳 fixture 的正解，缺席即回傳一個刻意不同的 disposition。這讓 mutation-kill
（CONFORMANT -> NONCONFORMANT）可完整端到端、可決定性地驗證，等同 test_convergence_contract.py
的 anchor-mutation 手法。

它**不**編碼 disposition 矩陣邏輯（只查 anchor 在不在），故與 sunset 觸發條件三
「把 disposition 判定移入程式」無關——真正量測 agent 符合度的是 AgentJudge。
"""

from pathlib import Path

from ..models import ConformanceFixture, Disposition, RunOutcome
from .base import DispositionJudge

# anchor 缺席時回傳的「不同」disposition：與正解不同即可，用以觸發 NONCONFORMANT。
_FALLBACK = {
    Disposition.BLOCKING: Disposition.DEFERRED,
    Disposition.DEFERRED: Disposition.BLOCKING,
    Disposition.OUTSIDE_CONTRACT: Disposition.BLOCKING,
    Disposition.NON_BLOCKING: Disposition.BLOCKING,
}


class AnchorPresenceJudge(DispositionJudge):
    """依 fixture 的 anchor 是否在目標 SKILL.md 中，回正解或一個不同的 disposition。"""

    name = "anchor-presence"

    def __init__(self, skill_path: Path) -> None:
        self._text = skill_path.read_text(encoding="utf-8")

    def judge(self, fixture: ConformanceFixture) -> RunOutcome:
        if fixture.mutation.anchor in self._text:
            return RunOutcome(disposition=fixture.expected_disposition)
        return RunOutcome(disposition=_FALLBACK[fixture.expected_disposition])

"""gate_eval 評測核心：三值穩定度判定、守恆檢查、報告。全程無 LLM 呼叫。

judge 只需符合 DispositionJudge 介面；核心消費其產出的 RunOutcome 清單，故可完整單元測試
（LLM 判斷經 emit-manifest -> dispositions 檔帶進來，與 skill_eval 同形狀）。
"""

import math

from .judges.base import DispositionJudge
from .models import (
    ConformanceFixture,
    ConservationResult,
    Disposition,
    Finding,
    FixtureVerdict,
    RunOutcome,
    StabilityVerdict,
)

INITIAL_N = 5  # 首輪判定次數（成本下限，非統計推導）
RERUN_N = 15  # 首輪 UNSTABLE 時的加跑次數
MAJORITY_FRACTION = 0.8  # 多數門檻比例（n=5 -> 4；n=15 -> 12）

# 報告首行固定聲明本結果的界線（設計刻意冗餘，全綠與有紅皆印）。
LIMITATION = "本結果只證明對既有 gate 規則的符合度，不證明那些規則本身正確。"


def majority_threshold(n: int) -> int:
    """n 次判定達成多數所需的最小同 disposition 次數。"""
    return math.ceil(MAJORITY_FRACTION * n)


def _distribution(outcomes: list[RunOutcome]) -> dict[str, int]:
    """成功判定的 disposition 分佈；執行失敗不計入。"""
    dist: dict[str, int] = {}
    for outcome in outcomes:
        if outcome.failed:
            continue
        key = str(outcome.disposition)
        dist[key] = dist.get(key, 0) + 1
    return dist


def _classify(
    expected: Disposition, outcomes: list[RunOutcome]
) -> tuple[StabilityVerdict, Disposition | None, dict[str, int]]:
    """依門檻把一組 outcome 映為三值判定；UNSTABLE 不併入 NONCONFORMANT。"""
    dist = _distribution(outcomes)
    threshold = majority_threshold(len(outcomes))
    if not dist:
        return StabilityVerdict.UNSTABLE, None, dist
    top_key, top_count = max(dist.items(), key=lambda kv: kv[1])
    if top_count < threshold:
        return StabilityVerdict.UNSTABLE, None, dist
    majority = Disposition(top_key)
    if majority == expected:
        return StabilityVerdict.CONFORMANT, majority, dist
    return StabilityVerdict.NONCONFORMANT, majority, dist


def needs_rerun(verdict: StabilityVerdict) -> bool:
    """首輪落在無多數（UNSTABLE）時須加跑至 RERUN_N 後重判。"""
    return verdict == StabilityVerdict.UNSTABLE


def evaluate_fixture(
    fixture_id: str,
    expected: Disposition,
    initial_outcomes: list[RunOutcome],
    rerun_outcomes: list[RunOutcome] | None = None,
) -> FixtureVerdict:
    """把 fixture 的判定 outcome 映為 FixtureVerdict。

    首輪 UNSTABLE 且有提供 rerun_outcomes 時，verdict 取自 rerun 分佈並標記 reran。
    首輪 UNSTABLE 但未提供 rerun_outcomes 時，回報首輪 UNSTABLE（reran=False），由呼叫端
    決定是否補跑——不靜默假裝已加跑。
    """
    verdict, majority, dist = _classify(expected, initial_outcomes)
    if verdict != StabilityVerdict.UNSTABLE or rerun_outcomes is None:
        return FixtureVerdict(
            fixture_id=fixture_id,
            expected=expected,
            verdict=verdict,
            majority_disposition=majority,
            total_runs=len(initial_outcomes),
            execution_failures=sum(1 for o in initial_outcomes if o.failed),
            reran=False,
            distribution=dist,
        )
    verdict2, majority2, dist2 = _classify(expected, rerun_outcomes)
    return FixtureVerdict(
        fixture_id=fixture_id,
        expected=expected,
        verdict=verdict2,
        majority_disposition=majority2,
        total_runs=len(rerun_outcomes),
        execution_failures=sum(1 for o in rerun_outcomes if o.failed),
        reran=True,
        distribution=dist2,
    )


def run_fixture_with_judge(
    judge: DispositionJudge, fixture: ConformanceFixture, n: int
) -> list[RunOutcome]:
    """呼叫 judge n 次；judge 拋例外時轉為執行失敗的 RunOutcome，不中斷整批。

    執行失敗與『判定為 deferred』刻意分離：前者 disposition 為 None 且帶 error，
    _distribution 不計入，故不污染 disposition 統計。
    """
    outcomes: list[RunOutcome] = []
    for _ in range(n):
        try:
            outcomes.append(judge.judge(fixture))
        except Exception as e:  # noqa: BLE001 — judge 後端任何失敗都記為執行失敗，不吞
            outcomes.append(RunOutcome(disposition=None, error=f"judge 執行失敗：{e}"))
    return outcomes


def check_conservation(inputs: list[Finding], outputs: list[Finding]) -> ConservationResult:
    """每筆輸入 finding 須在輸出恰好一次且標題描述逐字保留；否則記守恆失敗。"""
    out_by_title: dict[str, list[Finding]] = {}
    for f in outputs:
        out_by_title.setdefault(f.title, []).append(f)

    missing: list[str] = []
    duplicated: list[str] = []
    altered: list[str] = []
    for f in inputs:
        matches = out_by_title.get(f.title, [])
        if not matches:
            missing.append(f.title)
            continue
        if len(matches) > 1:
            duplicated.append(f.title)
        if any(m.description != f.description for m in matches):
            altered.append(f.title)

    ok = not (missing or duplicated or altered)
    return ConservationResult(ok=ok, missing=missing, duplicated=duplicated, altered=altered)


def render_report(conservation: ConservationResult, verdicts: list[FixtureVerdict]) -> str:
    """組出人類可讀報告；首行固定為界線聲明，守恆結果排在 disposition verdict 之前。"""
    lines = [f"[LIMIT] {LIMITATION}", ""]

    lines.append("## 守恆檢查")
    if conservation.ok:
        lines.append("  [OK] 每筆輸入 finding 在輸出恰好一次且原文保留")
    else:
        for title in conservation.missing:
            lines.append(f"  [FAIL] 遺失：{title}")
        for title in conservation.duplicated:
            lines.append(f"  [FAIL] 重複：{title}")
        for title in conservation.altered:
            lines.append(f"  [FAIL] 描述被改寫：{title}")
    lines.append("")

    lines.append("## disposition 判定")
    for fv in verdicts:
        flag = "reran@15" if fv.reran else f"n={fv.total_runs}"
        lines.append(
            f"  {fv.fixture_id}: {fv.verdict} "
            f"(expected={fv.expected}, majority={fv.majority_disposition}, "
            f"{flag}, fails={fv.execution_failures}, dist={fv.distribution})"
        )
    return "\n".join(lines)

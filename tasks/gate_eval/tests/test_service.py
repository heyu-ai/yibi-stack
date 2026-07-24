"""gate_eval 判定核心測試：三值穩定度、邊界重跑、執行失敗區隔、守恆、報告首行。"""

import pytest

from tasks.gate_eval.judges.base import DispositionJudge
from tasks.gate_eval.models import (
    ConformanceFixture,
    ContractMapping,
    Disposition,
    EvidenceForm,
    Factors,
    Finding,
    MutationDescriptor,
    Round,
    RunOutcome,
    Severity,
    StabilityVerdict,
)
from tasks.gate_eval.service import (
    LIMITATION,
    check_conservation,
    evaluate_fixture,
    majority_threshold,
    render_report,
    run_fixture_with_judge,
)


def outcomes(*dispositions: Disposition | None) -> list[RunOutcome]:
    """把 disposition 序列轉為 RunOutcome；None 代表執行失敗。"""
    return [
        RunOutcome(disposition=d) if d is not None else RunOutcome(error="執行失敗")
        for d in dispositions
    ]


B = Disposition.BLOCKING
D = Disposition.DEFERRED


class TestThreshold:
    def test_geval_dt_003_threshold_values(self) -> None:
        """GEVAL-DT-003: n=5 門檻為 4，n=15 為 12。"""
        assert majority_threshold(5) == 4
        assert majority_threshold(15) == 12


class TestThreeValuedVerdict:
    """GEVAL-DT-004: spec 的 verdict boundaries 表格逐列（n=5）。"""

    @pytest.mark.parametrize(
        ("dist", "expected", "verdict"),
        [
            ([B, B, B, B, B], B, StabilityVerdict.CONFORMANT),
            ([B, B, B, B, D], B, StabilityVerdict.CONFORMANT),
            ([D, D, D, D, B], B, StabilityVerdict.NONCONFORMANT),
            ([B, B, B, D, D], B, StabilityVerdict.UNSTABLE),
            ([B, B, D, D, Disposition.OUTSIDE_CONTRACT], B, StabilityVerdict.UNSTABLE),
        ],
    )
    def test_geval_dt_004_verdict_boundaries(
        self, dist: list[Disposition], expected: Disposition, verdict: StabilityVerdict
    ) -> None:
        fv = evaluate_fixture("fx", expected, outcomes(*dist))
        assert fv.verdict == verdict

    def test_geval_dt_005_unstable_not_collapsed_to_nonconformant(self) -> None:
        """GEVAL-DT-005: 無多數回 UNSTABLE，不併入 NONCONFORMANT。"""
        fv = evaluate_fixture("fx", B, outcomes(B, B, D, D, Disposition.OUTSIDE_CONTRACT))
        assert fv.verdict == StabilityVerdict.UNSTABLE
        # UNSTABLE 的判別特徵：無多數 -> majority_disposition 為 None（與 NONCONFORMANT 有多數不同）
        assert fv.majority_disposition is None


class TestRerun:
    def test_geval_st_003_three_two_split_reruns_and_verdict_from_15(self) -> None:
        """GEVAL-ST-003: 首輪 3:2（UNSTABLE）觸發重跑，verdict 取自 15 次分佈。"""
        initial = outcomes(B, B, B, D, D)  # 3:2 -> UNSTABLE
        rerun = outcomes(*([B] * 13 + [D] * 2))  # 13:2 -> 達 12 門檻 -> CONFORMANT
        fv = evaluate_fixture("fx", B, initial, rerun_outcomes=rerun)
        assert fv.reran is True
        assert fv.total_runs == 15
        assert fv.verdict == StabilityVerdict.CONFORMANT

    def test_geval_st_004_unanimous_does_not_rerun(self) -> None:
        """GEVAL-ST-004: 首輪 5:0 為終局，不重跑（即使有提供 rerun_outcomes）。"""
        fv = evaluate_fixture("fx", B, outcomes(B, B, B, B, B), rerun_outcomes=outcomes(D, D, D))
        assert fv.reran is False
        assert fv.verdict == StabilityVerdict.CONFORMANT

    def test_geval_st_005_four_one_is_final_not_rerun(self) -> None:
        """GEVAL-ST-005: 4:1 達門檻即終局 CONFORMANT，不重跑（design D3 reconcile）。"""
        fv = evaluate_fixture("fx", B, outcomes(B, B, B, B, D), rerun_outcomes=outcomes(D, D, D))
        assert fv.reran is False
        assert fv.verdict == StabilityVerdict.CONFORMANT


class _RaisingJudge(DispositionJudge):
    name = "raising"

    def judge(self, fixture: ConformanceFixture) -> RunOutcome:
        raise RuntimeError("backend 壞了")


class _FailOutcomeJudge(DispositionJudge):
    name = "failout"

    def judge(self, fixture: ConformanceFixture) -> RunOutcome:
        return RunOutcome(error="逾時")


def _fixture() -> ConformanceFixture:
    return ConformanceFixture(
        id="fx",
        finding_text="x",
        factors=Factors(
            severity=Severity.CRITICAL,
            evidence=EvidenceForm.VALID,
            round=Round.R1,
            contract_mapping=ContractMapping.VALID,
        ),
        expected_disposition=B,
        mutation=MutationDescriptor(anchors=["row"]),
    )


class TestExecutionFailure:
    def test_geval_st_006_raising_backend_recorded_as_failure(self) -> None:
        """GEVAL-ST-006: judge 拋例外轉為執行失敗，不中斷整批。"""
        outs = run_fixture_with_judge(_RaisingJudge(), _fixture(), 3)
        assert len(outs) == 3
        assert all(o.failed for o in outs)

    def test_geval_st_007_failures_excluded_from_disposition_stats(self) -> None:
        """GEVAL-ST-007: 執行失敗不計入 disposition 統計（與『判定為 deferred』分離）。"""
        # 4 個 blocking + 1 個執行失敗：分佈只算 4 個成功，門檻 ceil(0.8*5)=4 -> CONFORMANT
        outs = outcomes(B, B, B, B, None)
        fv = evaluate_fixture("fx", B, outs)
        assert fv.execution_failures == 1
        assert fv.distribution == {"blocking": 4}
        assert fv.verdict == StabilityVerdict.CONFORMANT

    def test_geval_st_008_fail_outcome_judge_all_failed(self) -> None:
        """GEVAL-ST-008: 回傳失敗 outcome 的 backend，全數記為失敗。"""
        outs = run_fixture_with_judge(_FailOutcomeJudge(), _fixture(), 4)
        assert sum(1 for o in outs if o.failed) == 4


class TestConservation:
    def test_geval_st_009_all_preserved_ok(self) -> None:
        """GEVAL-ST-009: 每筆輸入在輸出恰好一次且原文保留 -> ok。"""
        inp = [Finding(title="A", description="da"), Finding(title="B", description="db")]
        res = check_conservation(inp, list(inp))
        assert res.ok

    def test_geval_st_010_dropped_finding_named(self) -> None:
        """GEVAL-ST-010: 輸出遺漏一筆 -> 守恆失敗並指名（守恆對照組）。"""
        inp = [Finding(title="A", description="da"), Finding(title="B", description="db")]
        res = check_conservation(inp, [inp[0]])
        assert not res.ok
        assert res.missing == ["B"]

    def test_geval_st_011_altered_description_named(self) -> None:
        """GEVAL-ST-011: 標題在但描述被改寫 -> 守恆失敗並指名。"""
        inp = [Finding(title="A", description="da")]
        out = [Finding(title="A", description="改寫過")]
        res = check_conservation(inp, out)
        assert not res.ok
        assert res.altered == ["A"]

    def test_geval_st_012_duplicated_finding_named(self) -> None:
        """GEVAL-ST-012: 輸出重複同標題 -> 守恆失敗並指名。"""
        inp = [Finding(title="A", description="da")]
        out = [Finding(title="A", description="da"), Finding(title="A", description="da")]
        res = check_conservation(inp, out)
        assert not res.ok
        assert res.duplicated == ["A"]


class TestReport:
    def test_geval_st_013_first_line_is_limitation_when_green(self) -> None:
        """GEVAL-ST-013: 全綠時報告首行仍為界線聲明。"""
        from tasks.gate_eval.models import ConservationResult

        fv = evaluate_fixture("fx", B, outcomes(B, B, B, B, B))
        report = render_report(ConservationResult(ok=True), [fv])
        assert report.splitlines()[0] == f"[LIMIT] {LIMITATION}"

    def test_geval_st_014_first_line_is_limitation_when_red(self) -> None:
        """GEVAL-ST-014: 有紅時報告首行仍為界線聲明，且守恆排在 verdict 之前。"""
        from tasks.gate_eval.models import ConservationResult

        fv = evaluate_fixture("fx", B, outcomes(D, D, D, D, D))
        report = render_report(ConservationResult(ok=False, missing=["X"]), [fv])
        lines = report.splitlines()
        assert lines[0] == f"[LIMIT] {LIMITATION}"
        assert report.index("守恆檢查") < report.index("disposition 判定")

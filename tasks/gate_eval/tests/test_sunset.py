"""gate_eval sunset 協議測試：mutation 機制、有效性、prune、suite sunset、CLI 結構。"""

from pathlib import Path

import pytest

from tasks._paths import PROJECT_ROOT
from tasks.gate_eval.models import (
    AlertClass,
    FixtureWindowRecord,
    MutationDescriptor,
    PruneAction,
    StabilityVerdict,
    SuiteWindow,
    SunsetTrigger,
)
from tasks.gate_eval.sunset import (
    MutationAnchorNotFound,
    apply_mutation,
    classify_prune,
    evaluate_suite_sunset,
    is_effective,
    restore_and_invalidate,
)


class TestMutationMechanism:
    def test_geval_eg_003_absent_anchor_halts_named(self, tmp_path: Path) -> None:
        """GEVAL-EG-003: anchor 找不到即中止並指名 fixture 與 anchor，不靜默略過。"""
        target = tmp_path / "SKILL.md"
        target.write_text("some content without the row", encoding="utf-8")
        mut = MutationDescriptor(anchors=["| Critical | valid | blocking | blocking |"])
        with pytest.raises(MutationAnchorNotFound, match="f01"):
            apply_mutation(target, mut, "f01")

    def test_geval_st_015_apply_returns_original_and_mutates(self, tmp_path: Path) -> None:
        """GEVAL-ST-015: apply 回傳原文且就地移除 anchor。"""
        target = tmp_path / "SKILL.md"
        target.write_text("before | ROW | after", encoding="utf-8")
        mut = MutationDescriptor(anchors=["| ROW |"], replacement="")
        original = apply_mutation(target, mut, "fx")
        assert original == "before | ROW | after"
        assert "| ROW |" not in target.read_text(encoding="utf-8")

    def test_geval_st_016_restore_clears_cache_and_bumps_mtime(self, tmp_path: Path) -> None:
        """GEVAL-ST-016: 還原後清除 module_root 下 __pycache__ 並更新來源檔 mtime。"""
        module_root = tmp_path / "mod"
        (module_root / "sub" / "__pycache__").mkdir(parents=True)
        (module_root / "sub" / "__pycache__" / "x.pyc").write_bytes(b"stale")
        source = module_root / "src.md"
        source.write_text("mutated", encoding="utf-8")
        old_mtime = 1_000_000.0
        import os

        os.utime(source, (old_mtime, old_mtime))

        restore_and_invalidate(source, "restored", module_root)

        assert source.read_text(encoding="utf-8") == "restored"
        assert not (module_root / "sub" / "__pycache__").exists()
        assert source.stat().st_mtime > old_mtime


class TestEffectiveness:
    def test_geval_dt_006_killed_is_effective(self) -> None:
        """GEVAL-DT-006: CONFORMANT -> NONCONFORMANT 判定為有效。"""
        assert is_effective(StabilityVerdict.CONFORMANT, StabilityVerdict.NONCONFORMANT)

    def test_geval_dt_007_survived_is_ineffective(self) -> None:
        """GEVAL-DT-007: mutation 後仍 CONFORMANT 判定為無效。"""
        assert not is_effective(StabilityVerdict.CONFORMANT, StabilityVerdict.CONFORMANT)

    def test_geval_dt_008_unstable_transition_not_effective(self) -> None:
        """GEVAL-DT-008: 轉為 UNSTABLE 不算被殺（有效性只認 NONCONFORMANT）。"""
        assert not is_effective(StabilityVerdict.CONFORMANT, StabilityVerdict.UNSTABLE)


class TestPruneClassification:
    """GEVAL-DT-009: spec 的 prune recommendation 表格逐列。"""

    @pytest.mark.parametrize(
        ("kills", "alerts", "repaired", "action"),
        [
            (True, [AlertClass.TRUE], False, PruneAction.KEEP),
            (True, [], False, PruneAction.DEMOTE),
            (False, [AlertClass.TRUE], False, PruneAction.REMOVE),
            (True, [AlertClass.FALSE], False, PruneAction.REPAIR),
            (True, [AlertClass.FALSE], True, PruneAction.REMOVE),
        ],
    )
    def test_geval_dt_009_prune_table(
        self, kills: bool, alerts: list[AlertClass], repaired: bool, action: PruneAction
    ) -> None:
        rec = FixtureWindowRecord(
            fixture_id="fx",
            mutation_kills=kills,
            alerts=alerts,
            false_alarm_repaired_once=repaired,
        )
        assert classify_prune(rec).action == action

    def test_geval_dt_010_unclassified_counts_as_false_alarm(self) -> None:
        """GEVAL-DT-010: 未分類的紅燈併入假警報（第一次 -> REPAIR，非 KEEP）。"""
        rec = FixtureWindowRecord(
            fixture_id="fx",
            mutation_kills=True,
            alerts=[AlertClass.UNCLASSIFIED],
            false_alarm_repaired_once=False,
        )
        assert classify_prune(rec).action == PruneAction.REPAIR


class TestSuiteSunset:
    def test_geval_dt_011_no_alerts_two_windows(self) -> None:
        """GEVAL-DT-011: 連續兩窗口無警報 -> 觸發移除評估。"""
        windows = [SuiteWindow(any_fixture_alerted=False), SuiteWindow(any_fixture_alerted=False)]
        res = evaluate_suite_sunset(windows, superseded_by_code=False)
        assert res.due_for_removal
        assert SunsetTrigger.NO_ALERTS_TWO_WINDOWS in res.triggers

    def test_geval_dt_012_noise_dominant(self) -> None:
        """GEVAL-DT-012: 最近窗口假警報多於真警報 -> 觸發移除評估。"""
        windows = [SuiteWindow(true_alerts=1, false_alarms=3, any_fixture_alerted=True)]
        res = evaluate_suite_sunset(windows, superseded_by_code=False)
        assert SunsetTrigger.NOISE_DOMINANT in res.triggers

    def test_geval_dt_013_superseded_by_code_notes_not_failure(self) -> None:
        """GEVAL-DT-013: 被程式取代 -> 觸發，且註明屬取代而非失敗。"""
        res = evaluate_suite_sunset(
            [SuiteWindow(any_fixture_alerted=True)], superseded_by_code=True
        )
        assert SunsetTrigger.SUPERSEDED_BY_CODE in res.triggers
        assert any("取代" in n for n in res.notes)

    def test_geval_dt_014_no_trigger_reverse_case(self) -> None:
        """GEVAL-DT-014: 三條件皆不成立 -> 不進入移除評估（反向對照）。"""
        windows = [
            SuiteWindow(true_alerts=2, false_alarms=1, any_fixture_alerted=True),
            SuiteWindow(true_alerts=1, false_alarms=0, any_fixture_alerted=True),
        ]
        res = evaluate_suite_sunset(windows, superseded_by_code=False)
        assert not res.due_for_removal
        assert res.triggers == []


class TestRemovalIsDeletion:
    """GEVAL-ST-017: 移除成本維持在刪除等級——不進 pre-commit，三子命令皆可觸發。"""

    def test_geval_st_017_not_in_precommit(self) -> None:
        cfg = PROJECT_ROOT / ".pre-commit-config.yaml"
        text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
        assert "gate_eval" not in text, (
            "gate_eval 不應出現在 pre-commit 設定（移除成本須維持刪除等級）"
        )

    def test_geval_st_018_three_subcommands_registered(self) -> None:
        from tasks.gate_eval.cli import cli

        assert set(cli.commands) == {"eval", "mutation-verify", "sunset-report"}

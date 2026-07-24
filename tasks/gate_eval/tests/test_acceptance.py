"""驗收對照組（deterministic 半）：控制組一變紅、控制組二 mutation-kill 端到端。

控制組二此處以 AnchorPresenceJudge 自我測試 harness——證明「規則列被移除時 harness 會由
CONFORMANT 轉 NONCONFORMANT」。量測真實 agent 符合度的生產跑（AgentJudge）需 agent session，
記錄於 issue #337，不在單元測試內。
"""

import shutil
from pathlib import Path

import pytest

from tasks._paths import PROJECT_ROOT
from tasks.gate_eval.config import (
    check_fixture_oracle_consistency,
    load_fixture_file,
    load_fixtures,
    load_oracle,
)
from tasks.gate_eval.judges.anchor import AnchorPresenceJudge
from tasks.gate_eval.models import Disposition, Severity, StabilityVerdict
from tasks.gate_eval.service import INITIAL_N, evaluate_fixture, run_fixture_with_judge
from tasks.gate_eval.sunset import apply_mutation, is_effective

SKILL = PROJECT_ROOT / "plugins" / "pr-flow" / "skills" / "pr-cycle-deep" / "SKILL.md"
FINDINGS = PROJECT_ROOT / "tasks" / "gate_eval" / "fixtures" / "findings"
# 三個代表不同 tier 的 fixture（tier 欄位見各 fixture 檔）
TIER_FIXTURES = ["f03_crit_none_r1", "f06_imp_valid_r2", "f09_nit_valid_r1"]


class TestControlOneRedOnMislabel:
    def test_geval_st_019_mislabeled_fixture_makes_eval_red(self, tmp_path: Path) -> None:
        """GEVAL-ST-019: 刻意標錯期望 disposition 的 fixture 使一致性檢查變紅並指名。"""
        from tasks.gate_eval.tests.test_models import make_factors, write_fixture

        d = tmp_path / "findings"
        d.mkdir()
        write_fixture(d / "ok.json", id="ok", expected_disposition=Disposition.BLOCKING)
        write_fixture(d / "bad.json", id="mislabeled", expected_disposition=Disposition.DEFERRED)
        write_fixture(
            d / "nb.json",
            id="nb",
            expected_disposition=Disposition.NON_BLOCKING,
            factors=make_factors(severity=Severity.NIT),
        )
        oracle = load_oracle()
        fixtures = load_fixtures(d)
        with pytest.raises(RuntimeError, match="mislabeled"):
            check_fixture_oracle_consistency(fixtures, oracle)


class TestControlTwoMutationKill:
    """GEVAL-ST-020: 三個 tier fixture 各套一次獨立 mutation，皆由 CONFORMANT 轉 NONCONFORMANT。"""

    @pytest.mark.parametrize("fixture_id", TIER_FIXTURES)
    def test_geval_st_020_mutation_kills_tier_fixture(
        self, fixture_id: str, tmp_path: Path
    ) -> None:
        fx = load_fixture_file(FINDINGS / f"{fixture_id}.json")
        skill_copy = tmp_path / "SKILL.md"
        shutil.copy2(SKILL, skill_copy)

        # 乾淨 SKILL：anchor 在場 -> 全數回正解 -> CONFORMANT
        clean_judge = AnchorPresenceJudge(skill_copy)
        before = evaluate_fixture(
            fx.id, fx.expected_disposition, run_fixture_with_judge(clean_judge, fx, INITIAL_N)
        )
        assert before.verdict == StabilityVerdict.CONFORMANT

        # 套用該 fixture 的 mutation（移除其矩陣列）
        apply_mutation(skill_copy, fx.mutation, fx.id)
        assert fx.mutation.anchor not in skill_copy.read_text(encoding="utf-8")

        # mutated SKILL：anchor 缺席 -> 全數回不同值 -> NONCONFORMANT（被殺）
        mut_judge = AnchorPresenceJudge(skill_copy)
        after = evaluate_fixture(
            fx.id, fx.expected_disposition, run_fixture_with_judge(mut_judge, fx, INITIAL_N)
        )
        assert after.verdict == StabilityVerdict.NONCONFORMANT
        assert is_effective(before.verdict, after.verdict)

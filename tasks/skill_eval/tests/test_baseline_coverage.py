"""baseline 覆蓋一致性測試（deterministic，可在 headless CI 跑）。

觸發回歸 gate 本身需要 LLM judge，無法在 headless CI 執行；但「每個有 fixture 的 skill
是否都有對應 baseline 條目」是純結構檢查，可以。這正是 config.py 反覆強調的靜默失效：
新增 fixture 卻忘了寫 baseline -> compare_baseline 走 `base is None` 略過該 skill ->
0.00 的 pass rate 也回報無回歸。此檔把那個漂移在 CI 擋下。
"""

from tasks.skill_eval.config import discover_fixtures, load_baseline, load_fixture
from tasks.skill_eval.models import TriggerPromptClass


class TestBaselineCoverage:
    def test_seval_bc_001_baseline_file_exists_and_valid(self) -> None:
        """SEVAL-BC-001: baseline 檔存在且形狀合法（load_baseline 會驗 shape 與 class key）。
        spec: skill-trigger-eval#baseline-tracked-in-git"""
        baseline = load_baseline()
        assert baseline, (
            "baseline 為空：baselines/trigger_baseline.json 缺失或未涵蓋任何 skill；"
            "gitignore 掉或未建立的 baseline 讓回歸 gate 結構上恆略過（issue #220）"
        )

    def test_seval_bc_002_every_fixture_skill_has_baseline_entry(self) -> None:
        """SEVAL-BC-002: 每個含 trigger_eval.json 的 skill 都必須在 baseline 有條目。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        baseline = load_baseline()
        missing = [s for s in discover_fixtures() if s not in baseline]
        assert not missing, (
            f"下列 skill 有 fixture 卻無 baseline 條目，會靜默離開回歸 gate："
            f"{', '.join(missing)}。請重跑 skill-trigger-eval 的 baseline 步驟"
            "（uv run python -m tasks.skill_eval baseline --all ...）"
        )

    def test_seval_bc_003_nonempty_class_has_baseline_rate(self) -> None:
        """SEVAL-BC-003: fixture 中每個「非空」的 prompt 類別都必須在 baseline 有 pass_rate。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero

        空類別不需要 baseline（results_to_baseline 本就不產生），但非空類別若缺 baseline，
        該類會靜默離開 gate——正是 config.py 的錯字 key 註解所述的漂移。
        """
        baseline = load_baseline()
        gaps: list[str] = []
        for skill in discover_fixtures():
            fx = load_fixture(skill)
            skill_base = baseline.get(skill, {})
            for cls in TriggerPromptClass:
                if fx.prompts_for(cls) and str(cls) not in skill_base:
                    gaps.append(f"{skill}/{cls}")
        assert not gaps, (
            f"下列 skill 的非空類別在 baseline 缺 pass_rate，會靜默離開 gate：{', '.join(gaps)}"
        )

"""baseline 覆蓋一致性測試（deterministic，可在 headless CI 跑）。

觸發回歸 gate 本身需要 LLM judge，無法在 headless CI 執行；但「每個有 fixture 的 skill
是否都有對應 baseline 條目」是純結構檢查，可以。這正是 config.py 反覆強調的靜默失效：
新增 fixture 卻忘了寫 baseline -> compare_baseline 走 `base is None` 略過該 skill ->
0.00 的 pass rate 也回報無回歸。此檔把那個漂移在 CI 擋下。

BC-001~003 守 fixture->baseline 單向；BC-004 用集合相等把雙向漂移與 vacuous-pass
（discover_fixtures() 回空集時 BC-002/003 的迴圈退化成零檢查仍綠）一次鎖住；BC-005
交叉檢查 fixture 的 skill 欄位並讓 AC-2（model_validate round-trip）有明確 owner。
（PR #396 mob review：silent-failure-hunter / Codex 收斂的 Important + code-reviewer /
pr-test-analyzer 的 NIT。）
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

    def test_seval_bc_004_baseline_and_fixtures_are_bijective(self) -> None:
        """SEVAL-BC-004: baseline 的 skill 集合必須與 discover_fixtures() 完全相等。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero

        鎖住 BC-002/003 蓋不到的兩個洞（PR #396 mob review 收斂）：
        1. 反向漂移：fixture 被刪、baseline 卻留 stale entry（BC-002/003 只迭代
           discover_fixtures()，看不到孤兒 baseline entry）。
        2. vacuous-pass：若 discover_fixtures() 因 glob 迴歸（如 `**` 退成 `*`）或 fixture
           全刪而回空集，BC-002/003 的迴圈退化成零檢查仍綠；但 committed baseline 非空，
           空集 != 非空集 -> 本測試紅，堵住該假綠。
        """
        fixtures = set(discover_fixtures())
        baseline = set(load_baseline())
        assert fixtures, (
            "discover_fixtures() 回空集——glob 迴歸或 fixture 全刪，"
            "BC-002/003 會 vacuous-pass；gate 形同不存在"
        )
        assert fixtures == baseline, (
            "fixture 與 baseline 的 skill 集合不一致："
            f"缺 baseline 條目={sorted(fixtures - baseline)}；"
            f"stale baseline（fixture 已不存在）={sorted(baseline - fixtures)}。"
            "重跑 skill-trigger-eval 的 baseline 步驟（baseline --all）以同步"
        )

    def test_seval_bc_005_fixture_skill_field_matches_directory(self) -> None:
        """SEVAL-BC-005: 每份 fixture 的 skill 欄位須等於其目錄名；順帶讓 AC-2 有 owner。
        spec: skill-trigger-eval#valid-fixture-loads

        index/baseline 以目錄名為 key，JSON 內 `skill` 欄位卻從不比對——下一份 fixture
        若 copy-paste 錯 `skill` 仍 parse、仍拿到目錄名的 baseline entry，錯配靜默。
        本測試對每份 fixture 呼叫 load_fixture（會跑 TriggerEvalFixture.model_validate，
        即 AC-2 的 expect_trigger polarity 檢查），並斷言 skill 欄位相符。
        """
        mismatches: list[str] = []
        for skill in discover_fixtures():
            fx = load_fixture(skill)  # 觸發 model_validate -> check_expect_trigger（AC-2）
            if fx.skill != skill:
                mismatches.append(f"{skill}: fixture skill 欄位為 {fx.skill!r}")
        assert not mismatches, (
            f"fixture 的 skill 欄位與目錄名不符（copy-paste 錯配）：{', '.join(mismatches)}"
        )

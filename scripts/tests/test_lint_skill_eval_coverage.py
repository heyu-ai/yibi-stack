"""lint_skill_eval_coverage 純函式測試（合成 diff fixture）。

關鍵：只對真實檔案斷言的 lint 無法測自己的失敗路徑。這裡以純函式入口 + 合成 diff +
注入的存在性判斷驗證負向案例——尤其是「改 description 卻沒動 fixture」與「rename 進
skills/ 的新 skill」兩條，它們正是 gate 靜默失效的形狀。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lint_skill_eval_coverage import (  # noqa: E402
    check_skill_eval_coverage,
    main,
)


def diff_for(path: str, added: list[str], old_path: str | None = None) -> str:
    """組一份最小 unified diff（單檔、單 hunk）。old_path 預設為新增檔（/dev/null）。"""
    old = old_path or "/dev/null"
    old_line = "--- /dev/null" if old == "/dev/null" else f"--- a/{old}"
    body = "".join(f"+{line}\n" for line in added)
    return f"diff --git a/{old} b/{path}\n{old_line}\n+++ b/{path}\n@@ -0,0 +1 @@\n{body}"


ALWAYS = lambda _skill: True  # noqa: E731 — 測試用的存在性樁
NEVER = lambda _skill: False  # noqa: E731


class TestDescriptionChange:
    def test_slec_dt_001_description_changed_without_fixture_touch_warns(self) -> None:
        """SLEC-DT-001: 改 description 但同 diff 未動 fixture -> 回報。

        這是最常見的靜默失效：eval 照跑照報 [OK]，比對的卻是改動前的觸發假設。
        """
        diff = diff_for(
            "skills/demo/SKILL.md",
            ["description: 新的觸發描述"],
            old_path="skills/demo/SKILL.md",
        )
        msgs = check_skill_eval_coverage(diff, ALWAYS)
        assert len(msgs) == 1
        assert "未改動 trigger_eval.json" in msgs[0]

    def test_slec_dt_002_description_and_fixture_both_touched_passes(self) -> None:
        """SLEC-DT-002: description 與 fixture 同 diff 改動 -> 通過。"""
        diff = diff_for(
            "skills/demo/SKILL.md", ["description: 新描述"], old_path="skills/demo/SKILL.md"
        ) + diff_for(
            "skills/demo/trigger_eval.json",
            ['  {"prompt": "x", "expect_trigger": true}'],
            old_path="skills/demo/trigger_eval.json",
        )
        assert check_skill_eval_coverage(diff, ALWAYS) == []

    def test_slec_dt_003_body_only_change_ignored(self) -> None:
        """SLEC-DT-003: 只動 body 不動 description -> 不回報（觸發面未變）。"""
        diff = diff_for(
            "skills/demo/SKILL.md",
            ["## Step 5 — 新增一段說明", "這段跟觸發無關。"],
            old_path="skills/demo/SKILL.md",
        )
        assert check_skill_eval_coverage(diff, NEVER) == []

    def test_slec_eg_001_description_word_in_prose_does_not_fire(self) -> None:
        """SLEC-EG-001: body 散文提到 description 不算改觸發面（錨定行首）。"""
        diff = diff_for(
            "skills/demo/SKILL.md",
            ["撰寫 description: 要放觸發關鍵字。", "  description: 縮排的不是 frontmatter"],
            old_path="skills/demo/SKILL.md",
        )
        assert check_skill_eval_coverage(diff, NEVER) == []


class TestNewSkill:
    def test_slec_dt_004_new_skill_without_fixture_warns(self) -> None:
        """SLEC-DT-004: 新增 skill 且無 fixture -> 回報（即使沒有 description 行）。"""
        diff = diff_for("skills/fresh/SKILL.md", ["---", "name: fresh", "---"])
        msgs = check_skill_eval_coverage(diff, NEVER)
        assert len(msgs) == 1
        assert "新增 skill" in msgs[0]

    def test_slec_eg_002_renamed_into_skills_counts_as_new(self) -> None:
        """SLEC-EG-002: 從 drafts/ rename 進 skills/ 也算新 skill。

        只看 `old_path == "/dev/null"` 會漏掉 rename——old_path 是真實路徑，於是被當成
        既有檔案而跳過新檔檢查（rule 02 記載的同一個陷阱）。
        """
        diff = diff_for("skills/moved/SKILL.md", ["name: moved"], old_path="drafts/moved/SKILL.md")
        msgs = check_skill_eval_coverage(diff, NEVER)
        assert len(msgs) == 1
        assert "新增 skill" in msgs[0]

    def test_slec_eg_003_rename_within_skills_is_not_new(self) -> None:
        """SLEC-EG-003: 在 skills/ 內部改名不算新增（既有 skill 換位置）。"""
        diff = diff_for(
            "skills/renamed/SKILL.md", ["unchanged body"], old_path="skills/old-name/SKILL.md"
        )
        assert check_skill_eval_coverage(diff, NEVER) == []


class TestPluginPaths:
    def test_slec_eg_004_nested_plugin_sub_skill_matched(self) -> None:
        """SLEC-EG-004: plugins/ 巢狀 sub-skill 的 SKILL.md 也在檢查範圍。

        釘住 `plugins/[^/]+/skills/.+/SKILL\\.md`：改回 `[^/]+` 會讓 mycelium 的 sub-skill
        整層靜默逃過檢查（rule 02「`*` 不跨 `/`」的同類陷阱）。
        """
        diff = diff_for(
            "plugins/growth/skills/mycelium/recap/SKILL.md",
            ["description: 改了觸發描述"],
            old_path="plugins/growth/skills/mycelium/recap/SKILL.md",
        )
        msgs = check_skill_eval_coverage(diff, NEVER)
        assert len(msgs) == 1
        assert "plugins/growth/skills/mycelium/recap/SKILL.md" in msgs[0]

    def test_slec_eg_005_non_skill_markdown_ignored(self) -> None:
        """SLEC-EG-005: 非 SKILL.md 的 markdown 不觸發（如 skills/README.md）。"""
        diff = diff_for("skills/README.md", ["description: 這不是 skill"])
        assert check_skill_eval_coverage(diff, NEVER) == []


class TestCliContract:
    def test_slec_vl_001_warn_only_exits_zero(self, tmp_path: Path) -> None:
        """SLEC-VL-001: 預設 warn-only——有未覆蓋項仍 exit 0（起步期不擋 commit）。"""
        f = tmp_path / "d.diff"
        f.write_text(diff_for("skills/fresh/SKILL.md", ["name: fresh"]), encoding="utf-8")
        assert main([str(f)]) == 0

    def test_slec_vl_002_fail_mode_exits_one(self, tmp_path: Path) -> None:
        """SLEC-VL-002: `--fail` 把同一份輸入升級為 exit 1（覆蓋率鋪開後翻 blocking 用）。"""
        f = tmp_path / "d.diff"
        f.write_text(diff_for("skills/fresh/SKILL.md", ["name: fresh"]), encoding="utf-8")
        assert main(["--fail", str(f)]) == 1

    @pytest.mark.parametrize(
        "argv",
        [
            ["--base", "abc"],  # 只給一半
            ["--base", "", "--head", "def"],  # 空字串會退化成 HEAD...HEAD 的空 diff
            ["--base", "a", "--head", "b", "some.diff"],  # range 與檔案模式互斥
            ["--unknown"],
        ],
    )
    def test_slec_vl_003_bad_args_exit_two(self, argv: list[str]) -> None:
        """SLEC-VL-003: 引數矛盾 -> exit 2，不得退化成「跑完、通過、什麼都沒檢查」。"""
        assert main(argv) == 2

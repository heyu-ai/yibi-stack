"""LINTOVERLAP-* tests for scripts/lint_skill_overlap.py。

驗證「skill description 觸發詞重疊偵測」lint 的核心判斷邏輯。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
"""

import sys
from pathlib import Path

import importlib.util

_MOD_PATH = Path(__file__).resolve().parent.parent / "lint_skill_overlap.py"
_spec = importlib.util.spec_from_file_location("lint_skill_overlap", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
lint_skill_overlap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_skill_overlap)


def make_skill(description: str, block: bool = False) -> str:
    """組一份最小 SKILL.md 文字；block=True 時用 `>` folded scalar 寫法。"""
    if block:
        indented = "\n".join(f"  {line}" for line in description.splitlines())
        return f"---\nname: demo\ntype: know\nscope: global\ndescription: >\n{indented}\n---\n\n# Demo\n"
    return f"---\nname: demo\ntype: know\nscope: global\ndescription: {description}\n---\n\n# Demo\n"


class TestParseDescription:
    def test_lintoverlap_vl_001_reads_single_line(self) -> None:
        """LINTOVERLAP-VL-001: 單行 description 直接讀出"""
        assert lint_skill_overlap.parse_description(make_skill("PR review 自動化")) == "PR review 自動化"

    def test_lintoverlap_vl_002_reads_folded_block(self) -> None:
        """LINTOVERLAP-VL-002: `>` folded block 拼回單行"""
        text = make_skill("第一行 review\n第二行 merge", block=True)
        assert lint_skill_overlap.parse_description(text) == "第一行 review 第二行 merge"

    def test_lintoverlap_vl_003_no_frontmatter_returns_none(self) -> None:
        """LINTOVERLAP-VL-003: 無 frontmatter 回傳 None"""
        assert lint_skill_overlap.parse_description("# 無 frontmatter") is None

    def test_lintoverlap_vl_004_missing_description_returns_none(self) -> None:
        """LINTOVERLAP-VL-004: frontmatter 無 description 欄位回傳 None"""
        text = "---\nname: demo\ntype: know\nscope: global\n---\n\n# Demo\n"
        assert lint_skill_overlap.parse_description(text) is None


class TestExtractKeywords:
    def test_lintoverlap_dt_001_ascii_words_lowercased(self) -> None:
        """LINTOVERLAP-DT-001: ASCII 詞抽出並小寫化"""
        kw = lint_skill_overlap.extract_keywords("Review the PR before CI merge")
        assert "review" in kw
        assert "pr" in kw
        assert "ci" in kw

    def test_lintoverlap_dt_002_cjk_bigrams_extracted(self) -> None:
        """LINTOVERLAP-DT-002: CJK 連續字元抽出 bigram shingle"""
        kw = lint_skill_overlap.extract_keywords("審查程式碼")
        assert "審查" in kw
        assert "查程" in kw
        assert "程式" in kw
        assert "式碼" in kw

    def test_lintoverlap_eg_001_stopword_bigram_filtered(self) -> None:
        """LINTOVERLAP-EG-001: 樣板虛詞 bigram（如「觸發」）被濾掉"""
        kw = lint_skill_overlap.extract_keywords("觸發情境：需要審查")
        assert "觸發" not in kw
        assert "情境" not in kw
        assert "需要" not in kw

    def test_lintoverlap_eg_002_empty_description_empty_set(self) -> None:
        """LINTOVERLAP-EG-002: 空字串回傳空 set"""
        assert lint_skill_overlap.extract_keywords("") == set()


class TestJaccard:
    def test_lintoverlap_dt_003_identical_sets_score_one(self) -> None:
        """LINTOVERLAP-DT-003: 完全相同的 set -> 1.0"""
        a = {"pr", "review", "ci"}
        assert lint_skill_overlap.jaccard(a, a) == 1.0

    def test_lintoverlap_dt_004_disjoint_sets_score_zero(self) -> None:
        """LINTOVERLAP-DT-004: 無交集 -> 0.0"""
        assert lint_skill_overlap.jaccard({"pr"}, {"ci"}) == 0.0

    def test_lintoverlap_eg_003_empty_set_score_zero(self) -> None:
        """LINTOVERLAP-EG-003: 任一邊為空 set -> 0.0（不除以零）"""
        assert lint_skill_overlap.jaccard(set(), {"pr"}) == 0.0
        assert lint_skill_overlap.jaccard(set(), set()) == 0.0

    def test_lintoverlap_dt_005_partial_overlap_matches_formula(self) -> None:
        """LINTOVERLAP-DT-005: 部分重疊符合交集/聯集公式"""
        a = {"pr", "review", "ci"}
        b = {"pr", "review", "merge"}
        assert lint_skill_overlap.jaccard(a, b) == 2 / 4


class TestFindOverlaps:
    def test_lintoverlap_st_001_above_threshold_flagged_sorted_desc(self) -> None:
        """LINTOVERLAP-ST-001: 超門檻的 pair 依 score 降冪排序"""
        skills = [
            ("a", {"pr", "review", "ci"}),
            ("b", {"pr", "review", "merge"}),
            ("c", {"pr", "review", "ci", "merge"}),
        ]
        risky = lint_skill_overlap.find_overlaps(skills, threshold=0.3)
        assert len(risky) == 3
        scores = [row[2] for row in risky]
        assert scores == sorted(scores, reverse=True)

    def test_lintoverlap_eg_004_below_threshold_not_flagged(self) -> None:
        """LINTOVERLAP-EG-004: 低於門檻的 pair 不列入"""
        skills = [("a", {"pr"}), ("b", {"ci"})]
        assert lint_skill_overlap.find_overlaps(skills, threshold=0.1) == []

    def test_lintoverlap_dt_006_shared_keywords_capped(self) -> None:
        """LINTOVERLAP-DT-006: 共享關鍵字列表不超過 MAX_SHARED_KEYWORDS_SHOWN"""
        big_shared = {f"kw{i}" for i in range(50)}
        skills = [("a", big_shared), ("b", big_shared)]
        risky = lint_skill_overlap.find_overlaps(skills, threshold=0.5)
        assert len(risky) == 1
        assert len(risky[0][3]) == lint_skill_overlap.MAX_SHARED_KEYWORDS_SHOWN


class TestMainEndToEnd:
    def _write_skill(self, root: Path, name: str, description: str) -> None:
        d = root / name
        d.mkdir()
        (d / "SKILL.md").write_text(make_skill(description), encoding="utf-8")

    def test_lintoverlap_st_002_warn_only_default_exits_0(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """LINTOVERLAP-ST-002: warn-only 預設模式，有重疊仍 exit 0"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "PR review automation with CI merge")
        self._write_skill(skills, "b", "PR review automation with CI merge gate")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)  # type: ignore[attr-defined]
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 0

    def test_lintoverlap_st_003_fail_flag_exits_1_on_violation(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """LINTOVERLAP-ST-003: --fail 旗標 + 有重疊 -> main() 回 1"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "PR review automation with CI merge")
        self._write_skill(skills, "b", "PR review automation with CI merge gate")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)  # type: ignore[attr-defined]
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--fail"])
        assert lint_skill_overlap.main() == 1

    def test_lintoverlap_st_004_no_overlap_exits_0(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """LINTOVERLAP-ST-004: 無重疊 -> main() 回 0（含 --fail）"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "掃描 Gmail 帳單附件")
        self._write_skill(skills, "b", "部署 Kubernetes 叢集")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)  # type: ignore[attr-defined]
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--fail"])
        assert lint_skill_overlap.main() == 0

    def test_lintoverlap_eg_005_missing_skills_dir_exits_2(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """LINTOVERLAP-EG-005: skills 目錄不存在 -> main() 回 2"""
        monkeypatch.setattr(
            lint_skill_overlap, "SKILLS_DIR", tmp_path / "does-not-exist"  # type: ignore[attr-defined]
        )
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 2

    def test_lintoverlap_eg_006_custom_threshold_applied(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """LINTOVERLAP-EG-006: --threshold 覆寫預設門檻"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "PR review")
        self._write_skill(skills, "b", "PR merge")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)  # type: ignore[attr-defined]
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--fail", "--threshold", "0.9"])
        assert lint_skill_overlap.main() == 0

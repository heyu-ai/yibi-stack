"""LINTOVERLAP-* tests for scripts/lint_skill_overlap.py。

驗證「skill description 觸發詞重疊偵測」lint 的核心判斷邏輯。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parent.parent / "lint_skill_overlap.py"
_spec = importlib.util.spec_from_file_location("lint_skill_overlap", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
lint_skill_overlap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_skill_overlap)


def make_skill(description: str, block: bool = False, block_indicator: str = ">") -> str:
    """組一份最小 SKILL.md 文字；block=True 時用 block scalar 寫法（block_indicator 指定表頭）。"""
    if block:
        indented = "\n".join(f"  {line}" for line in description.splitlines())
        return (
            f"---\nname: demo\ntype: know\nscope: global\n"
            f"description: {block_indicator}\n{indented}\n---\n\n# Demo\n"
        )
    return (
        f"---\nname: demo\ntype: know\nscope: global\ndescription: {description}\n---\n\n# Demo\n"
    )


class TestParseDescription:
    def test_lintoverlap_vl_001_reads_single_line(self) -> None:
        """LINTOVERLAP-VL-001: 單行 description 直接讀出"""
        assert (
            lint_skill_overlap.parse_description(make_skill("PR review 自動化"))
            == "PR review 自動化"
        )

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

    def test_lintoverlap_eg_005_unclosed_frontmatter_returns_none(self) -> None:
        """LINTOVERLAP-EG-005: frontmatter 缺結尾 --- 視為解析失敗，不 fallback 到整份文件"""
        text = (
            "---\nname: demo\ntype: know\nscope: global\ndescription: PR review\n\n"
            "# Demo\n\ndescription: 這是 body 裡的文字，不應被當成 frontmatter 值\n"
        )
        assert lint_skill_overlap.parse_description(text) is None

    def test_lintoverlap_eg_006_empty_description_returns_none(self) -> None:
        """LINTOVERLAP-EG-006: description: 後面沒有值 -> 回傳 None（視同缺欄位）"""
        text = "---\nname: demo\ntype: know\nscope: global\ndescription:\n---\n\n# Demo\n"
        assert lint_skill_overlap.parse_description(text) is None

    def test_lintoverlap_eg_007_empty_block_scalar_returns_none(self) -> None:
        """LINTOVERLAP-EG-007: block scalar 表頭後沒有任何縮排內容 -> 回傳 None"""
        text = "---\nname: demo\ntype: know\nscope: global\ndescription: >\n---\n\n# Demo\n"
        assert lint_skill_overlap.parse_description(text) is None

    @pytest.mark.parametrize("indicator", [">", "|", ">-", "|-", ">+", "|+", ">2", "|2-", ">-2"])
    def test_lintoverlap_eg_008_block_scalar_indentation_indicators(self, indicator: str) -> None:
        """LINTOVERLAP-EG-008: YAML 縮排指示符（如 |2、>1-）也能正確解析 block scalar"""
        text = make_skill("PR review", block=True, block_indicator=indicator)
        assert lint_skill_overlap.parse_description(text) == "PR review"

    def test_lintoverlap_eg_022_plain_scalar_multiline_folds_continuation(self) -> None:
        """LINTOVERLAP-EG-022: 無引號 plain scalar 的後續縮排行會摺進同一個值（YAML 語意），
        不會被靜默截斷成只剩第一行。
        """
        text = (
            "---\nname: demo\ntype: know\nscope: global\n"
            "description: this is a\n  continued second line\n---\n\n# Demo\n"
        )
        assert lint_skill_overlap.parse_description(text) == "this is a continued second line"

    def test_lintoverlap_eg_023_plain_scalar_stops_at_next_key(self) -> None:
        """LINTOVERLAP-EG-023: plain scalar 延續行遇到未縮排的下一個 key 就停止收集"""
        text = "---\nname: demo\ndescription: foo\ntype: know\nscope: global\n---\n\n# Demo\n"
        assert lint_skill_overlap.parse_description(text) == "foo"


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

    def test_lintoverlap_eg_009_yonger_bigram_filtered_not_dead_entry(self) -> None:
        """LINTOVERLAP-EG-009: 「使用者」產生的 bigram 是「使用」「用者」，兩者都應被濾掉

        （回歸測試：先前 stopword 清單誤植「使者」——bigram 滑動視窗永遠不會產生這個
        字串，是死條目；真正該濾的是「用者」。）
        """
        kw = lint_skill_overlap.extract_keywords("本 skill 給使用者操作")
        assert "使用" not in kw
        assert "用者" not in kw
        assert "使者" not in kw  # 死條目本來就不該出現，順便鎖住

    def test_lintoverlap_eg_024_punctuation_crossing_bigrams_impossible(self) -> None:
        """LINTOVERLAP-EG-024: CJK run 在全形標點處斷開，跨標點的 bigram 永遠不會產生

        （回歸測試：先前 stopword 清單含「說「」「」時」兩個死條目——CJK_RUN_RE 只吃
        CJK Unified Ideographs，全形括號會截斷連續字元，這兩個 bigram 不可能被產生。）
        """
        kw = lint_skill_overlap.extract_keywords("當用戶說「幫我寫」時應觸發")
        assert "說「" not in kw
        assert "」時" not in kw
        assert "戶說" in kw  # 標點前的正常 bigram 仍應存在
        assert "時應" in kw  # 標點後的正常 bigram 仍應存在


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

    def test_lintoverlap_dt_007_shared_keywords_keep_longest_lexical_first(self) -> None:
        """LINTOVERLAP-DT-007: 共享關鍵字截斷後保留 (-len, lexical) 排序的前段，非任意子集"""
        shared = {"aa", "bb", "aaa", "bbb", "c"}
        skills = [("a", shared), ("b", shared)]
        risky = lint_skill_overlap.find_overlaps(skills, threshold=0.5)
        assert risky[0][3] == sorted(shared, key=lambda k: (-len(k), k))

    def test_lintoverlap_eg_010_score_exactly_at_threshold_is_flagged(self) -> None:
        """LINTOVERLAP-EG-010: score 剛好等於門檻（>= 語意）也要列入"""
        skills = [("a", {"pr", "review"}), ("b", {"pr", "ci"})]
        # jaccard = 1/3
        risky = lint_skill_overlap.find_overlaps(skills, threshold=1 / 3)
        assert len(risky) == 1


class TestIterGlobalSkillFiles:
    def test_lintoverlap_st_005_finds_real_directory_with_skill_md(self, tmp_path: Path) -> None:
        """LINTOVERLAP-ST-005: 一般目錄含 SKILL.md 會被列出"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "foo").mkdir()
        (skills / "foo" / "SKILL.md").write_text("x", encoding="utf-8")
        found = lint_skill_overlap.iter_global_skill_files(skills, tmp_path / "no-plugins")
        assert found == [("foo", skills / "foo" / "SKILL.md")]

    def test_lintoverlap_eg_011_non_directory_entry_skipped(self, tmp_path: Path) -> None:
        """LINTOVERLAP-EG-011: 非目錄的檔案（如 README.md）被靜默排除"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "README.md").write_text("x", encoding="utf-8")
        assert lint_skill_overlap.iter_global_skill_files(skills, tmp_path / "no-plugins") == []

    def test_lintoverlap_eg_012_directory_missing_skill_md_skipped(self, tmp_path: Path) -> None:
        """LINTOVERLAP-EG-012: 目錄存在但缺 SKILL.md 被排除"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "empty-dir").mkdir()
        assert lint_skill_overlap.iter_global_skill_files(skills, tmp_path / "no-plugins") == []

    def test_lintoverlap_st_006_follows_symlink_to_real_skill_dir(self, tmp_path: Path) -> None:
        """LINTOVERLAP-ST-006: symlink 指向真實 skill 目錄時會被跟隨並列出"""
        skills = tmp_path / "skills"
        skills.mkdir()
        real = tmp_path / "plugins" / "pack" / "skills" / "bar"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_text("x", encoding="utf-8")
        (skills / "bar").symlink_to(real, target_is_directory=True)
        found = lint_skill_overlap.iter_global_skill_files(skills, tmp_path / "no-plugins")
        assert found == [("bar", skills / "bar" / "SKILL.md")]

    def test_lintoverlap_eg_013_broken_symlink_warns_and_excluded(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LINTOVERLAP-EG-013: 失效 symlink（目標不存在）印出 [WARN] 並排除，不崩潰"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "dangling").symlink_to(tmp_path / "does-not-exist", target_is_directory=True)
        found = lint_skill_overlap.iter_global_skill_files(skills, tmp_path / "no-plugins")
        assert found == []
        assert "[WARN]" in capsys.readouterr().err

    def test_lintoverlap_st_007_sorted_by_name(self, tmp_path: Path) -> None:
        """LINTOVERLAP-ST-007: skills/ 底下的結果依名稱排序"""
        skills = tmp_path / "skills"
        skills.mkdir()
        for name in ["zeta", "alpha", "mid"]:
            (skills / name).mkdir()
            (skills / name / "SKILL.md").write_text("x", encoding="utf-8")
        found = lint_skill_overlap.iter_global_skill_files(skills, tmp_path / "no-plugins")
        assert [name for name, _ in found] == ["alpha", "mid", "zeta"]

    def test_lintoverlap_st_008_plugin_only_skill_included(self, tmp_path: Path) -> None:
        """LINTOVERLAP-ST-008: plugins/*/skills/*/SKILL.md 沒有對應 skills/ symlink 時也會被掃到"""
        skills = tmp_path / "skills"
        skills.mkdir()
        plugins = tmp_path / "plugins"
        plugin_skill = plugins / "pack" / "skills" / "plugin-only"
        plugin_skill.mkdir(parents=True)
        (plugin_skill / "SKILL.md").write_text("x", encoding="utf-8")
        found = lint_skill_overlap.iter_global_skill_files(skills, plugins)
        assert found == [("plugin-only", plugin_skill / "SKILL.md")]

    def test_lintoverlap_eg_025_symlinked_plugin_skill_not_double_counted(
        self, tmp_path: Path
    ) -> None:
        """LINTOVERLAP-EG-025: 同一份實體檔案透過 skills/ symlink 與 plugins/ 真實路徑
        都命中時，只計一次（依 realpath 去重）。
        """
        skills = tmp_path / "skills"
        skills.mkdir()
        plugins = tmp_path / "plugins"
        real = plugins / "pack" / "skills" / "bar"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_text("x", encoding="utf-8")
        (skills / "bar").symlink_to(real, target_is_directory=True)
        found = lint_skill_overlap.iter_global_skill_files(skills, plugins)
        assert len(found) == 1
        assert found[0][0] == "bar"

    def test_lintoverlap_eg_028_nested_plugin_sub_skill_included(self, tmp_path: Path) -> None:
        """LINTOVERLAP-EG-028: plugins/<plugin>/skills/<name>/<sub>/SKILL.md（巢狀 sub-skill，
        如 plugins/growth/skills/mycelium/recap/SKILL.md）也會被掃到，不會被單層 glob 漏掉。
        """
        skills = tmp_path / "skills"
        skills.mkdir()
        plugins = tmp_path / "plugins"
        nested = plugins / "pack" / "skills" / "parent" / "sub"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text("x", encoding="utf-8")
        found = lint_skill_overlap.iter_global_skill_files(skills, plugins)
        assert found == [("sub", nested / "SKILL.md")]

    def test_lintoverlap_eg_026_missing_plugins_dir_no_crash(self, tmp_path: Path) -> None:
        """LINTOVERLAP-EG-026: plugins 目錄不存在時，只回傳 skills/ 的結果，不崩潰"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "foo").mkdir()
        (skills / "foo" / "SKILL.md").write_text("x", encoding="utf-8")
        found = lint_skill_overlap.iter_global_skill_files(skills, tmp_path / "does-not-exist")
        assert found == [("foo", skills / "foo" / "SKILL.md")]


class TestMainEndToEnd:
    @pytest.fixture(autouse=True)
    def _no_real_plugins_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """預設不給 PLUGINS_DIR，避免測試意外掃到本機真實 repo 的 plugins/。"""
        monkeypatch.setattr(lint_skill_overlap, "PLUGINS_DIR", tmp_path / "no-plugins")

    def _write_skill(self, root: Path, name: str, description: str) -> None:
        d = root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(make_skill(description), encoding="utf-8")

    def test_lintoverlap_st_002_warn_only_default_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LINTOVERLAP-ST-002: warn-only 預設模式，有重疊仍 exit 0"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "PR review automation with CI merge")
        self._write_skill(skills, "b", "PR review automation with CI merge gate")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 0

    def test_lintoverlap_st_003_fail_flag_exits_1_on_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LINTOVERLAP-ST-003: --fail 旗標 + 有重疊 -> main() 回 1"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "PR review automation with CI merge")
        self._write_skill(skills, "b", "PR review automation with CI merge gate")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--fail"])
        assert lint_skill_overlap.main() == 1

    def test_lintoverlap_st_004_no_overlap_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LINTOVERLAP-ST-004: 無重疊 -> main() 回 0（含 --fail）"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "掃描 Gmail 帳單附件")
        self._write_skill(skills, "b", "部署 Kubernetes 叢集")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--fail"])
        assert lint_skill_overlap.main() == 0

    def test_lintoverlap_eg_014_missing_skills_dir_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LINTOVERLAP-EG-014: skills 目錄不存在 -> main() 回 2"""
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", tmp_path / "does-not-exist")
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 2

    def test_lintoverlap_eg_015_custom_threshold_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LINTOVERLAP-EG-015: --threshold 覆寫預設門檻"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "a", "PR review")
        self._write_skill(skills, "b", "PR merge")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--fail", "--threshold", "0.9"])
        assert lint_skill_overlap.main() == 0

    def test_lintoverlap_eg_016_threshold_missing_value_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LINTOVERLAP-EG-016: --threshold 為最後一個參數（漏帶值）-> [FAIL] exit 2"""
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--threshold"])
        assert lint_skill_overlap.main() == 2

    def test_lintoverlap_eg_017_threshold_non_numeric_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LINTOVERLAP-EG-017: --threshold 值非數字 -> [FAIL] exit 2（不崩潰噴 traceback）"""
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--threshold", "abc"])
        assert lint_skill_overlap.main() == 2

    @pytest.mark.parametrize("bad_value", ["-0.1", "1.5"])
    def test_lintoverlap_eg_018_threshold_out_of_range_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_value: str
    ) -> None:
        """LINTOVERLAP-EG-018: --threshold 超出 [0,1] 範圍 -> [FAIL] exit 2"""
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py", "--threshold", bad_value])
        assert lint_skill_overlap.main() == 2

    def test_lintoverlap_eg_019_empty_description_skill_excluded_no_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LINTOVERLAP-EG-019: description 為空的 skill 視同缺欄位，印警告、不計入 checked"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "empty").mkdir()
        (skills / "empty" / "SKILL.md").write_text(
            "---\nname: empty\ntype: know\nscope: global\ndescription:\n---\n\n# Demo\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 0
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err
        assert "已檢查 0 個 skill" in captured.out

    def test_lintoverlap_eg_020_non_utf8_file_warns_no_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LINTOVERLAP-EG-020: 非 UTF-8 SKILL.md 印 [WARN]，main() 正常結束不拋例外"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "bad-encoding").mkdir()
        (skills / "bad-encoding" / "SKILL.md").write_bytes(b"\xff\xfe\x00\x01invalid")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 0
        assert "[WARN]" in capsys.readouterr().err

    def test_lintoverlap_eg_021_broken_symlink_skill_no_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LINTOVERLAP-EG-021: skills/ 下有失效 symlink -> main() 印警告，正常結束"""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "dangling").symlink_to(tmp_path / "does-not-exist", target_is_directory=True)
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 0
        assert "[WARN]" in capsys.readouterr().err

    def test_lintoverlap_eg_027_plugin_only_skill_scanned_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """LINTOVERLAP-EG-027: plugin-only skill（無 skills/ symlink）也會被 main() 實際掃到，
        而不只是觸發 pre-commit hook 卻沒被檢查（見 PR #190 mob review 的 hook-scope
        vs scan-scope 落差發現）。
        """
        skills = tmp_path / "skills"
        skills.mkdir()
        plugins = tmp_path / "plugins"
        self._write_skill(plugins / "pack" / "skills", "plugin-only", "掃描 Gmail 帳單附件")
        self._write_skill(skills, "sibling", "部署 Kubernetes 叢集")
        monkeypatch.setattr(lint_skill_overlap, "SKILLS_DIR", skills)
        monkeypatch.setattr(lint_skill_overlap, "PLUGINS_DIR", plugins)
        monkeypatch.setattr(sys, "argv", ["lint_skill_overlap.py"])
        assert lint_skill_overlap.main() == 0
        captured = capsys.readouterr()
        assert "已檢查 2 個 skill" in captured.out

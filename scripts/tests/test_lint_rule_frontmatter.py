"""LINTRULE-* tests for scripts/lint_rule_frontmatter.py。

驗證 rule frontmatter 的 silent-failure key、結構與 paths 值檢查。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
"""

import importlib.util
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parent.parent / "lint_rule_frontmatter.py"
_spec = importlib.util.spec_from_file_location("lint_rule_frontmatter", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
lint_rule_frontmatter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_rule_frontmatter)


class TestLintFrontmatter:
    def test_lintrule_vl_001_no_frontmatter_is_valid(self) -> None:
        """LINTRULE-VL-001: 無 frontmatter 不違規"""
        assert lint_rule_frontmatter.lint_frontmatter("# Rule\n") == []

    def test_lintrule_vl_002_paths_list_is_valid(self) -> None:
        """LINTRULE-VL-002: paths list 合法"""
        text = '---\npaths:\n  - "tasks/**"\n---\n# Rule\n'
        assert lint_rule_frontmatter.lint_frontmatter(text) == []

    def test_lintrule_vl_003_paths_scalar_is_valid(self) -> None:
        """LINTRULE-VL-003: paths 純量合法"""
        text = "---\npaths: tasks/**\n---\n# Rule\n"
        assert lint_rule_frontmatter.lint_frontmatter(text) == []

    def test_lintrule_vl_004_unindented_paths_list_is_valid(self) -> None:
        """LINTRULE-VL-004: YAML 允許的未縮排 paths list 合法"""
        text = '---\npaths:\n- "tasks/**"\n---\n# Rule\n'
        assert lint_rule_frontmatter.lint_frontmatter(text) == []

    def test_lintrule_dt_001_bad_aliases_are_rejected(self) -> None:
        """LINTRULE-DT-001: 已知錯誤別名與 Paths 大小寫變體皆違規"""
        for key in ("globs", "glob", "path", "pattern", "Paths", "PATHS"):
            violations = lint_rule_frontmatter.lint_frontmatter(f"---\n{key}: tasks/**\n---\n")
            assert len(violations) == 1, key

    def test_lintrule_dt_002_unknown_key_is_allowed(self) -> None:
        """LINTRULE-DT-002: deny-list 不拒絕未知 top-level key"""
        assert lint_rule_frontmatter.lint_frontmatter("---\ndescription: demo\n---\n") == []

    def test_lintrule_dt_003_empty_paths_are_rejected(self) -> None:
        """LINTRULE-DT-003: 空白、空 list 與空 list item 皆違規"""
        for value in (
            "",
            " []",
            " [ ]",
            " '  '",
            ' "  "',
            ' ""',
            " # comment",
            " [] # comment",
            "\n  -",
        ):
            violations = lint_rule_frontmatter.lint_frontmatter(f"---\npaths:{value}\n---\n")
            assert any("不可為空" in reason for _, reason in violations), value

    def test_lintrule_dt_004_bom_bad_alias_is_rejected(self) -> None:
        """LINTRULE-DT-004: UTF-8 BOM 不得遮蔽錯誤路徑 key"""
        violations = lint_rule_frontmatter.lint_frontmatter("\ufeff---\nglobs: tasks/**\n---\n")
        assert any("`globs:`" in reason for _, reason in violations)

    def test_lintrule_dt_005_indented_fence_does_not_truncate_scan(self) -> None:
        """LINTRULE-DT-005: 縮排的 --- 不視為 frontmatter 結束分隔線"""
        text = "---\npaths: tasks/**\n  ---\nglobs: tasks/**\n---\n"
        violations = lint_rule_frontmatter.lint_frontmatter(text)
        assert any("`globs:`" in reason for _, reason in violations)

    def test_lintrule_eg_001_malformed_blocks_are_rejected(self) -> None:
        """LINTRULE-EG-001: 未關閉與非 mapping frontmatter 皆違規"""
        assert lint_rule_frontmatter.lint_frontmatter("---\npaths: tasks/**\n")
        assert lint_rule_frontmatter.lint_frontmatter("---\npaths = tasks/**\n---\n")


class TestMainEndToEnd:
    def test_lintrule_st_001_violation_exits_1(self, tmp_path: Path, monkeypatch: object) -> None:
        """LINTRULE-ST-001: 壞 key 使 main() 回 1"""
        rules = tmp_path / "rules"
        rules.mkdir()
        (rules / "bad.md").write_text("---\nglobs: tasks/**\n---\n", encoding="utf-8")
        monkeypatch.setattr(lint_rule_frontmatter, "RULES_DIR", rules)  # type: ignore[attr-defined]
        assert lint_rule_frontmatter.main() == 1

    def test_lintrule_st_002_missing_rules_dir_exits_2(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """LINTRULE-ST-002: rules 目錄缺失使 main() 回 2"""
        monkeypatch.setattr(lint_rule_frontmatter, "RULES_DIR", tmp_path / "missing")  # type: ignore[attr-defined]
        assert lint_rule_frontmatter.main() == 2

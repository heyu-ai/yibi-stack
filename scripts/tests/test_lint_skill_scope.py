"""LINTSCOPE-* tests for scripts/lint_skill_scope.py。

驗證「scope: global skill 不得 dispatch 本 repo plugin agent」lint 的核心判斷邏輯。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
"""

import importlib.util
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parent.parent / "lint_skill_scope.py"
_spec = importlib.util.spec_from_file_location("lint_skill_scope", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
lint_skill_scope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_skill_scope)

OWN = {"sdd", "pr-flow", "bash-hygiene"}


def make_skill(scope: str, body: str = "") -> str:
    """組一份最小 SKILL.md 文字。"""
    return f"---\nname: demo\ntype: know\nscope: {scope}\n---\n\n# Demo\n{body}\n"


class TestParseScope:
    def test_lintscope_vl_001_reads_global(self) -> None:
        """LINTSCOPE-VL-001: parse_scope 讀出 global"""
        assert lint_skill_scope.parse_scope(make_skill("global")) == "global"

    def test_lintscope_vl_002_reads_project(self) -> None:
        """LINTSCOPE-VL-002: parse_scope 讀出 project"""
        assert lint_skill_scope.parse_scope(make_skill("project")) == "project"

    def test_lintscope_vl_003_no_frontmatter_returns_none(self) -> None:
        """LINTSCOPE-VL-003: 無 frontmatter 回傳 None"""
        assert lint_skill_scope.parse_scope("# 無 frontmatter") is None


class TestFindOwnDispatches:
    def test_lintscope_dt_001_own_plugin_dispatch_flagged(self) -> None:
        """LINTSCOPE-DT-001: 本 repo plugin agent（subagent_type: 形式）→ 命中違規"""
        text = make_skill("global", "subagent_type: sdd:gherkin-scenario-writer")
        hits = lint_skill_scope.find_own_dispatches(text, OWN)
        assert len(hits) == 1
        assert hits[0][0] == "sdd"
        assert hits[0][1] == "gherkin-scenario-writer"

    def test_lintscope_dt_002_external_plugin_dispatch_ok(self) -> None:
        """LINTSCOPE-DT-002: 外部 plugin agent → 放行（不命中）"""
        text = make_skill(
            "global",
            "Agent(subagent_type=pr-review-toolkit:code-reviewer, prompt=...)",
        )
        assert lint_skill_scope.find_own_dispatches(text, OWN) == []

    def test_lintscope_dt_003_equals_form_flagged(self) -> None:
        """LINTSCOPE-DT-003: subagent_type= 形式的本 repo plugin agent 也命中"""
        text = make_skill("global", "subagent_type=sdd:qa-test-designer")
        hits = lint_skill_scope.find_own_dispatches(text, OWN)
        assert len(hits) == 1
        assert hits[0][0] == "sdd"

    def test_lintscope_eg_001_prose_mention_not_dispatch(self) -> None:
        """LINTSCOPE-EG-001: 純文件提及（無 subagent_type token）→ 不命中"""
        text = make_skill(
            "global", "use the `sdd:qa-test-designer` agent for programmatic invocation"
        )
        assert lint_skill_scope.find_own_dispatches(text, OWN) == []


class TestLoadOwnPlugins:
    def test_lintscope_st_001_loads_repo_marketplace(self) -> None:
        """LINTSCOPE-ST-001: 從本 repo marketplace.json 讀出自有 plugin 名單"""
        names = lint_skill_scope.load_own_plugins(lint_skill_scope.MARKETPLACE)
        assert "sdd" in names
        assert "pr-flow" in names


class TestMainEndToEnd:
    def _write_skill(self, root: Path, name: str, scope: str, body: str) -> None:
        d = root / name
        d.mkdir()
        (d / "SKILL.md").write_text(make_skill(scope, body), encoding="utf-8")

    def test_lintscope_st_002_violation_exits_1(self, tmp_path: Path, monkeypatch: object) -> None:
        """LINTSCOPE-ST-002: global skill dispatch 本 repo plugin agent → main() 回 1"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "bad", "global", "subagent_type: sdd:qa-test-designer")
        monkeypatch.setattr(lint_skill_scope, "SKILLS_DIR", skills)  # type: ignore[attr-defined]
        assert lint_skill_scope.main() == 1

    def test_lintscope_st_003_external_and_project_exit_0(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """LINTSCOPE-ST-003: 外部 dispatch 的 global + project scope skill → main() 回 0"""
        skills = tmp_path / "skills"
        skills.mkdir()
        self._write_skill(skills, "ext", "global", "subagent_type=pr-review-toolkit:code-reviewer")
        self._write_skill(skills, "proj", "project", "subagent_type: sdd:qa-test-designer")
        monkeypatch.setattr(lint_skill_scope, "SKILLS_DIR", skills)  # type: ignore[attr-defined]
        assert lint_skill_scope.main() == 0

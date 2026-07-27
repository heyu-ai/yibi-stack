"""Tests for `select_rules.py`, the rule picker behind `/codex-cli` Step 2.

The負向控制 is the point here. A picker that returns *every* rule would satisfy any
"the expected rule appears" assertion, so each matching test has a paired assertion that a
deliberately non-matching rule stays out. Same for `parse_paths`: "no `paths:` key" (always
loaded) and "`paths:` present but nothing matches" are different answers and must not collapse.

Test IDs: SR-GL-* glob translation, SR-FM-* frontmatter parsing, SR-SEL-* selection,
SR-CLI-* command-line behavior.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "select_rules.py"
_spec = importlib.util.spec_from_file_location("select_rules", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
select_rules = importlib.util.module_from_spec(_spec)
sys.modules["select_rules"] = select_rules
_spec.loader.exec_module(select_rules)


def matches(pattern: str, path: str) -> bool:
    return select_rules.glob_to_regex(pattern).match(path) is not None


# --- SR-GL: glob translation ------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("tasks/**", "tasks/mycelium/db.py"),
        ("tasks/**", "tasks/foo.py"),
        # `**/` must match zero directories: rule 05 (`tasks/**/models.py`) has to fire on a
        # models.py sitting directly under tasks/.
        ("tasks/**/models.py", "tasks/models.py"),
        ("tasks/**/models.py", "tasks/mycelium/models.py"),
        ("tasks/**/tests/**", "tasks/mycelium/tests/test_db.py"),
        # Non-anchored: CLAUDE.md states rule 11's `skills/**` also matches plugin skills.
        ("skills/**", "plugins/growth/skills/mycelium/SKILL.md"),
    ],
)
def test_sr_gl_001_patterns_match(pattern: str, path: str) -> None:
    assert matches(pattern, path)


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("tasks/**", "scripts/lint_skill_bash.py"),
        ("tasks/**/tests/**", "tasks/mycelium/db.py"),
        ("tasks/**/models.py", "tasks/mycelium/config.py"),
        # A single `*` must not cross a path separator.
        ("tasks/*.py", "tasks/mycelium/db.py"),
    ],
)
def test_sr_gl_002_patterns_do_not_match(pattern: str, path: str) -> None:
    assert not matches(pattern, path)


def test_sr_gl_003_regex_metacharacters_are_literal() -> None:
    """A `.` in the pattern must not act as regex "any character"."""
    assert matches("tasks/**/models.py", "tasks/a/models.py")
    assert not matches("tasks/**/models.py", "tasks/a/modelsXpy")


# --- SR-FM: frontmatter parsing ---------------------------------------------


def test_sr_fm_001_no_frontmatter_means_always_loaded() -> None:
    assert select_rules.parse_paths("# Title\n\nbody\n") is None


def test_sr_fm_002_frontmatter_without_paths_key_means_always_loaded() -> None:
    assert select_rules.parse_paths("---\neffort: high\n---\n# Title\n") is None


def test_sr_fm_003_list_form() -> None:
    text = '---\npaths:\n  - "tasks/**"\n  - "scripts/**"\n---\n# Title\n'
    assert select_rules.parse_paths(text) == ["tasks/**", "scripts/**"]


def test_sr_fm_004_scalar_form() -> None:
    assert select_rules.parse_paths("---\npaths: tasks/**\n---\n# Title\n") == ["tasks/**"]


def test_sr_fm_005_unterminated_frontmatter_is_not_treated_as_paths() -> None:
    assert select_rules.parse_paths('---\npaths:\n  - "tasks/**"\n# Title\n') is None


def test_sr_fm_006_title_falls_back_when_no_heading() -> None:
    assert select_rules.title_of("no heading here\n", "04-module-structure") == (
        "04-module-structure"
    )


# --- SR-SEL: selection ------------------------------------------------------


@pytest.fixture()
def rules_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".claude" / "rules"
    directory.mkdir(parents=True)
    (directory / "01-always.md").write_text("# Always Loaded\n", encoding="utf-8")
    (directory / "04-tasks.md").write_text(
        '---\npaths:\n  - "tasks/**"\n---\n# Task Module Structure\n', encoding="utf-8"
    )
    (directory / "11-skills.md").write_text(
        '---\npaths:\n  - "skills/**"\n---\n# SKILL.md Authoring Guide\n', encoding="utf-8"
    )
    return directory


def test_sr_sel_001_always_loaded_rule_is_included_with_no_paths_given(rules_dir: Path) -> None:
    lines = select_rules.select(rules_dir, [])
    assert any("01-always.md" in line for line in lines)
    # 負向控制：沒給路徑時，path-scoped rule 不得被選入——否則「有列到」這件事毫無資訊量。
    assert not any("04-tasks.md" in line for line in lines)
    assert not any("11-skills.md" in line for line in lines)


def test_sr_sel_002_only_the_matching_scoped_rule_is_added(rules_dir: Path) -> None:
    lines = select_rules.select(rules_dir, ["tasks/mycelium/db.py"])
    assert any("04-tasks.md" in line for line in lines)
    assert not any("11-skills.md" in line for line in lines)


def test_sr_sel_003_output_names_the_pattern_that_matched(rules_dir: Path) -> None:
    line = next(
        line for line in select_rules.select(rules_dir, ["tasks/a.py"]) if "04-tasks.md" in line
    )
    assert "tasks/**" in line
    assert "Task Module Structure" in line


# --- SR-CLI: command-line behavior ------------------------------------------


def test_sr_cli_001_missing_repo_root_exits_2(tmp_path: Path) -> None:
    assert select_rules.main(["--repo-root", str(tmp_path / "nope")]) == 2


def test_sr_cli_002_repo_without_rules_dir_warns_but_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert select_rules.main(["--repo-root", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "[WARN]" in captured.err
    assert captured.out == ""


def test_sr_cli_003_prints_selected_rules(
    rules_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = rules_dir.parent.parent
    assert select_rules.main(["--repo-root", str(repo_root), "tasks/a.py"]) == 0
    captured = capsys.readouterr()
    assert "04-tasks.md" in captured.out
    assert "11-skills.md" not in captured.out


def test_sr_cli_004_leading_dot_slash_is_normalized(
    rules_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = rules_dir.parent.parent
    assert select_rules.main(["--repo-root", str(repo_root), "./tasks/a.py"]) == 0
    assert "04-tasks.md" in capsys.readouterr().out

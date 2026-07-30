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


def test_sr_fm_007_flow_sequence_form() -> None:
    """`paths: ["tasks/**"]` 是合法 YAML，且是單一 pattern 最常見的寫法。

    不特別處理的話它會落進 scalar 分支，變成一個帶中括號與引號的 literal pattern，
    匹配不到任何真實路徑，然後靜默漏掉該 rule。
    """
    assert select_rules.parse_paths('---\npaths: ["tasks/**"]\n---\n# T\n') == ["tasks/**"]
    assert select_rules.parse_paths("---\npaths: [tasks/**, scripts/**]\n---\n# T\n") == [
        "tasks/**",
        "scripts/**",
    ]
    assert select_rules.parse_paths("---\npaths: []\n---\n# T\n") == []


def test_sr_fm_005_unterminated_frontmatter_is_not_treated_as_paths() -> None:
    assert select_rules.parse_paths('---\npaths:\n  - "tasks/**"\n# Title\n') is None


def test_sr_fm_006_title_falls_back_when_no_heading() -> None:
    assert select_rules.title_of("no heading here\n", "04-module-structure") == (
        "04-module-structure"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 有起始 `---` 但缺結束 `---` —— 唯一該回 True 的形狀。
        ('---\npaths:\n  - "tasks/**"\n# Title\n', True),
        # 負向控制。這三種都會讓 parse_paths 回 None，但它們是**正常的**全量載入，
        # 不得誤報成 frontmatter 壞掉——否則每個 always-loaded rule 都會噴 [WARN]。
        ('---\npaths:\n  - "tasks/**"\n---\n# Title\n', False),
        ("# no frontmatter at all\n", False),
        ("", False),
    ],
)
def test_sr_fm_008_frontmatter_is_malformed(text: str, expected: bool) -> None:
    assert select_rules.frontmatter_is_malformed(text) is expected


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
    # dot-prefixed scope：`str.lstrip("./")` 會把 `.claude/hooks/x.py` 削成
    # `claude/hooks/x.py`，這條 rule 就永遠不匹配。
    (directory / "41-hooks.md").write_text(
        '---\npaths:\n  - ".claude/hooks/**"\n---\n# Hook Conventions\n', encoding="utf-8"
    )
    return directory


def test_sr_sel_001_always_loaded_rule_is_included_with_no_paths_given(rules_dir: Path) -> None:
    lines, scoped_hits = select_rules.select(rules_dir, [])
    assert any("01-always.md" in line for line in lines)
    # 負向控制：沒給路徑時，path-scoped rule 不得被選入——否則「有列到」這件事毫無資訊量。
    assert not any("04-tasks.md" in line for line in lines)
    assert not any("11-skills.md" in line for line in lines)
    assert scoped_hits == 0


def test_sr_sel_002_only_the_matching_scoped_rule_is_added(rules_dir: Path) -> None:
    lines, scoped_hits = select_rules.select(rules_dir, ["tasks/mycelium/db.py"])
    assert any("04-tasks.md" in line for line in lines)
    assert not any("11-skills.md" in line for line in lines)
    assert scoped_hits == 1


def test_sr_sel_003_output_names_the_pattern_that_matched(rules_dir: Path) -> None:
    lines, _ = select_rules.select(rules_dir, ["tasks/a.py"])
    line = next(line for line in lines if "04-tasks.md" in line)
    assert "tasks/**" in line
    assert "Task Module Structure" in line


def test_sr_sel_004_dot_prefixed_path_selects_its_scoped_rule(rules_dir: Path) -> None:
    """`.claude/hooks/x.py` 必須命中 `.claude/hooks/**`。

    這是 `lstrip` 版本會失敗的案例：路徑被削掉開頭的 `.` 後 pattern 不再匹配，
    rule 靜默消失。
    """
    lines, scoped_hits = select_rules.select(rules_dir, [".claude/hooks/x.py"])
    assert any("41-hooks.md" in line for line in lines)
    assert scoped_hits == 1


def test_sr_sel_005_unparseable_paths_key_warns_and_is_skipped(
    rules_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (rules_dir / "99-broken.md").write_text("---\npaths:\n---\n# Broken Scope\n", encoding="utf-8")
    lines, _ = select_rules.select(rules_dir, ["tasks/a.py"])
    assert not any("99-broken.md" in line for line in lines)
    assert "99-broken.md" in capsys.readouterr().err


def test_sr_sel_006_malformed_frontmatter_warns_but_still_counts_as_always_loaded(
    rules_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """缺結束 `---` 的 rule：仍以全量載入計（fail-safe），但必須發 `[WARN]`。

    這條路徑修正前是**靜默**的——與 SR-SEL-005（有 `paths:` key 卻解析不出 pattern）
    同樣是「frontmatter 壞掉」，診斷待遇卻不同。SKILL.md Step 2 的 exit-code 表把它
    列為一個具名結果，所以行為必須真的存在。
    """
    (rules_dir / "98-truncated.md").write_text(
        '---\npaths:\n  - "tasks/**"\n# Truncated Scope\n', encoding="utf-8"
    )
    lines, _ = select_rules.select(rules_dir, ["scripts/x.py"])
    # fail-safe 方向：多載入而非漏載入。
    assert any("98-truncated.md" in line for line in lines)
    assert "98-truncated.md" in capsys.readouterr().err


def test_sr_sel_007_well_formed_always_loaded_rule_does_not_warn(
    rules_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """負向控制：沒有 frontmatter 的 rule 是**正常**的全量載入，不得誤報 `[WARN]`。

    少了這條，SR-SEL-006 就沒有資訊量——一個對每個 always-loaded rule 都開火的
    `[WARN]` 同樣會讓它變綠。
    """
    lines, _ = select_rules.select(rules_dir, ["tasks/a.py"])
    assert any("01-always.md" in line for line in lines)
    assert "01-always.md" not in capsys.readouterr().err


def test_sr_sel_008_unreadable_rule_warns_and_other_rules_survive(
    rules_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """讀檔失敗必須 `[WARN]` 並繼續處理其他 rule。

    SKILL.md Step 2 的 exit-code 表把 `[WARN] 無法讀取 <rule>` 列為具名結果，但在加這條
    之前該分支零測試覆蓋：把 `except OSError` 改成 `except ValueError` 的 mutation 是
    **存活**的（整個 suite 照樣全綠），代表真的發生 OSError 時會直接 traceback 而沒有任何
    測試會紅。
    """
    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "04-tasks.md":
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    lines, _ = select_rules.select(rules_dir, ["tasks/a.py"])
    err = capsys.readouterr().err
    assert "04-tasks.md" in err
    assert "無法讀取" in err
    # 單一 rule 讀取失敗不得中斷其餘選取。
    assert any("01-always.md" in line for line in lines)


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


def test_sr_cli_004_dot_prefixed_path_survives_normalization_end_to_end(
    rules_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """端到端版本的 SR-SEL-004。

    這個測試取代了原本的「`./tasks/a.py` 會被正規化」版本——那個測試是假的：
    `glob_to_regex` 的 `(?:.*/)?` 前綴本來就吸收得掉 `./`，所以整行正規化刪掉它仍然綠，
    無法分辨 `lstrip` 與 `removeprefix`。這個案例前綴吸收不掉，才真的鎖住那行。
    """
    repo_root = rules_dir.parent.parent
    assert select_rules.main(["--repo-root", str(repo_root), ".claude/hooks/x.py"]) == 0
    assert "41-hooks.md" in capsys.readouterr().out


def test_sr_cli_005_no_scoped_rule_matched_warns(
    rules_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """給了路徑卻零 scoped 命中必須 [WARN]。

    always-loaded rule 會讓輸出永遠非空，所以這個警告不能用「輸出是否為空」判斷。
    """
    repo_root = rules_dir.parent.parent
    assert select_rules.main(["--repo-root", str(repo_root), "task/typo/db.py"]) == 0
    captured = capsys.readouterr()
    assert "[WARN]" in captured.err
    assert "01-always.md" in captured.out  # 仍列出 always-loaded，警告不是因為輸出為空


# --- SR-NP: path normalization ----------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("./tasks/a.py", "tasks/a.py"),
        ("././tasks/a.py", "tasks/a.py"),
        # 負向控制：dot-prefixed 路徑必須原封不動——lstrip 版本在這裡回 "claude/hooks/x.py"
        (".claude/hooks/x.py", ".claude/hooks/x.py"),
        (".github/workflows/ci.yml", ".github/workflows/ci.yml"),
        ("tasks/a.py", "tasks/a.py"),
    ],
)
def test_sr_np_001_normalize_path(given: str, expected: str) -> None:
    assert select_rules.normalize_path(given) == expected

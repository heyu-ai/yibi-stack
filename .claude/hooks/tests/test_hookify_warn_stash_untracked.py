"""hookify 規則 warn-stash-without-untracked 的正／負樣本測試。

規則檔：.claude/hookify.warn-stash-without-untracked.local.md

CI 環境沒有 hookify plugin，所以這裡**重現** hookify 讀取 pattern 的方式，而不是 import 它：
- frontmatter：`content.split('---', 2)`，取第二段
- 取值：頂層 `key: value` 行以 `split(':', 1)` 切開，value 只做 `strip()` 與
  `.strip('"').strip("'")`——**不處理任何跳脫**
- 比對：`re.compile(pattern, re.IGNORECASE).search(command)`
（出處：hookify plugin `core/config_loader.py` 的 `extract_frontmatter`、`core/rule_engine.py`
的 `compile_regex` / `_regex_match`。）

Probed. 下面同一組 30 個樣本已在本機對真實 hookify engine（plugin cache `a9fd21643fc1` 的
`load_rule_file` + `RuleEngine.evaluate_rules`）跑過，結果與本測試一致；規則的 7 個單點
mutation 也都被本測試抓到。(Source: PR #540 的 stash 稽核，lesson `git-stash-no-u-drops-untracked-half`)

「不處理跳脫」是這個測試存在的主要理由之一：若 pattern 寫成加引號的 `"...\\\\s..."`，
engine 實際拿到的是字面雙反斜線，規則會**靜默永不觸發**。repo 既有的
warn-plugin-version-lockstep 規則就是這個形狀（實測：`git add plugins/dev-cycle/package.json`
不觸發）。`test_hsu_vl_002_pattern_has_no_literal_double_backslash` 把這個陷阱鎖住。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RULE_FILE = REPO_ROOT / ".claude" / "hookify.warn-stash-without-untracked.local.md"


def _frontmatter(content: str) -> dict[str, str]:
    """照 hookify config_loader.extract_frontmatter 的頂層 key: value 規則取值。"""
    assert content.startswith("---"), "規則檔必須以 --- 開頭，否則 hookify 讀不到 frontmatter"
    parts = content.split("---", 2)
    assert len(parts) == 3, "frontmatter 缺少結尾的 ---"
    values: dict[str, str] = {}
    for line in parts[1].split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and ":" in line and not stripped.startswith("-"):
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@pytest.fixture(scope="module")
def rule() -> dict[str, str]:
    return _frontmatter(RULE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def regex(rule: dict[str, str]) -> re.Pattern[str]:
    return re.compile(rule["pattern"], re.IGNORECASE)


class TestStashRuleShape:
    def test_hsu_vl_001_rule_is_enabled_bash_warn(self, rule: dict[str, str]) -> None:
        """HSU-VL-001: 規則啟用、event=bash、action=warn（提醒，不擋）。"""
        assert rule["name"] == "warn-stash-without-untracked"
        assert rule["enabled"].lower() == "true"
        assert rule["event"] == "bash"
        assert rule["action"] == "warn"

    def test_hsu_vl_002_pattern_has_no_literal_double_backslash(self, rule: dict[str, str]) -> None:
        """HSU-VL-002: hookify 不處理跳脫，載入後的 pattern 不得含字面 `\\\\`（會靜默永不觸發）。"""
        assert "\\\\" not in rule["pattern"], rule["pattern"]

    def test_hsu_vl_003_frontmatter_survives_triple_dash_split(self) -> None:
        """HSU-VL-003: hookify 用 split('---', 2) 切 frontmatter，pattern 內不得出現 `---`。"""
        content = RULE_FILE.read_text(encoding="utf-8")
        frontmatter = content.split("---", 2)[1]
        assert "pattern:" in frontmatter, "pattern 必須落在 frontmatter 內"


SHOULD_WARN = [
    "git stash",
    "git stash push",
    'git stash push -m "wip"',
    'git stash save "wip"',
    "git stash -m wip",
    "git stash -k",
    "git -C /path/repo stash push -m x",
    "git --no-pager stash",
    "git stash && git checkout main",
    "git stash; git pull",
    "git stash push -- src/a.py",
    "git stash list && git stash",
]

SHOULD_STAY_SILENT = [
    # 已帶 untracked 相關旗標
    "git stash -u",
    "git stash push -u -m x",
    "git stash push --include-untracked",
    "git stash -a",
    "git stash push --all",
    "git stash -ku",
    "git stash push -um wip",
    # 不是「存」的子指令
    "git stash list",
    "git stash show -p stash@{0}",
    "git stash drop stash@{1}",
    "git stash pop",
    "git stash apply abc123",
    "git stash clear",
    "git stash branch foo",
    "git stash list --format=%H",
    "git stash -u && git stash list",
    # 無關指令
    "git status",
    "git log --grep=stash",
]


class TestStashRuleMatching:
    @pytest.mark.parametrize("command", SHOULD_WARN)
    def test_hsu_dt_001_stash_without_untracked_flag_warns(
        self, regex: re.Pattern[str], command: str
    ) -> None:
        """HSU-DT-001: 存 stash 且沒帶 -u／--include-untracked／-a／--all -> 觸發提醒。"""
        assert regex.search(command), f"應該觸發卻沒有：{command}"

    @pytest.mark.parametrize("command", SHOULD_STAY_SILENT)
    def test_hsu_dt_002_flagged_or_non_saving_stash_stays_silent(
        self, regex: re.Pattern[str], command: str
    ) -> None:
        """HSU-DT-002: 已帶 untracked 旗標、或 list/show/drop/pop/apply 等非存入子指令 -> 不提醒。"""
        assert not regex.search(command), f"不該觸發卻觸發了：{command}"

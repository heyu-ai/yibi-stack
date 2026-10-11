"""repo 內所有 hookify 規則（.claude/hookify.*.local.md）的載入與比對測試。

hookify 是外部 plugin，CI 沒有安裝它，所以這裡**重現**它讀取與比對規則的方式，而不是 import：

- `_extract_frontmatter`：照 hookify `core/config_loader.py` 的 `extract_frontmatter`——
  `split('---', 2)` 切 frontmatter；頂層 `key: value` 與 `conditions:` 底下的清單項目，
  value 一律只做 `strip()` 與 `.strip('"').strip("'")`，**不處理任何跳脫**。
- `_fires`：照 `core/rule_engine.py`——所有 condition 都成立才觸發；`regex_match` 用
  `re.compile(pattern, re.IGNORECASE).search`；欄位取值照 `_extract_field`
  （Bash 的 `command`；Edit 的 `file_path` / `new_text`→`new_string`）。

「不處理跳脫」是這個檔案存在的主要理由：pattern 一旦寫成加引號的 `"...\\\\."`，engine 拿到的
就是字面雙反斜線，規則**靜默永不觸發**、也不報錯。warn-plugin-version-lockstep 與
warn-subshell-exit-fail-open 兩條規則從建立起就是這個形狀，本 PR 才修正。

Probed. 修正前後都用真實 hookify engine（plugin cache `a9fd21643fc1` 的 `load_rule_file` +
`RuleEngine.evaluate_rules`）跑過下方 `SAMPLES`：修正前兩條規則的正樣本全部不觸發，修正後
12 個樣本全部與預期一致。(Source: PR #552 發現 warn-plugin-version-lockstep 不觸發)

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import re
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RULE_FILES = sorted((REPO_ROOT / ".claude").glob("hookify.*.local.md"))


def _clean(value: str) -> str:
    """hookify 對所有 value 做的唯一處理：去頭尾空白，再剝掉頭尾引號。"""
    return value.strip().strip('"').strip("'")


def _extract_frontmatter(content: str) -> dict[str, Any]:
    """照 hookify config_loader.extract_frontmatter 逐分支重現（含逗號分隔的單行 dict）。"""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    frontmatter: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[Any] = []
    current_dict: dict[str, str] = {}
    in_list = False
    in_dict_item = False

    for line in parts[1].split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and ":" in line and not stripped.startswith("-"):
            if in_list and current_key:
                if in_dict_item and current_dict:
                    current_list.append(current_dict)
                    current_dict = {}
                frontmatter[current_key] = current_list
                in_list = False
                in_dict_item = False
                current_list = []
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if not value:
                current_key = key
                in_list = True
                current_list = []
            else:
                frontmatter[key] = _clean(value)
        elif stripped.startswith("-") and in_list:
            if in_dict_item and current_dict:
                current_list.append(current_dict)
                current_dict = {}
            item = stripped[1:].strip()
            if ":" in item and "," in item:
                # 同一行逗號分隔的 dict：`- field: command, operator: regex_match`
                inline: dict[str, str] = {}
                for part in item.split(","):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        inline[k.strip()] = _clean(v)
                current_list.append(inline)
                in_dict_item = False
            elif ":" in item:
                in_dict_item = True
                k, v = item.split(":", 1)
                current_dict = {k.strip(): _clean(v)}
            else:
                current_list.append(_clean(item))
                in_dict_item = False
        elif indent > 2 and in_dict_item and ":" in line:
            k, v = stripped.split(":", 1)
            current_dict[k.strip()] = _clean(v)

    if in_list and current_key:
        if in_dict_item and current_dict:
            current_list.append(current_dict)
        frontmatter[current_key] = current_list
    return frontmatter


def _conditions(fm: dict[str, Any]) -> list[dict[str, str]]:
    """照 hookify Rule.from_dict：有 conditions 就用；否則把 pattern 依 event 轉成單一條件。"""
    conds = fm.get("conditions")
    if isinstance(conds, list) and conds:
        return conds
    pattern = fm.get("pattern")
    if not pattern:
        return []
    field = {"bash": "command", "file": "new_text"}.get(fm.get("event", "all"), "content")
    return [{"field": field, "operator": "regex_match", "pattern": pattern}]


def _field(field: str, tool: str, tool_input: dict[str, str]) -> str | None:
    """照 hookify rule_engine._extract_field（只涵蓋 Bash 與 Edit）。"""
    if field in tool_input:
        return tool_input[field]
    if tool == "Bash" and field == "command":
        return tool_input.get("command", "")
    if tool in ("Write", "Edit"):
        if field == "content":
            return tool_input.get("content") or tool_input.get("new_string", "")
        if field in ("new_text", "new_string"):
            return tool_input.get("new_string", "")
        if field == "file_path":
            return tool_input.get("file_path", "")
    return None


def _fires(fm: dict[str, Any], tool: str, tool_input: dict[str, str]) -> bool:
    conds = _conditions(fm)
    if not conds:
        return False
    for c in conds:
        value = _field(c["field"], tool, tool_input)
        if value is None:
            return False
        op, pattern = c["operator"], c["pattern"]
        if op == "regex_match":
            if not re.compile(pattern, re.IGNORECASE).search(value):
                return False
        elif op == "contains":
            if pattern not in value:
                return False
        elif op == "not_contains":
            if pattern in value:
                return False
        else:
            return False
    return True


def _load(path: Path) -> dict[str, Any]:
    return _extract_frontmatter(path.read_text(encoding="utf-8"))


def _by_name(name: str) -> dict[str, Any]:
    for path in RULE_FILES:
        fm = _load(path)
        if fm.get("name") == name:
            return fm
    raise AssertionError(f"找不到規則：{name}")


def test_hkr_vl_000_rule_files_exist() -> None:
    """HKR-VL-000: 至少找得到一條規則——glob 寫錯時下面的參數化測試會變成 0 個而假綠。"""
    assert RULE_FILES, "找不到任何 .claude/hookify.*.local.md"


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.name)
class TestEveryHookifyRule:
    def test_hkr_vl_001_loads_with_conditions(self, path: Path) -> None:
        """HKR-VL-001: 規則能被解析，有 name / event，且至少有一個條件（hookify 對 0 條件一律不觸發）。"""
        fm = _load(path)
        assert fm.get("name"), f"{path.name} 缺少 name"
        assert fm.get("event") in {"bash", "file", "stop", "prompt", "all"}, fm.get("event")
        assert _conditions(fm), f"{path.name} 沒有任何條件，永遠不會觸發"

    def test_hkr_vl_002_no_literal_double_backslash(self, path: Path) -> None:
        """HKR-VL-002: 載入後的 pattern 不得含字面 `\\\\`——hookify 不處理跳脫，這種 pattern 靜默永不觸發。

        要比對字面反斜線時改用 `\\x5c`。
        """
        for c in _conditions(_load(path)):
            assert "\\\\" not in c["pattern"], f"{path.name}：{c['pattern']!r}"

    def test_hkr_vl_003_every_regex_compiles(self, path: Path) -> None:
        """HKR-VL-003: 每個 regex_match 的 pattern 都能編譯（hookify 遇到錯誤 regex 只印 stderr 並當成不觸發）。"""
        for c in _conditions(_load(path)):
            if c["operator"] == "regex_match":
                re.compile(c["pattern"], re.IGNORECASE)


SUBSHELL_FIRES = '_helper() {\n  if [ -z "$x" ]; then\n    exit 1\n  fi\n}\nX=$(_helper)\n'
SUBSHELL_NO_EXIT = "_helper() {\n  return 2\n}\nX=$(_helper) || RC=$?\n"


def _edit(path: str, text: str) -> dict[str, str]:
    return {"file_path": path, "old_string": "", "new_string": text}


# (規則名稱, tool, tool_input, 是否應觸發)；修正前後都已對真實 engine 跑過，見模組 docstring
SAMPLES = [
    (
        "warn-plugin-version-lockstep",
        "Bash",
        {"command": "git add plugins/dev-cycle/package.json"},
        True,
    ),
    ("warn-plugin-version-lockstep", "Bash", {"command": "jq . plugins/growth/package.json"}, True),
    ("warn-plugin-version-lockstep", "Bash", {"command": "git add package.json"}, False),
    (
        "warn-plugin-version-lockstep",
        "Bash",
        {"command": "git add plugins/dev-cycle/.claude-plugin/plugin.json"},
        False,
    ),
    # `\.` 必須是字面的點：修正前的 `\\.` 與修正後若誤寫成 `.` 都分辨不出這一格
    (
        "warn-plugin-version-lockstep",
        "Bash",
        {"command": "cat plugins/dev-cycle/packageXjson"},
        False,
    ),
    ("warn-subshell-exit-fail-open", "Edit", _edit("scripts/a.sh", SUBSHELL_FIRES), True),
    ("warn-subshell-exit-fail-open", "Edit", _edit("scripts/a.py", SUBSHELL_FIRES), False),
    ("warn-subshell-exit-fail-open", "Edit", _edit("scripts/a.sh", SUBSHELL_NO_EXIT), False),
    ("warn-subshell-exit-fail-open", "Edit", _edit("scripts/a.shx", SUBSHELL_FIRES), False),
    ("warn-rglob-symlink", "Edit", _edit("tasks/x.py", "for p in d.rglob('*.md'):"), True),
    ("warn-rglob-symlink", "Edit", _edit("tasks/x.py", "for p in d.glob('*.md'):"), False),
    ("warn-rglob-symlink", "Edit", _edit("docs/x.md", "d.rglob('*.md')"), False),
]


@pytest.mark.parametrize(
    ("name", "tool", "tool_input", "expected"),
    SAMPLES,
    ids=[f"{s[0]}-{i}" for i, s in enumerate(SAMPLES)],
)
def test_hkr_dt_001_rule_samples(
    name: str, tool: str, tool_input: dict[str, str], expected: bool
) -> None:
    """HKR-DT-001: 各規則的正／負樣本與預期一致（正樣本保證規則真的會觸發，不只是「沒誤報」）。"""
    assert _fires(_by_name(name), tool, tool_input) is expected, tool_input

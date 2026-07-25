"""lint_rule_evidence 純函式測試（合成 diff fixture）。

對應 testplan：REG-EG-001a/b/c（分層強制）、REG-VL-001（錨點缺失不空洞通過）、
2.3 new-section heuristic（編輯既有 section 不誤觸發）。加上 PR #339 mob review
找出的迴歸案例：settings.json / .pre-commit-config.yaml 新註冊 hook 未受檢查、
CLAUDE.md 未納入 always-loaded 文件面、無數字前綴的新 rule 檔逃過兩層檢查、巢狀
hook script 路徑逃過檢查、以及證據標記在 table row / fenced code block 內被誤判
為「已有證據」。

關鍵：只對真實檔案斷言的 lint 無法測自己的失敗路徑；這裡以純函式入口 + 合成 diff
驗證負向案例。
"""

import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lint_rule_evidence  # noqa: E402
from lint_rule_evidence import (  # noqa: E402
    check_rule_evidence,
    warn_rule_evidence,
)


def _new_file_diff(path: str, body_lines: list[str]) -> str:
    added = "\n".join(f"+{line}" for line in body_lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(body_lines)} @@\n"
        f"{added}\n"
    )


def _existing_file_diff(path: str, added_body: list[str]) -> str:
    added = "\n".join(f"+{line}" for line in added_body)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -10,0 +11 @@\n{added}\n"


# --- REG-EG-001a：新 rule 檔缺證據標記 -> error 非空 ---


def test_new_rule_file_missing_evidence_is_error():
    diff = _new_file_diff(".claude/rules/17-foo.md", ["# Foo", "一些沒有證據的規則內容。"])
    errors = check_rule_evidence(diff)
    assert errors, "新 rule 檔缺證據標記應回傳非空 error 清單"
    assert ".claude/rules/17-foo.md" in errors[0]


def test_new_rule_file_with_structured_marker_passes():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md",
        ["# Foo", "規則內容。", "<!-- verified: probe -->"],
    )
    assert check_rule_evidence(diff) == []


def test_new_rule_file_with_prose_source_marker_passes():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md",
        ["# Foo", "規則內容。（Source: PR #250 實測）"],
    )
    assert check_rule_evidence(diff) == []


def test_new_rule_file_with_probed_marker_passes():
    diff = _new_file_diff(".claude/rules/17-foo.md", ["# Foo", "規則內容。Probed."])
    assert check_rule_evidence(diff) == []


def test_new_rule_file_with_verified_on_marker_passes():
    diff = _new_file_diff(
        ".claude/rules/17-foo.md",
        ["# Foo", "行為宣稱（verified on agy 1.1.2）。"],
    )
    assert check_rule_evidence(diff) == []


# --- REG-EG-001c：新 hook 檔缺證據標記 -> error 非空 ---


def test_new_hook_missing_evidence_is_error():
    diff = _new_file_diff(".claude/hooks/foo-check.py", ["import sys", "sys.exit(0)"])
    errors = check_rule_evidence(diff)
    assert errors
    assert ".claude/hooks/foo-check.py" in errors[0]


# --- REG-EG-001b：既有 rule 檔新增 section 缺標記 -> warn（非 error）---


def test_existing_rule_new_section_missing_evidence_is_warn_not_error():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["## 新的反模式", "一段沒有證據的說明。"],
    )
    assert check_rule_evidence(diff) == [], "既有檔新 section 不應是 error（只 warn）"
    warns = warn_rule_evidence(diff)
    assert warns
    assert "新的反模式" in warns[0]


def test_existing_rule_new_section_with_marker_no_warn():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["## 新的反模式", "說明。Probed."],
    )
    assert warn_rule_evidence(diff) == []


# --- 2.3 heuristic：編輯既有 section（無新 heading）不誤觸發 warn ---


def test_editing_existing_section_no_new_heading_no_warn():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["在既有段落裡多加一行說明，沒有新增 heading。"],
    )
    assert warn_rule_evidence(diff) == []
    assert check_rule_evidence(diff) == []


# --- REG-VL-001：錨點缺失不空洞通過；真正空 diff 才回空 ---


def test_anchor_missing_is_not_vacuous_pass():
    """有新 rule 內容但缺證據標記（錨點缺失）-> 非空，不得因找不到錨點而回空。"""
    diff = _new_file_diff(".claude/rules/18-bar.md", ["# Bar", "內容但無任何證據錨點。"])
    assert check_rule_evidence(diff) != []


def test_empty_diff_returns_empty():
    """真正空的 diff（沒 stage 任何東西）-> 無可檢查，回空清單才正確。"""
    assert check_rule_evidence("") == []
    assert warn_rule_evidence("") == []


# --- 非 rule/hook 的新檔不受管 ---


def test_new_non_rule_file_ignored():
    diff = _new_file_diff("scripts/foo.py", ["print('hi')"])
    assert check_rule_evidence(diff) == []
    assert warn_rule_evidence(diff) == []


# --- AC-6 迴歸：既有 settings.json / .pre-commit-config.yaml 新註冊 hook 缺標記 -> error ---


def test_settings_json_new_hook_missing_evidence_is_error():
    diff = _existing_file_diff(
        ".claude/settings.json",
        ['"command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/foo-new-check.py || exit 2"'],
    )
    errors = check_rule_evidence(diff)
    assert errors, "settings.json 新註冊 hook 缺證據標記應回傳非空 error 清單"
    assert ".claude/settings.json" in errors[0]


def test_settings_json_new_hook_with_marker_passes():
    diff = _existing_file_diff(
        ".claude/settings.json",
        [
            '"command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/foo-new-check.py || exit 2",',
            "// <!-- verified: probe -->",
        ],
    )
    assert check_rule_evidence(diff) == []


def test_settings_json_edit_without_new_hook_command_ignored():
    """既有 settings.json 的其他編輯（不含新增 hook command）不應誤觸發。"""
    diff = _existing_file_diff(".claude/settings.json", ['"someOtherKey": "value"'])
    assert check_rule_evidence(diff) == []


def test_precommit_config_new_hook_id_missing_evidence_is_error():
    diff = _existing_file_diff(
        ".pre-commit-config.yaml",
        ["      - id: foo-new-check", "        entry: python3 scripts/foo_new_check.py"],
    )
    errors = check_rule_evidence(diff)
    assert errors
    assert ".pre-commit-config.yaml" in errors[0]


def test_precommit_config_new_hook_id_with_marker_passes():
    diff = _existing_file_diff(
        ".pre-commit-config.yaml",
        ["      - id: foo-new-check", "        # <!-- verified: probe -->"],
    )
    assert check_rule_evidence(diff) == []


# --- AC-6/AC-7 迴歸：CLAUDE.md 納入 always-loaded 文件面（既有檔新 section -> warn）---


def test_claude_md_new_section_missing_evidence_is_warn_not_error():
    diff = _existing_file_diff("CLAUDE.md", ["## 新的慣例", "一段沒有證據的說明。"])
    assert check_rule_evidence(diff) == [], "CLAUDE.md 新 section 不應是 error（只 warn）"
    warns = warn_rule_evidence(diff)
    assert warns
    assert "新的慣例" in warns[0]


def test_claude_md_new_section_with_marker_no_warn():
    diff = _existing_file_diff("CLAUDE.md", ["## 新的慣例", "說明。Probed."])
    assert warn_rule_evidence(diff) == []


# --- AC-6 迴歸：無數字前綴的新 rule 檔仍須受檢（NN- 只是命名慣例，非把關條件）---


def test_new_rule_file_without_numeric_prefix_missing_evidence_is_error():
    diff = _new_file_diff(
        ".claude/rules/retro-evidence.md", ["# Retro Evidence", "沒有證據的內容。"]
    )
    errors = check_rule_evidence(diff)
    assert errors, "無數字前綴的新 rule 檔缺證據標記，過去會同時逃過 error 與 warn 兩層"
    assert ".claude/rules/retro-evidence.md" in errors[0]


# --- AC-6 迴歸：巢狀 hook script 路徑仍須受檢 ---


def test_nested_hook_script_missing_evidence_is_error():
    diff = _new_file_diff(".claude/hooks/lib/foo-check.py", ["import sys", "sys.exit(0)"])
    errors = check_rule_evidence(diff)
    assert errors, "巢狀路徑下的新 hook script 缺證據標記，過去因單層路徑正則逃過檢查"
    assert ".claude/hooks/lib/foo-check.py" in errors[0]


# --- AC-7 迴歸：證據標記只在 table row / fenced code block 內出現時，不算真的有證據 ---


def test_marker_only_in_table_row_is_not_counted_as_evidence():
    """rule 11 自己的新 section 曾以此方式誤判：表格內「範例」文字含標記字串，
    被當成該 section 已有真實證據，實際上該 section 從未真的宣稱自己已驗證。
    """
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        [
            "## 新的反模式",
            "說明。",
            "| 類型 | 範例 |",
            "| --- | --- |",
            "| 結構化 | `<!-- verified: probe -->` |",
        ],
    )
    warns = warn_rule_evidence(diff)
    assert warns, "table row 裡的標記語法範例不應被視為真實證據"


def test_marker_only_in_fenced_code_block_is_not_counted_as_evidence():
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        [
            "## 新的反模式",
            "說明。範例標記語法：",
            "```",
            "<!-- verified: probe -->",
            "```",
        ],
    )
    warns = warn_rule_evidence(diff)
    assert warns, "fenced code block 內的標記語法範例不應被視為真實證據"


def test_marker_outside_table_and_fence_still_counts_as_evidence():
    """確認上面兩個負向控制不是矯枉過正：真正在 prose 行內出現的標記仍要通過。"""
    diff = _existing_file_diff(
        ".claude/rules/13-bash-anti-patterns.md",
        ["## 新的反模式", "說明。<!-- verified: probe -->"],
    )
    assert warn_rule_evidence(diff) == []


# --- exit-code 契約迴歸：git 不可用時 _staged_diff 應轉為 RuntimeError（main() 的 exit 2 路徑）---


def test_staged_diff_wraps_missing_git_binary_as_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(RuntimeError):
        lint_rule_evidence._staged_diff()

"""lint_rule_evidence 純函式測試（合成 diff fixture）。

對應 testplan：REG-EG-001a/b/c（分層強制）、REG-VL-001（錨點缺失不空洞通過）、
2.3 new-section heuristic（編輯既有 section 不誤觸發）。

關鍵：只對真實檔案斷言的 lint 無法測自己的失敗路徑；這裡以純函式入口 + 合成 diff
驗證負向案例。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

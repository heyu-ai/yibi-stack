"""pr-retrospective SKILL.md「機械化優先：hook／lint > rule」錨點測試。

使用者要求 `/pr-retro` 判斷 lesson 落點時，預設先想能不能做成 hook 或 lint，做不出來才寫
rule。改版前 SKILL.md 有三處與此相反：Step 2 的 Q5 清單把「寫入規則文件」排第一、完全沒有
lint 選項；Promotion Gate G1 只問 hook；Patch-Surface Ladder 把 `reference rule` 排在
`script helper`（lint）之前。本檔鎖住改版後的優先序，避免日後改寫時默默退回。

每個 section helper 找不到標題就 fail，不回傳空字串（rule 17「Doc-Guard Tests」）。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "plugins" / "growth" / "skills" / "pr-retrospective" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    """回傳 start 與其後第一個 end 之間的內容；任一錨點不存在就 fail。"""
    assert start in text, f"解析前提不成立：找不到起點錨點 {start!r}"
    begin = text.index(start)
    assert end in text[begin:], f"解析前提不成立：{start!r} 之後找不到終點錨點 {end!r}"
    return text[begin : text.index(end, begin)]


def _index_in(block: str, needle: str) -> int:
    assert needle in block, f"區塊內找不到 {needle!r}"
    return block.index(needle)


def test_prm_dt_001_q5_draft_lists_hook_and_lint_before_rule() -> None:
    """PRM-DT-001: Step 2 草稿的 Q5 清單，hook 與 lint 排在寫入規則文件之前"""
    block = _between(_skill_text(), "### Q5 Improvement Actions", "請回覆：")
    rule_idx = _index_in(block, "- [ ] 寫入規則文件")
    assert _index_in(block, "- [ ] 新增 hook") < rule_idx
    assert _index_in(block, "- [ ] 新增 lint") < rule_idx


def test_prm_dt_002_g1_asks_hook_and_lint() -> None:
    """PRM-DT-002: Promotion Gate G1 同時問 hook 與 lint，失敗時改走 hook／lint 而非 rule"""
    gate = _between(_skill_text(), "#### Promotion Gate", "#### Lesson Classifier")
    g1_start = _index_in(gate, "| **G1 automation-infeasible** |")
    g1_row = gate[g1_start : gate.index("\n", g1_start)]
    assert "hook" in g1_row
    assert "lint" in g1_row
    assert "新增 lint" in g1_row, "G1 失敗動作必須指向 Q5「新增 lint」"


def test_prm_dt_003_mechanical_first_section_sits_inside_promotion_gate() -> None:
    """PRM-DT-003: 「機械化優先」段落存在，且位於 Promotion Gate 與 Lesson Classifier 之間"""
    gate = _between(_skill_text(), "#### Promotion Gate", "#### Lesson Classifier")
    section = _between(gate, "##### 機械化優先：hook／lint > rule", "> 此 gate 的設計邏輯")
    for target in ("hook", "lint", "gate: none"):
        assert target in section, f"機械化優先段落缺少 {target!r}"


def test_prm_dt_004_ladder_ranks_script_helper_above_reference_rule() -> None:
    """PRM-DT-004: Patch-Surface Ladder 中 script helper（hook／lint）排在 reference rule 之前"""
    ladder = _between(
        _skill_text(),
        "#### 最小相容修改階梯（Patch-Surface Ladder）",
        "#### CLAUDE.md 行數檢查",
    )
    assert _index_in(ladder, "| `script helper` |") < _index_in(ladder, "| `reference rule` |")


def test_prm_vl_001_lint_action_row_requires_evidence_gate() -> None:
    """PRM-VL-001: Q5 映射表的「新增 lint」列與相鄰兩列一樣，須先通過 Evidence Gate"""
    text = _skill_text()
    rows = [ln for ln in text.splitlines() if ln.startswith("| 新增 lint |")]
    assert len(rows) == 1, f"Q5 映射表應恰有一列「新增 lint」，實得 {len(rows)}"
    assert "須先通過 Step 5.0 Evidence Gate" in rows[0]
    assert ".pre-commit-config.yaml" in rows[0]

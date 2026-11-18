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
    action = g1_row.rsplit("|", 2)[-2]
    assert "不寫 rule" in action, "G1 失敗動作欄必須明寫「不寫 rule」，否則語意可被翻轉而錨點仍在"


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


def test_prm_dt_005_g1_mechanical_lessons_still_written_active_with_marker() -> None:
    """PRM-DT-005: G1 判定可機械化的 lesson 照常以 active 寫入，insight 帶 gate-pending 標記"""
    gate = _between(_skill_text(), "#### Promotion Gate", "##### 機械化優先")
    assert "只有在 G1+G2+G3 全通過後" not in gate, "舊的耦合句仍在：G1 不得再擋 active 寫入"
    clause = _between(gate, "Typed lesson 寫入與 G1 脫鉤", "\n\n")
    for target in ("照常以 `state=active` 寫入", "`[gate-pending:hook]`", "`[gate-pending:lint]`"):
        assert target in clause, f"脫鉤條款缺少 {target!r}"
    assert "harness-weekly-review" in clause, "必須指明每週由誰確認"


def test_prm_dt_006_step4b_note_matches_decoupling() -> None:
    """PRM-DT-006: Step 4b 開頭的執行條件與脫鉤後的 Promotion Gate 一致"""
    note = _between(_skill_text(), "### Step 4b", "Classifier → `--type` 對照表")
    assert "G1+G2+G3 才正常寫入" not in note
    assert "gate-pending" in note


def test_prm_dt_007_reassess_exit_for_mechanical_lesson_uses_finalize_with_marker() -> None:
    """PRM-DT-007: reassess 重評後 G1 判定可機械化 → finalize 並以 --insight 補上標記，不 re-park"""
    exits = _between(
        _skill_text(),
        "| 重評結論 | 動作 | 終止狀態 | 可重試？ |",
        "**`--park` 這兩條出口不可重試**",
    )
    rows = [ln for ln in exits.splitlines() if "G1 判定可機械化" in ln]
    assert len(rows) == 1, f"reassess 出口表應恰有一列 G1 可機械化，實得 {len(rows)}"
    assert "`lessons finalize --id`" in rows[0]
    assert "--insight" in rows[0]
    assert "gate-pending" in rows[0]


WEEKLY_MD = REPO_ROOT / "plugins" / "harness" / "skills" / "harness-weekly-review" / "SKILL.md"


def test_prm_st_001_weekly_review_confirms_gate_pending_lessons() -> None:
    """PRM-ST-001: harness-weekly-review 每週列出 gate-pending lesson 並給出收尾指令"""
    text = WEEKLY_MD.read_text(encoding="utf-8")
    step = _between(text, "### Step 4b — 確認待做成 gate 的 lesson", "### Step 5")
    for target in (
        'mycelium lessons search "gate-pending:"',
        "--json",
        "mycelium lessons retire --id",
        "需要 owner 裁決",
    ):
        assert target in step, f"Step 4b 缺少 {target!r}"
    report = _between(text, "### Step 7 — 回報", "## 門檻")
    assert "gate-pending" in report, "Step 7 回報必須列出待做成 gate 的 lesson"


def test_prm_vl_001_lint_action_row_requires_evidence_gate() -> None:
    """PRM-VL-001: Q5 映射表的「新增 lint」列與相鄰兩列一樣，須先通過 Evidence Gate"""
    text = _skill_text()
    rows = [ln for ln in text.splitlines() if ln.startswith("| 新增 lint |")]
    assert len(rows) == 1, f"Q5 映射表應恰有一列「新增 lint」，實得 {len(rows)}"
    assert "須先通過 Step 5.0 Evidence Gate" in rows[0]
    assert ".pre-commit-config.yaml" in rows[0]

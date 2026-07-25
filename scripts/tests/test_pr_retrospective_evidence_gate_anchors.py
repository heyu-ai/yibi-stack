"""pr-retrospective SKILL.md 的 Step 5.0 Evidence Gate 錨點測試。

`openspec/changes/add-retro-evidence-gate/tasks.md` 3.1-3.6 每項都聲稱「驗證：錨點測試確認
<string> 存在」，但直到 PR #339 mob review（Claude/Codex/Gemini 三方一致）指出前，這些
tasks 都只做過一次性人工檢查，從未有任何 pytest 真正鎖住這些字串——刪掉 SKILL.md:476 那行
「須先通過 Step 5.0 Evidence Gate」（AC-1 唯一的實際 gate 接線點）會讓 `make ci` 照樣全綠。

本檔把 tasks.md 3.1-3.6 與 4.1 聲稱的錨點，逐一轉成真正對真實檔案內容的斷言。這些是
testplan.md 中標 `[doc]`（對真實 SKILL.md / rule 斷言）的 TC，不是重新定義新的驗證邏輯。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "plugins" / "pr-flow" / "skills" / "pr-retrospective" / "SKILL.md"
RULE_11 = REPO_ROOT / ".claude" / "rules" / "11-skill-authoring.md"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _rule_11_text() -> str:
    return RULE_11.read_text(encoding="utf-8")


# --- task 3.1：Step 5.0 段存在，且位於 Promotion Gate 敘述之前 ---


def test_step_5_0_section_exists_before_promotion_gate() -> None:
    text = _skill_text()
    step_5_0_idx = text.index("#### Step 5.0 Evidence Gate")
    promotion_gate_idx = text.index("#### Promotion Gate（3 條，全通過才路由到 rule 檔）")
    assert step_5_0_idx < promotion_gate_idx, "Step 5.0 必須排在 Promotion Gate 之前（上游 gate）"


# --- task 3.2：證據形式表為封閉列舉，末列標「無可接受形式，恆 park」，無 catch-all 字樣 ---


def test_evidence_form_table_last_row_and_no_catchall() -> None:
    text = _skill_text()
    assert "無可接受形式" in text
    assert "恆 park" in text or "恆歸 Tier 3" in text
    assert "catch-all" in text  # 出現在「表中不得有 catch-all 列」的宣告本身
    # 反面驗證：表格實際內容不含常見 catch-all 措辭（如 "其他"/"other"/"etc." 當作獨立列）
    assert "| 其他 |" not in text
    assert "| other |" not in text.lower().replace("其他", "")


# --- task 3.3：三種執行結果（重現／未重現／無效）與「無效先修一次、降 Tier 3、不記未重現、不 drop」 ---


def test_probe_outcome_three_way_split_anchors() -> None:
    text = _skill_text()
    for anchor in ("跑了、宣稱重現", "跑了、宣稱不成立", "根本跑不起來（證據無效）"):
        assert anchor in text, f"缺少三種執行結果錨點：{anchor}"
    assert "先修一次" in text
    assert "降 Tier 3 park" in text
    assert "不記為未重現" in text
    assert "不 drop" in text


# --- task 3.4：成本分層（結構檢查零成本、秒級 probe 當場跑、派 subagent 或降 Tier 2） ---


def test_cost_tiering_anchors() -> None:
    text = _skill_text()
    assert "派 subagent" in text
    assert "降級 Tier 2" in text
    assert "結構檢查（零指令）" in text
    assert "秒級 probe 當場跑" in text


# --- task 3.5：Q5→action 映射表「寫入規則文件」「新增 hook」兩列皆含證據前置條件 ---


def test_q5_action_mapping_rows_require_evidence_gate_first() -> None:
    text = _skill_text()
    write_rule_row = text[text.index("| 寫入規則文件 |") : text.index("| 新增 hook |")]
    hook_row_start = text.index("| 新增 hook |")
    hook_row = text[hook_row_start : text.index("\n", hook_row_start)]
    assert "須先通過 Step 5.0 Evidence Gate" in write_rule_row, (
        "「寫入規則文件」列缺少 Evidence Gate 前置條件——這是 AC-1"
        "「未分級者 MUST NOT 進入 Promotion Gate」唯一的實際接線點"
    )
    assert "須先通過 Step 5.0 Evidence Gate" in hook_row, (
        "「新增 hook」列缺少 Evidence Gate 前置條件"
    )


# --- task 3.6：Tier 3 park 與 recurrence 升級規則 ---


def test_tier3_park_and_recurrence_anchors() -> None:
    text = _skill_text()
    assert "recurrence ≥ 2" in text
    assert "解除 park" in text
    assert "仍須通過 Tier 1" in text
    assert "typed-lessons" in text
    assert "confidence ≤ 4" in text
    assert '"parked"' in text or '`"parked"`' in text


# --- task 4.1：rule 11 新增「Retro-authored rule/hook 的三層證據標準」段 ---


def test_rule_11_evidence_standard_section_exists() -> None:
    text = _rule_11_text()
    assert "Retro-authored rule/hook 的三層證據標準" in text

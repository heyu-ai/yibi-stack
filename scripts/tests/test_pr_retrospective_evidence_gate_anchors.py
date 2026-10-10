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
SKILL_MD = REPO_ROOT / "plugins" / "growth" / "skills" / "pr-retrospective" / "SKILL.md"
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


# --- rule-mechanization-gate：rule 草稿須附機械化宣告 ---
#
# 文件與程式碼對照：宣告語法、合格目錄、豁免理由的**唯一真相**是 `lint_rule_evidence.py`
# 的常數；SKILL.md 模板與 rule 11 各抄了一份給人讀。直接拿常數去比對文件，任何一邊改了
# 另一邊沒跟，這裡就轉紅（不靠人記得同步）。

_RULE_11_MECHANIZATION_HEADING = (
    "## Every New Rule Section Declares Whether It Could Have Been a Gate"
)


def _lint_module():
    import importlib
    import sys

    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module("lint_rule_evidence")


def _skill_rule_writing_row() -> str:
    rows = [ln for ln in _skill_text().splitlines() if ln.startswith("| 寫入規則文件 |")]
    assert len(rows) == 1, f"Step 5 Q5 映射表應恰有一列「寫入規則文件」，實得 {len(rows)}"
    return rows[0]


def _rule_11_mechanization_section() -> str:
    text = _rule_11_text()
    start = text.index(_RULE_11_MECHANIZATION_HEADING)
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_skill_rule_draft_template_carries_the_declaration_fields() -> None:
    row = _skill_rule_writing_row()
    assert "<!-- gate: <path>[::<symbol>] -->" in row
    assert "<!-- gate: none (reason:" in row
    assert "scripts/lint_rule_evidence.py" in row


def test_skill_template_lists_every_eligible_gate_location_and_reason() -> None:
    lint = _lint_module()
    row = _skill_rule_writing_row()
    for prefix in lint._GATE_DIR_PREFIXES:
        assert prefix in row, f"SKILL.md 模板缺合格 gate 目錄 {prefix}"
    for exact in lint._GATE_EXACT_FILES:
        assert exact in row, f"SKILL.md 模板缺合格 gate 檔 {exact}"
    assert "tasks/**/tests/" in row
    for reason in lint._EXEMPT_REASONS:
        assert reason in row, f"SKILL.md 模板缺豁免理由 {reason}"


def test_rule_11_mechanization_section_matches_the_lint_constants() -> None:
    lint = _lint_module()
    section = _rule_11_mechanization_section()
    for prefix in lint._GATE_DIR_PREFIXES:
        assert prefix in section, f"rule 11 缺合格 gate 目錄 {prefix}"
    for exact in lint._GATE_EXACT_FILES:
        assert exact in section, f"rule 11 缺合格 gate 檔 {exact}"
    for reason in lint._EXEMPT_REASONS:
        assert reason in section, f"rule 11 缺豁免理由 {reason}"
    assert str(lint._MIN_EXPLANATION_CHARS) in section


def test_rule_11_mechanization_section_passes_its_own_lint() -> None:
    """dogfood：這個 section 自己的宣告必須是個真宣告——對自己新增的內容跑一次 lint。"""
    lint = _lint_module()
    section = _rule_11_mechanization_section()
    block = section.splitlines()
    payloads = lint._declaration_payloads(block)
    assert len(payloads) == 1, f"section 內應恰有一個宣告，實得 {payloads}"
    assert lint._declaration_problems(payloads, lint._read_repo_file) == []

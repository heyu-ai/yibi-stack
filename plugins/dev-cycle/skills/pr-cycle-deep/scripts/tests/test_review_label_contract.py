"""RLC: SKILL.md 的 review-in-progress label 時序契約（issue #587）。

只證明「文件仍寫著這些規則」，不證明 agent 會照做（LLM runtime 行為無法在此驗證）。
`check_label_contract(text)` 是純函式，這樣才能用 mutation 餵它壞輸入、證明它會轉紅：
只對真實檔案斷言的測試，自己的失敗路徑永遠測不到。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[2] / "SKILL.md"
ADD = "review-label.sh add"
REMOVE = "review-label.sh remove"
GH_REMOVE = "--remove-label"
# Step 8 裡「使用者回覆 ship 才往下走」那句；撤 label 必須出現在它之後。
SHIP_ANCHOR = 'user replies "ship" before proceeding to Step 9'
NO_MECHANISM = "本 repo 沒有 review-in-progress 阻擋機制"


def _section(text: str, heading: str, level: str = "###") -> str:
    """回傳 `heading` 起到下一個段落標題之前的內容。

    `###` 層級的終點是下一個 `### Step ` 或 `## Troubleshooting`；`####` 層級的終點是
    下一個 `#### ` 或 `### Step `。終點刻意不認一般的 `#`：SKILL.md 的 code fence 內有
    `### Goal`、`# Human Quick Pass` 之類的範本標題，用一般 heading 當終點會提早截斷。
    找不到起點就 raise，不回傳空字串（空字串會讓「不得出現」類斷言假綠）。
    """
    end = r"^#### |^### Step " if level == "####" else r"^### Step |^## Troubleshooting"
    pattern = re.compile(
        rf"^{re.escape(level)} {re.escape(heading)}.*?(?={end}|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"heading not found: {level} {heading}")
    return match.group(0)


def _row(section: str, prefix: str) -> str:
    """回傳 section 內以 `prefix` 開頭、剛好唯一的一行（表格列）；找不到或不唯一就 raise。"""
    rows = [line for line in section.splitlines() if line.startswith(prefix)]
    if len(rows) != 1:
        raise AssertionError(f"expected exactly one row starting with {prefix!r}, got {len(rows)}")
    return rows[0]


def check_label_contract(text: str) -> list[str]:
    """回傳違反時序契約的條目；空 list 代表符合。"""
    problems: list[str] = []
    step1 = _section(text, "Step 1 —")
    step5b = _section(text, "Step 5b")
    step6 = _section(text, "Step 6")
    step8 = _section(text, "Step 8")
    step10 = _section(text, "Step 10")
    breaker = _section(text, "Circuit breaker", level="####")

    # Step 1：貼 label，以及 exit table 的語意（AC-3）。
    if ADD not in step1:
        problems.append("Step 1 must add the label")
    row10 = _row(step1, "| `10` |")
    if "Continue" not in row10 or "MUST say" not in row10:
        problems.append("Step 1 exit 10 row must say Continue and require the Step 8 note")
    if "**Stop**" not in _row(step1, "| other |"):
        problems.append("Step 1 other row must say **Stop**")

    # Step 5b：修正還沒做，不得撤。
    if REMOVE in step5b or GH_REMOVE in step5b:
        problems.append("Step 5b must not remove the label (fixes are not done yet)")

    # Step 6：MERGED／CLOSED 兩個出口各自要撤。
    if REMOVE not in _row(step6, "| `MERGED` |"):
        problems.append("Step 6 MERGED row must remove the label")
    if REMOVE not in _row(step6, "| `CLOSED` |"):
        problems.append("Step 6 CLOSED row must remove the label")

    # Step 7 circuit breaker：撤、三個選項的 label 狀態、continue 時要重貼。
    if REMOVE not in breaker:
        problems.append("circuit breaker must remove the label")
    if ADD not in breaker:
        problems.append("circuit breaker must re-add the label on Continue fixing")
    for anchor in (
        "label already off",
        "removed early by the circuit breaker",
        "Step 1's exit table",
        "do not resume fixing",
        "the label stays off",
    ):
        if anchor not in breaker:
            problems.append(f"circuit breaker must define the label state: {anchor}")

    # Step 8：ship 之後才撤；摘要要涵蓋三種狀態；撤失敗不得往下走（AC-1／AC-3）。
    if REMOVE not in step8:
        problems.append("Step 8 must remove the label")
    else:
        ship_at = step8.find(SHIP_ANCHOR)
        remove_at = step8.find(REMOVE)
        if ship_at == -1 or remove_at < ship_at:
            problems.append('Step 8 must remove the label after the user replies "ship"')
    if NO_MECHANISM not in step8:
        problems.append("Step 8 template must carry the no-blocking-mechanism sentence")
    if "removed early by circuit breaker" not in step8:
        problems.append("Step 8 template must carry the circuit-breaker-removed state")
    if "do not continue to Step 9 until they confirm" not in step8:
        problems.append(
            "Step 8 must not continue to Step 9 until the user confirms a failed remove"
        )

    # Step 10：merge gate 的出口。
    if REMOVE not in step10:
        problems.append("Step 10 gate must remove the label")
    return problems


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_real_skill_satisfies_contract(skill_text: str) -> None:
    """RLC-ST-001: 真實 SKILL.md 符合契約。"""
    assert check_label_contract(skill_text) == []


def _mutate_once(
    skill_text: str,
    heading: str,
    level: str,
    anchor: str,
    replacement: str,
) -> str:
    """只在 `heading` 區段內把 `anchor` 的唯一一處換成 `replacement`。

    anchor 在該區段不是恰好出現一次就 fail，避免一次改到多處。
    """
    section = _section(skill_text, heading, level)
    assert skill_text.count(section) == 1, f"section not unique: {heading}"
    assert section.count(anchor) == 1, f"anchor drifted or ambiguous in {heading}: {anchor!r}"
    assert anchor != replacement
    return skill_text.replace(section, section.replace(anchor, replacement))


def test_mutation_remove_moved_into_step_5b_turns_red(skill_text: str) -> None:
    """RLC-MT-001: 把撤 label 移回 Step 5b（#2449 的失敗形狀）必須轉紅。"""
    anchor = "Do **not** touch the `review-in-progress` label here"
    mutated = _mutate_once(skill_text, "Step 5b", "###", anchor, f"`bash x/{REMOVE} 1` {anchor}")
    problems = check_label_contract(mutated)
    assert any("Step 5b must not remove" in p for p in problems), problems


def test_mutation_missing_step_8_remove_turns_red(skill_text: str) -> None:
    """RLC-MT-002: Step 8 沒有撤 label 必須轉紅（fail-closed 方向也要有出口）。"""
    mutated = _mutate_once(skill_text, "Step 8", "###", REMOVE, "review-label.sh noop")
    assert "Step 8 must remove the label" in check_label_contract(mutated)


def test_mutation_step_8_remove_before_ship_turns_red(skill_text: str) -> None:
    """RLC-MT-003: Step 8 在使用者回覆 ship 之前就撤，必須轉紅。"""
    step8 = _section(skill_text, "Step 8")
    early = "Show the summary and hotspots to the user."
    real = f"bash ~/.agents/skills/pr-cycle-deep/scripts/{REMOVE} {{{{pr_number}}}}"
    assert step8.count(early) == 1 and step8.count(real) == 1, "anchor drifted"
    # 單一突變：把撤 label 的命令從「ship 之後」搬到「摘要給人看之前」。
    moved = step8.replace(real, "true").replace(early, f"{real}\n{early}")
    assert SHIP_ANCHOR in moved
    mutated = skill_text.replace(step8, moved)
    assert any("after the user replies" in p for p in check_label_contract(mutated))


# (id, heading, level, 區段內唯一的 anchor, 替換成, 預期出現的 problem 片段)
_EXIT_MUTATIONS = [
    (
        "step1-add",
        "Step 1 —",
        "###",
        "review-label.sh add {{pr_number}}",
        "review-label.sh noop {{pr_number}}",
        "Step 1 must add",
    ),
    (
        "step6-merged-row",
        "Step 6",
        "###",
        "skip re-review; run Step 1's `review-label.sh remove`",
        "skip re-review; run Step 1's `review-label.sh noop`",
        "Step 6 MERGED row",
    ),
    (
        "step6-closed-row",
        "Step 6",
        "###",
        "**STOP** — run Step 1's `review-label.sh remove`",
        "**STOP** — run Step 1's `review-label.sh noop`",
        "Step 6 CLOSED row",
    ),
    (
        "step10-gate",
        "Step 10",
        "###",
        "run Step 1's `review-label.sh remove` (a no-op",
        "run Step 1's `review-label.sh noop` (a no-op",
        "Step 10 gate",
    ),
    (
        "breaker-remove",
        "Circuit breaker",
        "####",
        "run Step 1's `review-label.sh remove {{pr_number}}`",
        "run Step 1's `review-label.sh noop {{pr_number}}`",
        "circuit breaker must remove",
    ),
    (
        "breaker-add",
        "Circuit breaker",
        "####",
        "review-label.sh add {{pr_number}}",
        "review-label.sh noop {{pr_number}}",
        "circuit breaker must re-add",
    ),
]

# AC-3 與 Stop／continue 語意：每個 anchor 各自一個突變。
_SEMANTIC_MUTATIONS = [
    (
        "step1-exit10-continue",
        "Step 1 —",
        "###",
        "| Continue; Step 8's summary MUST say",
        "| Proceed; Step 8's summary MUST say",
        "Step 1 exit 10 row",
    ),
    (
        "step1-exit10-step8-note",
        "Step 1 —",
        "###",
        "Step 8's summary MUST say",
        "Step 8's summary may say",
        "Step 1 exit 10 row",
    ),
    (
        "step1-other-stop",
        "Step 1 —",
        "###",
        "**Stop**; never run R1",
        "Halt; never run R1",
        "Step 1 other row",
    ),
    (
        "step8-no-mechanism",
        "Step 8",
        "###",
        NO_MECHANISM,
        "本 repo 沒有阻擋機制",
        "no-blocking-mechanism",
    ),
    (
        "step8-breaker-state",
        "Step 8",
        "###",
        "removed early by circuit breaker",
        "removed by something",
        "circuit-breaker-removed state",
    ),
    (
        "step8-no-continue-on-failure",
        "Step 8",
        "###",
        "do not continue to Step 9 until they confirm",
        "then continue to Step 9",
        "until the user confirms",
    ),
    (
        "breaker-false-positive-state",
        "Circuit breaker",
        "####",
        "label already off",
        "label state unspecified",
        "label already off",
    ),
    (
        "breaker-continue-uses-exit-table",
        "Circuit breaker",
        "####",
        "Step 1's exit table",
        "Step 1's table",
        "Step 1's exit table",
    ),
    (
        "breaker-no-resume-on-failure",
        "Circuit breaker",
        "####",
        "do not resume fixing",
        "resume fixing anyway",
        "do not resume fixing",
    ),
    (
        "breaker-redesign-state",
        "Circuit breaker",
        "####",
        "the label stays off",
        "the label may come back",
        "the label stays off",
    ),
]


@pytest.mark.parametrize(
    ("case_id", "heading", "level", "anchor", "replacement", "expected"),
    _EXIT_MUTATIONS + _SEMANTIC_MUTATIONS,
    ids=[m[0] for m in _EXIT_MUTATIONS + _SEMANTIC_MUTATIONS],
)
def test_mutation_breaking_one_exit_or_wording_turns_red(
    skill_text: str,
    case_id: str,
    heading: str,
    level: str,
    anchor: str,
    replacement: str,
    expected: str,
) -> None:
    """RLC-MT-004: 每個出口／語意 anchor 各自只改一處，檢查器必須轉紅且只為該理由轉紅。"""
    mutated = _mutate_once(skill_text, heading, level, anchor, replacement)
    problems = check_label_contract(mutated)
    assert any(expected in p for p in problems), (case_id, problems)
    # 單一突變只該踩到一條規則：其餘規則不能一起被連帶打紅，否則是為錯的理由轉紅。
    assert len(problems) == 1, (case_id, problems)


def test_script_is_referenced_by_exact_installed_path(skill_text: str) -> None:
    """RLC-ST-002: SKILL.md 引用的 script 真的存在，路徑用安裝版絕對形式。"""
    assert (SKILL_MD.parent / "scripts" / "review-label.sh").is_file()
    assert "~/.agents/skills/pr-cycle-deep/scripts/review-label.sh" in skill_text

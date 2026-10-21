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


def _section(text: str, heading: str, level: str = "###") -> str:
    """回傳 `heading` 起到下一個 step（`#### ` 層級則到下一個 `#### `）標題之前的內容。

    終點刻意只認 `### Step ` / `#### `，不認一般的 `#`：SKILL.md 的 code fence 內有
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


def check_label_contract(text: str) -> list[str]:
    """回傳違反時序契約的條目；空 list 代表符合。"""
    problems: list[str] = []
    step1 = _section(text, "Step 1 —")
    step5b = _section(text, "Step 5b")
    step6 = _section(text, "Step 6")
    step8 = _section(text, "Step 8")
    breaker = _section(text, "Circuit breaker", level="####")

    if ADD not in step1:
        problems.append("Step 1 must add the label")
    for name, body in (("Step 5b", step5b),):
        if REMOVE in body or GH_REMOVE in body:
            problems.append(f"{name} must not remove the label (fixes are not done yet)")
    if REMOVE not in step8:
        problems.append("Step 8 must remove the label")
    else:
        ship_at = step8.find(SHIP_ANCHOR)
        remove_at = step8.find(REMOVE)
        if ship_at == -1 or remove_at < ship_at:
            problems.append('Step 8 must remove the label after the user replies "ship"')
    if REMOVE not in breaker:
        problems.append("circuit breaker must remove the label")
    if REMOVE not in step6:
        problems.append("Step 6 MERGED/CLOSED exits must remove the label")
    return problems


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_real_skill_satisfies_contract(skill_text: str) -> None:
    """RLC-ST-001: 真實 SKILL.md 符合契約。"""
    assert check_label_contract(skill_text) == []


def test_mutation_remove_moved_into_step_5b_turns_red(skill_text: str) -> None:
    """RLC-MT-001: 把撤 label 移回 Step 5b（#2449 的失敗形狀）必須轉紅。"""
    anchor = "Do **not** touch the `review-in-progress` label here"
    assert skill_text.count(anchor) == 1, "anchor drifted; update the mutation"
    mutated = skill_text.replace(anchor, f"`bash x/{REMOVE} 1` {anchor}")
    problems = check_label_contract(mutated)
    assert any("Step 5b must not remove" in p for p in problems), problems


def test_mutation_missing_step_8_remove_turns_red(skill_text: str) -> None:
    """RLC-MT-002: Step 8 沒有撤 label 必須轉紅（fail-closed 方向也要有出口）。"""
    step8 = _section(skill_text, "Step 8")
    assert step8.count(REMOVE) == 1, "anchor drifted; update the mutation"
    mutated = skill_text.replace(step8, step8.replace(REMOVE, "review-label.sh noop"))
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


@pytest.mark.parametrize(
    ("what", "needle", "expected"),
    [
        ("Step 1 add", ADD, "Step 1 must add the label"),
        (
            "circuit breaker remove",
            "Before showing this prompt, run Step 1's `review-label.sh remove",
            "circuit breaker",
        ),
        (
            "Step 6 table remove",
            "run Step 1's `review-label.sh remove` and tell the user",
            "Step 6",
        ),
    ],
)
def test_mutation_dropping_each_exit_turns_red(
    skill_text: str, what: str, needle: str, expected: str
) -> None:
    """RLC-MT-004: 逐一拿掉 add／各個撤 label 出口，檢查器必須各自轉紅（每次只改一處）。"""
    assert needle in skill_text, f"anchor drifted for {what}"
    # 只改出口所在區段內的字串，避免別處同名片段造成「為錯的理由轉紅」。
    section = {
        "Step 1 add": _section(skill_text, "Step 1 —"),
        "circuit breaker remove": _section(skill_text, "Circuit breaker", level="####"),
        "Step 6 table remove": _section(skill_text, "Step 6"),
    }[what]
    broken = section.replace(ADD if "add" in what else REMOVE, "review-label.sh noop")
    assert broken != section
    mutated = skill_text.replace(section, broken)
    assert any(expected in p for p in check_label_contract(mutated)), what


def test_script_is_referenced_by_exact_installed_path(skill_text: str) -> None:
    """RLC-ST-002: SKILL.md 引用的 script 真的存在，路徑用安裝版絕對形式。"""
    assert (SKILL_MD.parent / "scripts" / "review-label.sh").is_file()
    assert "~/.agents/skills/pr-cycle-deep/scripts/review-label.sh" in skill_text

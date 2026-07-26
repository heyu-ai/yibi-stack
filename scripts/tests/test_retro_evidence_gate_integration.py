"""retro-evidence-gate 的 runbook / CI wiring contract tests。"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lint_rule_evidence  # noqa: E402


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runbook_defers_typed_lesson_mutation_until_after_evidence_gate():
    skill = _read("plugins/pr-flow/skills/pr-retrospective/SKILL.md")

    preparation = skill.index("### Step 4b — 準備 typed-lessons 寫入")
    no_execute = skill.index("此處只準備 metadata 與 script，不得執行", preparation)
    evidence_gate = skill.index("#### Step 5.0 Evidence Gate", no_execute)
    promotion_gate = skill.index("#### Promotion Gate", evidence_gate)

    assert preparation < no_execute < evidence_gate < promotion_gate


def test_runbook_uses_executable_park_and_reassessment_contract():
    skill = _read("plugins/pr-flow/skills/pr-retrospective/SKILL.md")

    assert "mycelium lessons add --park" in skill
    assert "status=parked recurrence=<n>" in skill
    assert "status=reassess recurrence=<n>" in skill
    assert "只重套 parked、不再次 bump recurrence" in skill
    assert "--tag parked" not in skill


def test_ci_fetches_history_and_runs_explicit_range_mode():
    workflow = _read(".github/workflows/ci.yml")

    assert "fetch-depth: 0" in workflow
    assert "Evidence lint against pull request range" in workflow
    assert '--base "${{ github.event.pull_request.base.sha }}"' in workflow
    assert '--head "${{ github.event.pull_request.head.sha }}"' in workflow


# --- drift guard：workflow 傳的 flag 必須是 script 真的認得的 flag ---
#
# 上面那條測試只斷言 YAML 檔案裡有這些字串——它驗證的是「我有沒有把這行字寫進去」，
# 不是「這個介面存在嗎」。PR #347 就是這樣本機全綠而 CI 紅：workflow 傳 `--base`/`--head`，
# 但腳本當時只吃 positional diff 檔，`--base` 被當成檔名 -> exit 2。
# 下面兩條把呼叫端與實作端綁在一起，任一端改名都會紅。

_EVIDENCE_LINT_FLAG_RE = re.compile(r"(--[a-z][a-z0-9-]*)")


def _workflow_evidence_lint_flags() -> set[str]:
    """從 ci.yml 中呼叫 lint_rule_evidence.py 的 run 區塊抽出實際傳遞的長選項。"""
    workflow = _read(".github/workflows/ci.yml")
    flags: set[str] = set()
    for block in workflow.split("- name:"):
        if "lint_rule_evidence.py" not in block:
            continue
        flags.update(_EVIDENCE_LINT_FLAG_RE.findall(block))
    return flags


def test_workflow_passes_flags_the_script_actually_parses():
    flags = _workflow_evidence_lint_flags()
    assert flags, "在 ci.yml 找不到 lint_rule_evidence.py 的呼叫——錨點失效，本測試等於沒跑"

    for flag in sorted(flags):
        # 每個 flag 都給一個佔位值，確認 parser 不把它當成未知選項。
        try:
            lint_rule_evidence._parse_args([flag, "PLACEHOLDER"])
        except ValueError as e:
            assert "未知選項" not in str(e), (
                f"ci.yml 傳了 {flag}，但 scripts/lint_rule_evidence.py 不認得這個選項"
            )


def test_workflow_full_invocation_shape_is_accepted():
    """完整的 CI 呼叫形狀（base+head 一起給）必須被 parser 接受為 range 模式。"""
    flags = _workflow_evidence_lint_flags()
    assert {"--base", "--head"} <= flags

    base, head, diff_file = lint_rule_evidence._parse_args(
        ["--base", "aaaaaaa", "--head", "bbbbbbb"]
    )
    assert (base, head, diff_file) == ("aaaaaaa", "bbbbbbb", None)


def test_drift_guard_itself_rejects_an_unknown_flag():
    """正向對照：guard 必須對「script 不認得的 flag」真的抛錯，否則上面兩條沒有資訊量。"""
    with pytest.raises(ValueError, match="未知選項"):
        lint_rule_evidence._parse_args(["--not-a-real-flag", "x"])

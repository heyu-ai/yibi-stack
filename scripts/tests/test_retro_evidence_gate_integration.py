"""retro-evidence-gate 的 runbook / CI wiring contract tests。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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

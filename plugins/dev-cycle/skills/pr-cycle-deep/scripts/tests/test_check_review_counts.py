"""彙整 gate 的遺漏、重複、合併與錯誤輸入行為。"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_review_counts.py"


def _run(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), "--review-dir", str(directory)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _accepted(directory: Path, count: int) -> None:
    (directory / "code-review-filtered.json").write_text(
        json.dumps(
            {
                "verdict": "NEEDS_CHANGES" if count else "LGTM",
                "summary": "Review completed",
                "findings": [{"file": f"src/{index}.py"} for index in range(count)],
            }
        ),
        encoding="utf-8",
    )


def test_merged_deferred_and_withdrawn_sources_are_accounted_for(tmp_path: Path) -> None:
    _accepted(tmp_path, 4)
    (tmp_path / "final.md").write_text(
        "## Consensus Important\n1. 合併兩個來源的缺陷\n"
        "   - Code-review source: CR-1, CR-2\n"
        "## Deferred for lack of evidence\n1. 無法重現\n- Code-review source: CR-3\n"
        "## Withdrawn\n1. reviewer 撤回，因條件不成立\n- Code-review source: CR-4\n"
        "## Actionable NIT\n1. 其他 voice 的建議\n",
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accepted=4 listed=4" in result.stdout


@pytest.mark.parametrize(
    ("sources", "diagnostic"),
    [
        ("CR-1", "missing=['CR-2']"),
        ("CR-1, CR-1", "duplicates=['CR-1']"),
        ("CR-1, CR-3", "unexpected=['CR-3']"),
        ("CR-1, CR-2, CR-2", "duplicates=['CR-2']"),
    ],
)
def test_missing_duplicate_and_unknown_sources_block(
    tmp_path: Path, sources: str, diagnostic: str
) -> None:
    _accepted(tmp_path, 2)
    (tmp_path / "final.md").write_text(
        f"## Consensus Important\n1. finding\n- Code-review source: {sources}\n",
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert diagnostic in result.stderr


@pytest.mark.parametrize(
    "decoy",
    [
        "```text\n- Code-review source: CR-1\n```\n",
        "~~~~text\n- Code-review source: CR-1\n~~~~\n",
        "<!-- code-review-scope:start -->\n- Code-review source: CR-1\n"
        "<!-- code-review-scope:end -->\n",
        "accepted=1 listed=1\n",
    ],
)
def test_examples_audit_and_summary_do_not_replace_a_finding(tmp_path: Path, decoy: str) -> None:
    _accepted(tmp_path, 1)
    (tmp_path / "final.md").write_text(f"# Final\n{decoy}", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "accepted=1 listed=0" in result.stderr


def test_zero_findings_requires_valid_artifacts(tmp_path: Path) -> None:
    _accepted(tmp_path, 0)
    final = tmp_path / "final.md"
    final.write_text("# Final\nNo findings.\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accepted=0 listed=0" in result.stdout
    final.unlink()
    assert _run(tmp_path).returncode == 2


@pytest.mark.parametrize(
    "broken",
    [
        "missing-json",
        "invalid-json",
        "invalid-envelope",
        "empty-final",
        "bad-source",
        "bad-fence",
        "bad-audit",
    ],
)
def test_invalid_inputs_fail_closed(tmp_path: Path, broken: str) -> None:
    _accepted(tmp_path, 0)
    accepted = tmp_path / "code-review-filtered.json"
    final = tmp_path / "final.md"
    final.write_text("# Final\nNo findings.\n", encoding="utf-8")
    if broken == "missing-json":
        accepted.unlink()
    elif broken == "invalid-json":
        accepted.write_text("{", encoding="utf-8")
    elif broken == "invalid-envelope":
        accepted.write_text('{"findings": null}', encoding="utf-8")
    else:
        final.write_text(
            {
                "empty-final": " \n",
                "bad-source": "- Code-review source: CR-0\n",
                "bad-fence": "```text\nNo findings\n",
                "bad-audit": "<!-- code-review-scope:start -->\n",
            }[broken],
            encoding="utf-8",
        )
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "[FAIL]" in result.stderr

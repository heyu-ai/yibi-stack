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
        ("CR-1, CR-2, CR-3", "unexpected=['CR-3']"),
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
        "<!--\n- Code-review source: CR-1\n-->\n",
        "    - Code-review source: CR-1\n",
        "1. Example:\n\n       - Code-review source: CR-1\n",
        "- Example:\n    ```text\n  - Code-review source: CR-1\n    ```\n",
        "- ```text\n  - Code-review source: CR-1\n  ```\n",
        "~~~\n```\n- Code-review source: CR-1\n```\n~~~\n",
        "````\n```\n- Code-review source: CR-1\n```\n````\n",
        "```\n```text\n- Code-review source: CR-1\n```\n",
        "- - -\n\n    - Code-review source: CR-1\n",
        "  <!-- code-review-scope:start --> \t\n- Code-review source: CR-1\n"
        " <!-- code-review-scope:end -->  \n",
        "<div>\n- Code-review source: CR-1\n</div>\n",
        "`- Code-review source: CR-1`\n",
        "<!-- outer comment\n<!-- code-review-scope:start -->\n"
        "```text\n- Code-review source: CR-1\n```\n",
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


@pytest.mark.parametrize("indent", ["    ", "\t"])
def test_multidigit_list_sources_use_container_relative_indentation(
    tmp_path: Path, indent: str
) -> None:
    _accepted(tmp_path, 1)
    (tmp_path / "final.md").write_text(
        f"# Final\n10. finding\n{indent}- Code-review source: CR-1\n", encoding="utf-8"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accepted=1 listed=1" in result.stdout


def test_extra_source_blocks_when_no_findings_were_accepted(tmp_path: Path) -> None:
    _accepted(tmp_path, 0)
    (tmp_path / "final.md").write_text("# Final\n- Code-review source: CR-1\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "unexpected=['CR-1']" in result.stderr


@pytest.mark.parametrize(
    "malformed",
    [
        "- Code-review source : CR-1",
        "* Code-review source: CR-1",
        "- **Code-review source:** CR-1",
        "- code-review source： CR-1",
        "+ Code-review source: CR-1",
        "1. Code-review source: CR-1",
        "- code-review source: CR-1",
        "- Code-review  source: CR-1",
        "- Code-review source: CR-01",
        "- Code-review source:",
        "- Code-review source: CR-1,CR-2",
        "- Code-review source: CR-1, CR-2 trailing prose",
        "- [Code-review source:](https://example.com) CR-1",
        "- Code-review source: `CR-1`",
        "\nCode-review source: CR-1",
        "# Code-review source: CR-1",
        "\n> Code-review source: CR-1",
        "- finding\n  Code-review source: CR-1",
        "- finding\n\n  Code-review source: CR-1",
        "- Code-review source: CR-1,\n  CR-2",
    ],
)
def test_malformed_extra_source_cannot_hide_behind_complete_coverage(
    tmp_path: Path, malformed: str
) -> None:
    _accepted(tmp_path, 1)
    (tmp_path / "final.md").write_text(
        f"# Final\n- Code-review source: CR-1\n{malformed}\n", encoding="utf-8"
    )
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "來源列格式錯誤" in result.stderr


@pytest.mark.parametrize(
    "evidence",
    [
        "```foo```\n",
        "`<!-- code-review-scope:start -->`\n",
        "```text\n<!-- code-review-scope:start -->\n```\n",
    ],
)
def test_literal_evidence_does_not_become_a_fence_or_audit_boundary(
    tmp_path: Path, evidence: str
) -> None:
    _accepted(tmp_path, 1)
    (tmp_path / "final.md").write_text(
        "# Final\n" + evidence + "1. finding\n   - Code-review source: CR-1\n"
        "<!-- code-review-scope:start -->\n## Code-review scope audit\n"
        "<!-- code-review-scope:end -->\n",
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accepted=1 listed=1" in result.stdout


@pytest.mark.parametrize(
    "broken_structure",
    [
        "<!-- code-review-scope:end -->\n",
        "<!-- code-review-scope:end -->\n<!-- code-review-scope:start -->\n",
        "<!-- code-review-scope:start -->\n<!-- code-review-scope:end -->\n"
        "<!-- code-review-scope:start -->\n<!-- code-review-scope:end -->\n",
        "<!-- code-review-scope:start -->\n```text\n<!-- code-review-scope:end -->\n",
        "<!--\n- Code-review source: CR-1\n",
        "  <!-- code-review-scope:start --> \t\n",
        "  <!-- code-review-scope:end --> \t\n",
        " <!-- code-review-scope:start -->\n <!-- code-review-scope:end -->\n"
        " <!-- code-review-scope:start -->\n <!-- code-review-scope:end -->\n",
        "<!-- code-review-scope:start -->\n<!-- unfinished comment\n",
        "<!-- code-review-scope:start -->\n- Code-review source: CR-0\n"
        "<!-- code-review-scope:end -->\n",
        "<!-- code-review-scope:start -->\n- Code-review source : CR-1\n"
        "<!-- code-review-scope:end -->\n",
        "- x\n  ~~~\n```\n  ~~~\n- Code-review source: CR-1\n```\n```\n",
        "- x\n  ```\n# Outside container\n",
        "> ```\n> example\n\n# Outside quote\n",
    ],
)
def test_structure_is_validated_even_in_excluded_regions(
    tmp_path: Path, broken_structure: str
) -> None:
    _accepted(tmp_path, 0)
    (tmp_path / "final.md").write_text("# Final\n" + broken_structure, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "[FAIL] review-count" in result.stderr


@pytest.mark.parametrize(
    "body",
    [
        "1. 10. finding\n       - Code-review source: CR-1\n",
        "1. 10. finding\nlazy continuation of finding\n       - Code-review source: CR-1\n",
        "1. first level\n\n   10. second level\n       - third level\n"
        "         - Code-review source: CR-1\n",
        "\n    <!-- literal example\n\n- Code-review source: CR-1\n",
        "1. Unclosed `<!--` hides rows\n   - Code-review source: CR-1\n",
        "1. Escaped \\<!-- literal\n   - Code-review source: CR-1\n",
        "Note: <!--\n\n- Code-review source: CR-1\n",
        "1. Code-review source accounting must remain strict\n   - Code-review source: CR-1\n",
        "1. Code-review source accounting: details\n   - Code-review source: CR-1\n",
        "1. Evidence <!-- hidden --> remains visible\n   - Code-review source: CR-1\n",
        "1. Evidence `<!-- code-review-scope:end -->` remains literal\n"
        "   - Code-review source: CR-1\n",
        "\n    <!-- code-review-scope:start -->\n\n- Code-review source: CR-1\n",
        "```text\n<!-- literal opener\n```\n- Code-review source: CR-1\n",
        "~~~text\nsample\n~~~~~ \t\n- Code-review source: CR-1\n",
        "> ```text\n> sample\n> ```\n\n- Code-review source: CR-1\n",
        "- finding\n  ```text\n  sample\n  ```\n  - Code-review source: CR-1\n",
    ],
)
def test_commonmark_containers_and_literal_contexts_preserve_real_sources(
    tmp_path: Path, body: str
) -> None:
    _accepted(tmp_path, 1)
    (tmp_path / "final.md").write_text("# Final\n" + body, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accepted=1 listed=1" in result.stdout


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_padded_audit_excludes_only_owned_sources(tmp_path: Path, newline: str) -> None:
    _accepted(tmp_path, 2)
    text = (
        "# Final\n- Code-review source: CR-1\n"
        "  <!-- code-review-scope:start --> \t\n"
        "- Code-review source: CR-99, CR-99\n"
        "```text\n<!-- code-review-scope:end -->\n```\n"
        " <!-- code-review-scope:end -->  \n"
        "- Code-review source: CR-2"
    )
    (tmp_path / "final.md").write_bytes(text.replace("\n", newline).encode("utf-8"))
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accepted=2 listed=2" in result.stdout


@pytest.mark.parametrize(
    "body",
    [
        "Code-review source accounting is a title, not a field.\n",
        "1. Code-review source accounting: no admitted findings\n",
        "`Code-review source: CR-1`\n",
        "- `Code-review source: CR-1`\n",
        "Note: <!--\n",
        "<!-- ordinary closed comment -->\n",
        "```\n```\n",
        "~~~\n~~~",
    ],
)
def test_zero_findings_accepts_nonfields_and_closed_empty_fences(tmp_path: Path, body: str) -> None:
    _accepted(tmp_path, 0)
    (tmp_path / "final.md").write_text("# Final\n" + body, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "accepted=0 listed=0" in result.stdout


def test_parser_depth_limit_never_hides_unknown_sources(tmp_path: Path) -> None:
    _accepted(tmp_path, 0)
    (tmp_path / "final.md").write_text(
        "# Final\n" + "- " * 64 + "Code-review source: CR-1\n", encoding="utf-8"
    )
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "巢狀層級" in result.stderr


@pytest.mark.parametrize(
    ("entrypoint", "expected_exit"),
    [("check_review_counts.py", 2), ("review_scope.py", 1)],
)
def test_missing_script_lock_stops_before_accepting_or_resetting(
    tmp_path: Path, entrypoint: str, expected_exit: int
) -> None:
    for name in ("check_review_counts.py", "review_scope.py", "review_markdown.py"):
        (tmp_path / name).write_bytes((SCRIPT.parent / name).read_bytes())
    directory = tmp_path / ".pr-review"
    directory.mkdir()
    _accepted(directory, 0)
    (directory / "final.md").write_text("# Final\nNo findings.\n", encoding="utf-8")
    accepted_before = (directory / "code-review-filtered.json").read_bytes()
    subprocess.run(  # nosec B603 B607
        ["git", "init", "-q", str(tmp_path)], check=True, capture_output=True, timeout=10
    )
    args = ["--review-dir", str(directory)] if entrypoint == SCRIPT.name else ["reset"]
    result = subprocess.run(  # nosec B603
        [sys.executable, str(tmp_path / entrypoint), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == expected_exit
    assert "lockfile" in result.stderr
    assert (directory / "code-review-filtered.json").read_bytes() == accepted_before

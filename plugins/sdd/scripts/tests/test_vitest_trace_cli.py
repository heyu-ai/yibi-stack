"""Real CLI coverage for Vitest discovery, bindings, and fail-closed prerequisites."""

from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest
from check_testplan_trace import discover_test_files, parse_bindings

SCRIPT = Path(__file__).resolve().parents[1] / "check_testplan_trace.py"
PLAN = """trace: enforced

| TC-ID | Kind | Test Purpose | Expected Result |
|---|---|---|---|
| UI-VL-001 | auto | close player | stopped |
| UI-VL-002 | auto | menu above player | reachable |

## Coverage Analysis

| Scenario slug | TC-ID(s) |
|---|---|
| close-player | UI-VL-001 |
| menu-access | UI-VL-002 |
"""
SOURCE = """import { describe, it, test as check } from 'vitest';
describe('player', () => {
  it.each(['playing', 'paused'])('closes %s', async (state) => {
    // spec: player#close-player
    // tc: UI-VL-001
    const view = <button>{state}</button>;
    expect(view).toBeDefined();
  });
  check('menu is reachable', () => {
    /* spec: player#menu-access
       tc: UI-VL-002 */
    expect(true).toBe(true);
  });
});
"""


def _write(root: Path, relative: str, text: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _repo(root: Path, source: str = SOURCE) -> Path:
    _write(root, "docs/openspec/changes/player/testplan.md", PLAN)
    _write(root, "ui/Player.test.tsx", source)
    return root


def _run(root: Path, *args: str, environment: dict[str, str] | None = None):
    return subprocess.run(  # nosec B603
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(root),
            "--openspec-dir",
            "docs/openspec",
            "--change",
            "player",
            "--strict",
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=environment,
    )


def test_real_tsx_each_and_alias_bind_through_public_cli(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = _run(repo)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout == ""
    report = _run(repo, "--report")
    assert report.returncode == 0, report.stderr
    rows = report.stdout.splitlines()[1:]
    assert len(rows) == 2
    assert rows[0].startswith(
        "player\tUI-VL-001\tauto\tbound\tui/Player.test.tsx::player::closes %s@"
    )
    assert rows[1].startswith(
        "player\tUI-VL-002\tauto\tbound\tui/Player.test.tsx::player::menu is reachable@"
    )


@pytest.mark.parametrize(
    ("source", "finding"),
    [
        (SOURCE.replace("// tc: UI-VL-001", "// no binding"), "missing: player UI-VL-001"),
        (SOURCE.replace("player#close-player", "player#wrong-slug"), "mismatch: player UI-VL-001"),
        (
            'const data = "tc: UI-VL-001";\n// tc: UI-VL-002\n',
            "missing: player UI-VL-001",
        ),
        (SOURCE.replace("it.each(", "it.skip.each("), "missing: player UI-VL-001"),
    ],
)
def test_invalid_or_nonexecuting_binding_cannot_pass(
    tmp_path: Path, source: str, finding: str
) -> None:
    result = _run(_repo(tmp_path, source))
    assert result.returncode == 1, result.stderr + result.stdout
    assert f"[FAIL] {finding}" in result.stdout


def test_syntax_failure_is_not_a_missing_test(tmp_path: Path) -> None:
    result = _run(_repo(tmp_path, SOURCE + "const = ;\n"))
    assert result.returncode == 2
    assert "語法錯誤" in result.stderr
    assert "missing:" not in result.stdout


def test_missing_node_is_config_failure_only_when_vitest_files_exist(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    environment = {**os.environ, "PATH": ""}
    result = _run(repo, environment=environment)
    assert result.returncode == 2
    assert "Node.js" in result.stderr
    assert "missing:" not in result.stdout

    (repo / "ui/Player.test.tsx").unlink()
    _write(
        repo,
        "tests/test_player.py",
        'def test_player():\n    """tc: UI-VL-001, UI-VL-002\n'
        '    spec: player#close-player\n    spec: player#menu-access\n    """\n',
    )
    python_only = _run(repo, environment=environment)
    assert python_only.returncode == 0, python_only.stderr + python_only.stdout


def test_discovery_prunes_dependencies_and_deduplicates_overlapping_roots(tmp_path: Path) -> None:
    actual = _write(tmp_path, "ui/Player.test.tsx", SOURCE)
    _write(tmp_path, "ui/Player.tsx", SOURCE)
    _write(tmp_path, "node_modules/demo/Hidden.test.tsx", SOURCE)
    _write(tmp_path, ".claude/worktrees/other/Hidden.test.tsx", SOURCE)
    _write(tmp_path, ".venv/Hidden.spec.ts", SOURCE)
    found = discover_test_files([tmp_path, tmp_path / "ui", actual])
    assert found == [actual]
    bindings = parse_bindings(actual, tmp_path)
    assert [binding.tc_ids for binding in bindings] == [("UI-VL-001",), ("UI-VL-002",)]


def test_foreign_active_plan_is_ownership_context_not_selected_noise(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(
        repo,
        "docs/openspec/changes/other/testplan.md",
        PLAN.replace("UI-VL-", "OTHER-VL-").replace("close-player", "other-close"),
    )
    _write(repo, "ui/Other.test.tsx", SOURCE.replace("UI-VL-", "OTHER-VL-"))
    result = _run(repo)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout == ""

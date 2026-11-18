"""Execute shipped lesson commands against isolated SQLite and external CLI boundaries."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/growth/skills/pr-retrospective"
RUNTIME = SKILL / "scripts/retro-lessons.py"
INSIGHT = "A $HSP_UNSET_VARIABLE and $(printf SHOULD_NOT_RUN) must remain literal."
PROJECT = "runtime-payments"
KEY = "runtime-shell-safety"


def _render(state: str) -> str:
    """Execute the published example, substituting only the invocation's inputs."""
    blocks = re.findall(
        r"```bash\n(.*?)```", (SKILL / "SKILL.md").read_text(encoding="utf-8"), re.S
    )
    script = next(block for block in blocks if "add_lesson()" in block)
    script = script.replace('PR_NUMBER="<from Step 0>"', 'PR_NUMBER="42"')
    script = script.replace('ORIG_PROJECT="<from Step 0>"', f'ORIG_PROJECT="{PROJECT}"')
    script = script.replace('RETRO_ID="<id from Step 4 output>"', 'RETRO_ID="runtime-retro"')
    script = script.replace(
        'RETRO_ROOT="<resolved skill directory from Step 0>"', f'RETRO_ROOT="{SKILL}"'
    )
    values = [KEY, "pitfall", INSIGHT, "4" if state == "park" else "8", "observed", "", state]
    for placeholder, value in zip(re.findall(r"\{\{[^\n]*?\}\}", script), values, strict=True):
        script = script.replace(placeholder, value)
    return script


@pytest.fixture
def runtime(tmp_path):
    """Use the actual installed entrypoint, never a project-module mock."""
    bindir = Path(sys.executable).parent
    executable = bindir / "mycelium"
    if not executable.is_file():
        pytest.fail("測試環境未安裝 mycelium entrypoint，請先執行 uv sync")
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "unrelated-session-repo"
    cwd.mkdir()
    subprocess.run(  # nosec B603 B607
        ["git", "init", "-q", str(cwd)], check=True, capture_output=True, timeout=20
    )
    database = tmp_path / "lessons.db"
    env = dict(
        os.environ,
        HOME=str(home),
        MYCELIUM_DB_OVERRIDE=str(database),
        PATH=str(bindir) + os.pathsep + os.environ.get("PATH", os.defpath),
    )
    env.pop("HSP_UNSET_VARIABLE", None)
    return {"env": env, "db": database, "cwd": cwd, "cli": executable, "tmp": tmp_path}


def _run(runtime, *args):
    return subprocess.run(  # nosec B603
        [sys.executable, str(RUNTIME), *args],
        cwd=runtime["cwd"],
        env=runtime["env"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _add(runtime, state="active", *, retrospective_id="runtime-retro", insight=INSIGHT):
    return _run(
        runtime,
        "add",
        "--project",
        PROJECT,
        "--key",
        KEY,
        "--type",
        "pitfall",
        "--insight",
        insight,
        "--confidence",
        "4" if state == "park" else "8",
        "--source",
        "observed",
        "--retro-pr",
        "42",
        "--retrospective-id",
        retrospective_id,
        "--state",
        state,
    )


def _rows(runtime):
    with sqlite3.connect(runtime["db"]) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM lessons")]


def _boundary(runtime, body):
    """Replace only the external executable; real row queries still use real SQLite."""
    directory = runtime["tmp"] / "boundary"
    directory.mkdir()
    executable = directory / "mycelium"
    executable.write_text(
        f"#!{sys.executable}\nimport json, os, subprocess, sys\n"
        f"REAL = {str(runtime['cli'])!r}\n" + body,
        encoding="utf-8",
    )
    executable.chmod(0o755)
    runtime["env"]["PATH"] = str(directory) + os.pathsep + runtime["env"]["PATH"]


def test_hsp_st_020_active_replay_preserves_literal_insight(runtime):
    """tc: HSP-ST-020
    spec: retro-hindsight-projection#legacy-lesson-write-safety
    """
    script = runtime["tmp"] / "lesson.sh"
    script.write_text(_render("active"), encoding="utf-8")
    for _ in range(2):
        result = subprocess.run(  # nosec B603
            ["/bin/bash", str(script)],
            cwd=runtime["cwd"],
            env=runtime["env"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    rows = _rows(runtime)
    assert len(rows) == 1
    assert (rows[0]["project"], rows[0]["key"], rows[0]["insight"], rows[0]["confidence"]) == (
        PROJECT,
        KEY,
        INSIGHT,
        8,
    )
    assert json.loads(rows[0]["tags"]) == []
    assert f"verified_id={rows[0]['id']}" in result.stdout


def test_hsp_st_021_park_path_preserves_inactive_state(runtime):
    """tc: HSP-ST-021
    spec: retro-hindsight-projection#legacy-lesson-write-safety
    """
    result = _add(runtime, "park")
    assert result.returncode == 0, result.stderr
    (row,) = _rows(runtime)
    assert (row["project"], row["key"], row["insight"], row["confidence"]) == (
        PROJECT,
        KEY,
        INSIGHT,
        4,
    )
    assert set(json.loads(row["tags"])) == {"parked", "recurrence-1"}
    assert f"verified_id={row['id']}" in result.stdout
    assert "status=parked recurrence=1" in result.stdout


@pytest.mark.parametrize("existing_state", ["active", "park", "retired"])
def test_skip_returns_existing_id_without_requiring_current_retro(runtime, existing_state):
    first = _add(
        runtime,
        "park" if existing_state == "park" else "active",
        retrospective_id="earlier-retro",
        insight="Already canonical.",
    )
    assert first.returncode == 0, first.stderr
    if existing_state == "retired":
        lesson_id = _rows(runtime)[0]["id"]
        retired = subprocess.run(  # nosec B603
            [str(runtime["cli"]), "lessons", "retire", "--id", lesson_id, "--reason", "old event"],
            env=runtime["env"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert retired.returncode == 0, retired.stderr
    (old,) = _rows(runtime)
    result = _add(runtime)
    assert result.returncode == 0, result.stderr
    assert f"verified_id={old['id']}" in result.stdout
    assert _rows(runtime) == [old]


@pytest.mark.parametrize("history", ["parked", "retired"])
def test_same_key_history_does_not_prove_missing_new_write(runtime, history):
    seed = _add(runtime, "park" if history == "parked" else "active")
    assert seed.returncode == 0, seed.stderr
    (old,) = _rows(runtime)
    if history == "retired":
        retired = subprocess.run(  # nosec B603
            [str(runtime["cli"]), "lessons", "retire", "--id", old["id"], "--reason", "old event"],
            env=runtime["env"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert retired.returncode == 0, retired.stderr
    _boundary(
        runtime,
        "if sys.argv[1:3] == ['lessons', 'add']:\n"
        "    print('id=never-persisted key=runtime-shell-safety trusted=False')\n"
        "    sys.exit(0)\n"
        "os.execv(REAL, [REAL, *sys.argv[1:]])\n",
    )
    result = _add(runtime)
    assert result.returncode == 1
    assert "verified_id=" not in result.stdout
    assert len(_rows(runtime)) == 1


@pytest.mark.parametrize("state", ["active", "park"])
def test_add_failure_is_immediate_and_preserves_external_exit(runtime, state):
    assert _add(runtime, "park").returncode == 0
    marker = runtime["tmp"] / "readback-ran"
    _boundary(
        runtime,
        "if sys.argv[1:3] == ['lessons', 'add']:\n"
        "    print('write rejected', file=sys.stderr)\n"
        "    sys.exit(7)\n"
        f"open({str(marker)!r}, 'w').write('unexpected readback')\n"
        "os.execv(REAL, [REAL, *sys.argv[1:]])\n",
    )
    result = _add(runtime, state)
    assert result.returncode == 7
    assert "write rejected" in result.stderr
    assert not marker.exists()
    (row,) = _rows(runtime)
    assert set(json.loads(row["tags"])) == {"parked", "recurrence-1"}


@pytest.mark.parametrize("corruption", ["id", "project", "key", "type", "json", "missing"])
def test_readback_must_match_exact_returned_identity(runtime, corruption):
    _boundary(
        runtime,
        "if sys.argv[1:3] != ['lessons', 'rows']:\n"
        "    os.execv(REAL, [REAL, *sys.argv[1:]])\n"
        "result = subprocess.run([REAL, *sys.argv[1:]], capture_output=True, text=True, timeout=20)\n"
        "data = json.loads(result.stdout)\n"
        f"corruption = {corruption!r}\n"
        "if corruption == 'json':\n"
        "    print('not JSON')\n"
        "elif corruption == 'missing':\n"
        "    data['missing_ids'] = [data['rows'][0]['id']]\n"
        "    print(json.dumps(data))\n"
        "else:\n"
        "    data['rows'][0][corruption] = 'different'\n"
        "    print(json.dumps(data))\n",
    )
    result = _add(runtime)
    assert result.returncode == 1
    assert "verified_id=" not in result.stdout
    assert len(_rows(runtime)) == 1  # Failed confirmation never replays a successful write.


@pytest.mark.parametrize("state", ["active", "park"])
def test_missing_add_identity_cannot_be_replaced_by_same_key_search(runtime, state):
    assert _add(runtime, "park").returncode == 0
    _boundary(
        runtime,
        "if sys.argv[1:3] == ['lessons', 'add']:\n"
        "    print('write apparently succeeded')\n"
        "    sys.exit(0)\n"
        "os.execv(REAL, [REAL, *sys.argv[1:]])\n",
    )
    result = _add(runtime, state)
    assert result.returncode == 1
    assert "verified_id=" not in result.stdout
    assert len(_rows(runtime)) == 1


@pytest.mark.parametrize(
    ("error", "stale"),
    [
        ("Error: --key 與 --id 合計最多 200 個", True),
        ("Error: No such command 'rows'.", True),
        ("Error: key 只能含英數字、底線、連字號", False),
    ],
)
def test_public_rows_diagnoses_stale_cli_without_blaming_valid_parameters(runtime, error, stale):
    _boundary(runtime, f"print({error!r}, file=sys.stderr)\nsys.exit(2)\n")
    command = ["rows", "--project", PROJECT]
    for number in range(201):
        command.extend(["--key", f"history-{number}"])
    result = _run(runtime, *command)
    assert result.returncode == 2
    assert error in result.stderr
    assert ("uv tool install --force" in result.stderr) is stale


@pytest.mark.parametrize("code", [2, 3])
def test_readback_failure_preserves_exit_and_never_retries_park(runtime, code):
    _boundary(
        runtime,
        "if sys.argv[1:3] == ['lessons', 'rows']:\n"
        "    print('readback unavailable', file=sys.stderr)\n"
        f"    sys.exit({code})\n"
        "os.execv(REAL, [REAL, *sys.argv[1:]])\n",
    )
    result = _add(runtime, "park")
    assert result.returncode == code
    assert "readback unavailable" in result.stderr
    (row,) = _rows(runtime)
    assert set(json.loads(row["tags"])) == {"parked", "recurrence-1"}
    assert "verified_id=" not in result.stdout


def test_runtime_keeps_actual_session_cwd_for_external_cli(runtime):
    observed = runtime["tmp"] / "observed-cwd"
    _boundary(
        runtime,
        f"open({str(observed)!r}, 'w').write(os.getcwd())\nos.execv(REAL, [REAL, *sys.argv[1:]])\n",
    )
    result = _add(runtime)
    assert result.returncode == 0, result.stderr
    assert observed.read_text() == str(runtime["cwd"])
    (row,) = _rows(runtime)
    assert row["project"] == PROJECT

"""執行出貨的 Step 4b Bash 範本，驗證 SQLite 狀態而非文件措辭。"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/growth/skills/pr-retrospective/SKILL.md"
INSIGHT = "A $HSP_UNSET_VARIABLE and $(printf SHOULD_NOT_RUN) must remain literal."


def _render(state: str) -> str:
    """只填入使用者在 Step 5 確認的值；範本本體直接取自出貨檔。"""
    blocks = re.findall(r"```bash\n(.*?)```", SKILL.read_text(encoding="utf-8"), re.S)
    script = next(block for block in blocks if "add_lesson()" in block)
    script = script.replace('PR_NUMBER="<from Step 0>"', 'PR_NUMBER="42"')
    script = script.replace('ORIG_PROJECT="<from Step 0>"', 'ORIG_PROJECT="runtime-payments"')
    script = script.replace('RETRO_ID="<id from Step 4 output>"', 'RETRO_ID="runtime-retro"')
    values = [
        "runtime-shell-safety",
        "pitfall",
        INSIGHT,
        "4" if state == "park" else "8",
        "observed",
        "",
        state,
    ]
    for placeholder, value in zip(re.findall(r"\{\{[^\n]*?\}\}", script), values, strict=True):
        script = script.replace(placeholder, value)
    return script


@pytest.fixture
def runtime(tmp_path):
    """隔離 HOME 與 DB；執行目前測試環境安裝的真正 mycelium CLI。"""
    bindir = Path(sys.executable).parent
    if not (bindir / "mycelium").is_file():
        pytest.fail("測試環境未安裝 mycelium entrypoint，請先執行 uv sync")
    home = tmp_path / "home"
    home.mkdir()
    database = tmp_path / "lessons.db"
    env = dict(
        os.environ,
        HOME=str(home),
        MYCELIUM_DB_OVERRIDE=str(database),
        PATH=str(bindir) + os.pathsep + os.environ.get("PATH", os.defpath),
    )
    env.pop("HSP_UNSET_VARIABLE", None)

    def execute(state):
        script = tmp_path / "lesson.sh"
        script.write_text(_render(state), encoding="utf-8")
        result = subprocess.run(
            ["/bin/bash", str(script)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        with sqlite3.connect(database) as db:
            return db.execute("SELECT project,key,insight,confidence,tags FROM lessons").fetchall()

    return execute


def test_hsp_st_020_active_replay_preserves_literal_insight(runtime):
    """tc: HSP-ST-020
    spec: retro-hindsight-projection#legacy-lesson-write-safety
    """
    runtime("active")
    rows = runtime("active")
    assert rows == [("runtime-payments", "runtime-shell-safety", INSIGHT, 8, "[]")]


def test_hsp_st_021_park_path_preserves_inactive_state(runtime):
    """tc: HSP-ST-021
    spec: retro-hindsight-projection#legacy-lesson-write-safety
    """
    rows = runtime("park")
    assert [
        (project, key, insight, confidence) for project, key, insight, confidence, _ in rows
    ] == [("runtime-payments", "runtime-shell-safety", INSIGHT, 4)]
    assert set(json.loads(rows[0][4])) == {"parked", "recurrence-1"}

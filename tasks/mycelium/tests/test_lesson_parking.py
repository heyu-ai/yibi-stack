"""Tier 3 lesson parking、recurrence 與 default exclusion 回歸測試。"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from tasks.mycelium.cli import cli
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.lessons_service import (
    park_lesson,
    show_lessons_typed,
)
from tasks.mycelium.tier_service import run_promotion_check


def _lesson(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "project": "yibi-stack",
        "type": "pitfall",
        "key": "cli-parked-friction",
        "insight": "Original title and description must remain unchanged.",
        "confidence": 4,
        "source": "inferred",
    }
    data.update(overrides)
    return data


def test_initial_park_persists_tags_and_confidence(tmp_path: Path):
    db_path = tmp_path / "lessons.db"
    result = park_lesson(_lesson(), db_path=db_path)

    assert result["status"] == "parked"
    assert result["recurrence"] == 1
    row = result["lesson"]
    assert row["confidence"] <= 4
    assert set(row["tags"]) >= {"parked", "recurrence-1"}


def test_second_occurrence_unparks_for_reassessment_and_preserves_text(tmp_path: Path):
    db_path = tmp_path / "lessons.db"
    first = park_lesson(_lesson(), db_path=db_path)
    second = park_lesson(
        _lesson(insight="A later summary must not overwrite the original."),
        db_path=db_path,
    )

    assert second["id"] == first["id"]
    assert second["status"] == "reassess"
    assert second["recurrence"] == 2
    assert "parked" not in second["lesson"]["tags"]
    assert second["lesson"]["insight"] == _lesson()["insight"]


def test_repark_after_failed_reassessment_does_not_double_bump(tmp_path: Path):
    db_path = tmp_path / "lessons.db"
    park_lesson(_lesson(), db_path=db_path)
    park_lesson(_lesson(), db_path=db_path)
    result = park_lesson(_lesson(), db_path=db_path)

    assert result["status"] == "parked"
    assert result["recurrence"] == 2
    assert set(result["lesson"]["tags"]) >= {"parked", "recurrence-2"}


def test_park_rejects_confidence_above_four(tmp_path: Path):
    with pytest.raises(ValueError, match="confidence"):
        park_lesson(_lesson(confidence=5), db_path=tmp_path / "lessons.db")


def test_normal_recall_excludes_parked_unless_explicitly_requested(tmp_path: Path):
    db_path = tmp_path / "lessons.db"
    park_lesson(_lesson(), db_path=db_path)

    assert (
        show_lessons_typed(
            project="yibi-stack",
            include_legacy=False,
            db_path=db_path,
        )
        == []
    )
    visible = show_lessons_typed(
        project="yibi-stack",
        include_legacy=False,
        include_parked=True,
        db_path=db_path,
    )
    assert len(visible) == 1
    assert "parked" in visible[0]["tags"]


def test_tier_promotion_skips_parked_lessons(tmp_path: Path):
    db_path = tmp_path / "lessons.db"
    parked = park_lesson(_lesson(), db_path=db_path)
    db = AgentsDB(db_path=db_path)
    db.init_db()
    db.conn.execute("UPDATE lessons SET access_count = 3 WHERE id = ?", (parked["id"],))
    db.conn.commit()
    db.close()

    result = run_promotion_check(db_path=db_path)

    assert result.promoted_to_hot == 0
    db = AgentsDB(db_path=db_path)
    db.init_db()
    row = db.get_lesson(str(parked["id"]))
    db.close()
    assert row is not None
    assert row["tier"] == "working"


def test_lessons_add_park_cli_is_executable(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "lessons.db"
    monkeypatch.setenv("MYCELIUM_DB_OVERRIDE", str(db_path))
    args = [
        "lessons",
        "add",
        "--type",
        "pitfall",
        "--key",
        "cli-parked-friction",
        "--insight",
        "Original title and description must remain unchanged.",
        "--confidence",
        "4",
        "--source",
        "inferred",
        "--project",
        "yibi-stack",
        "--park",
    ]

    first = CliRunner().invoke(cli, args, catch_exceptions=False)
    second = CliRunner().invoke(cli, args, catch_exceptions=False)

    assert first.exit_code == 0
    assert "status=parked recurrence=1" in first.output
    assert second.exit_code == 0
    assert "status=reassess recurrence=2" in second.output

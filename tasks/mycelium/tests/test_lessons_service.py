"""測試 lessons_service：show_lessons、search_lessons、add_lesson、_apply_decay 等。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tasks.mycelium.cli import cli
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.lessons_service import (
    _apply_decay,
    add_lesson,
    search_lessons,
    search_lessons_typed,
    show_lessons,
    show_lessons_typed,
)
from tasks.mycelium.models import HandoverRecord, LessonSource, LessonType, SessionType


def make_record(**overrides: object) -> HandoverRecord:
    defaults: dict[str, object] = {
        "id": "record-1",
        "timestamp": "2026-04-15T10:00:00+00:00",
        "operator": "howie",
        "session_type": SessionType.debug,
        "topic": "parser bug",
        "conversation_summary": "修了個 bug",
        "project": "ainization-skill",
    }
    return HandoverRecord.model_validate({**defaults, **overrides})


def make_db_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    db = AgentsDB(db_path=p)
    db.init_db()
    db.close()
    return p


def make_insights_file(tmp_path: Path, entries: list[dict[str, object]] | None = None) -> Path:
    path = tmp_path / "insights.jsonl"
    if entries:
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8",
        )
    return path


_SAMPLE_INSIGHT: dict[str, object] = {
    "id": "ins-1",
    "timestamp": "2026-04-15T11:00:00+00:00",
    "session_id": "sess-abc",
    "project": "ainization-skill",
    "working_dir": "/tmp",
    "branch": "main",
    "insight_text": "★ 這是一個洞察",
    "session_reason": "stop",
}


def make_lesson_data(**kwargs: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "project": "yibi-stack",
        "type": LessonType.pitfall,
        "key": "test-key",
        "insight": "AP2 hook blocks Unicode in bash heredoc; use Write tool + redirect",
        "confidence": 8,
        "source": LessonSource.observed,
    }
    return {**defaults, **kwargs}


class TestAddLesson:
    def test_lsn_st_001_add_and_roundtrip(self, tmp_path: Path) -> None:
        """LSN-ST-001: add_lesson 寫入後 query_lessons_typed 可取回相同記錄"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.close()

        result = add_lesson(make_lesson_data(), db_path=db_path)
        assert "id" in result
        assert result["trusted"] is False

        db = AgentsDB(db_path=db_path)
        db.init_db()
        rows = db.query_lessons_typed(project="yibi-stack")
        db.close()

        assert len(rows) == 1
        assert rows[0]["key"] == "test-key"
        assert rows[0]["type"] == "pitfall"

    def test_lsn_st_001_user_stated_returns_trusted_true(self, tmp_path: Path) -> None:
        """LSN-ST-001: user-stated source 回傳 trusted=True"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.close()

        result = add_lesson(make_lesson_data(source=LessonSource.user_stated), db_path=db_path)
        assert result["trusted"] is True


class TestApplyDecay:
    def _ts_ago(self, days: int) -> str:
        return (datetime.now(UTC) - timedelta(days=days)).isoformat()

    def test_lsn_st_002_observed_60_days_decays_by_2(self) -> None:
        """LSN-ST-002: observed confidence=8 存 60 天 -> effective=6"""
        ts = self._ts_ago(60)
        result = _apply_decay(8, "observed", ts)
        assert result == 6

    def test_lsn_st_003_user_stated_no_decay(self) -> None:
        """LSN-ST-003: user-stated confidence=9 存 90 天 -> 仍為 9"""
        ts = self._ts_ago(90)
        result = _apply_decay(9, "user-stated", ts)
        assert result == 9

    def test_lsn_st_003_cross_model_no_decay(self) -> None:
        """LSN-ST-003: cross-model 不衰減"""
        ts = self._ts_ago(120)
        result = _apply_decay(7, "cross-model", ts)
        assert result == 7

    def test_decay_floor_is_1(self) -> None:
        """decay 下限為 1（observed confidence=2, 90 天 -> 1）"""
        ts = self._ts_ago(90)
        result = _apply_decay(2, "observed", ts)
        assert result == 1

    def test_decay_inferred_30_days(self) -> None:
        """inferred confidence=5, 30 天 -> 4"""
        ts = self._ts_ago(30)
        result = _apply_decay(5, "inferred", ts)
        assert result == 4


class TestShowLessonsTyped:
    def _db_with_lesson(self, tmp_path: Path, **kwargs: object) -> Path:
        db_path = tmp_path / "test.db"
        add_lesson(make_lesson_data(**kwargs), db_path=db_path)
        return db_path

    def test_lsn_st_004_dedup_latest_winner(self, tmp_path: Path) -> None:
        """LSN-ST-004: 同 key+type 保留最新 ts"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.close()

        add_lesson(
            make_lesson_data(
                key="dedup-grain",
                ts="2026-01-01T00:00:00+00:00",
                insight="pathlib rglob does not follow symlinks; use os.walk(followlinks=True)",
                source=LessonSource.observed,
            ),
            db_path=db_path,
        )
        add_lesson(
            make_lesson_data(
                key="dedup-grain",
                ts="2026-06-01T00:00:00+00:00",
                insight="AP2 hook blocks Unicode in bash heredoc; use Write tool + redirect",
                source=LessonSource.observed,
            ),
            db_path=db_path,
        )

        rows = show_lessons_typed(project="yibi-stack", include_legacy=False, db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["key"] == "dedup-grain"
        assert (
            rows[0]["insight"]
            == "AP2 hook blocks Unicode in bash heredoc; use Write tool + redirect"
        )

    def test_lsn_st_005_cross_project_only_trusted(self, tmp_path: Path) -> None:
        """LSN-ST-005: cross_project=True 只回傳 trusted=True 記錄"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.close()

        add_lesson(
            make_lesson_data(project="proj-a", source=LessonSource.user_stated, key="k1"),
            db_path=db_path,
        )
        add_lesson(
            make_lesson_data(project="proj-b", source=LessonSource.observed, key="k2"),
            db_path=db_path,
        )

        rows = show_lessons_typed(cross_project=True, include_legacy=False, db_path=db_path)
        assert all(r["trusted"] for r in rows)
        keys = {r["key"] for r in rows}
        assert "k1" in keys
        assert "k2" not in keys

    def test_lsn_st_006_include_legacy_merges_handover_lessons(self, tmp_path: Path) -> None:
        """LSN-ST-006: include_legacy=True 合併 handovers.lessons_learned"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(
                project="yibi-stack",
                lessons_learned=["rg uses ERE not BRE; backslash-pipe is literal, not alternation"],
            )
        )
        db.close()

        rows = show_lessons_typed(project="yibi-stack", include_legacy=True, db_path=db_path)
        assert len(rows) >= 1
        insights = [r["insight"] for r in rows]
        assert any("rg" in i for i in insights)

    def test_lsn_eg_001_empty_typed_table_returns_legacy(self, tmp_path: Path) -> None:
        """LSN-EG-001: lessons table 為空 + include_legacy=True 時回傳 legacy"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(project="yibi-stack", lessons_learned=["some legacy lesson text here"])
        )
        db.close()

        rows = show_lessons_typed(project="yibi-stack", include_legacy=True, db_path=db_path)
        assert len(rows) >= 1

    def test_lsn_eg_002_legacy_rows_deduplicated(self, tmp_path: Path) -> None:
        """LSN-EG-002: 同 key+type 的 legacy rows 被 dedup"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        lesson_text = "identical lesson text that deduplicates correctly"
        db.insert_handover(
            make_record(id="h1", project="yibi-stack", lessons_learned=[lesson_text])
        )
        db.insert_handover(
            make_record(id="h2", project="yibi-stack", lessons_learned=[lesson_text])
        )
        db.close()

        rows = show_lessons_typed(project="yibi-stack", include_legacy=True, db_path=db_path)
        matching = [r for r in rows if lesson_text in r.get("insight", "")]
        assert len(matching) == 1


class TestBackwardCompat:
    def test_lsn_cv_001_show_lessons_returns_legacy_text(self, tmp_path: Path) -> None:
        """LSN-CV-001: show_lessons() 舊行為不變（仍回傳 legacy lessons_learned 內容）"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["nom 比 regex 穩"]))
        db.close()

        rows = show_lessons(db_path=db_path)
        assert len(rows) >= 1
        texts = [r["text"] for r in rows]
        assert any("nom" in t for t in texts)

    def test_lsn_cv_001_search_lessons_returns_matching(self, tmp_path: Path) -> None:
        """LSN-CV-001: search_lessons() 舊行為不變（仍搜尋 lessons_learned 文字）"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["always test edge cases thoroughly"]))
        db.close()

        rows = search_lessons(query="edge cases", db_path=db_path)
        assert len(rows) >= 1
        assert any("edge cases" in r["text"] for r in rows)


class TestShowLessons:
    def test_lesson_dt_001_empty_db_returns_empty(self, tmp_path: Path) -> None:
        """LESSON-DT-001：空 DB 回傳空 list。"""
        rows = show_lessons(db_path=make_db_path(tmp_path))
        assert rows == []

    def test_lesson_dt_002_returns_handover_lessons(self, tmp_path: Path) -> None:
        """LESSON-DT-002：有 lessons_learned 的 handover 記錄會被展開為個別項目。"""
        db = AgentsDB(db_path=make_db_path(tmp_path))
        db.init_db()
        db.insert_handover(
            make_record(lessons_learned=["nom 比 regex 穩", "always test edge cases"])
        )
        db.close()

        rows = show_lessons(db_path=tmp_path / "test.db")
        assert len(rows) == 2
        texts = [r["text"] for r in rows]
        assert "nom 比 regex 穩" in texts
        assert "always test edge cases" in texts
        assert all(r["source"] == "handover" for r in rows)

    def test_lesson_dt_003_project_filter(self, tmp_path: Path) -> None:
        """LESSON-DT-003：project 過濾只回傳匹配的教訓。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(id="a", project="proj-a", lessons_learned=["lesson a"]))
        db.insert_handover(make_record(id="b", project="proj-b", lessons_learned=["lesson b"]))
        db.close()

        rows = show_lessons(project="proj-a", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["text"] == "lesson a"

    def test_lesson_dt_004_includes_attempted_approaches(self, tmp_path: Path) -> None:
        """LESSON-DT-004：attempted_approaches 也會被展開，source 為 handover-approach。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(
                lessons_learned=["lesson"],
                attempted_approaches=["試過 regex 太脆弱"],
            )
        )
        db.close()

        rows = show_lessons(db_path=db_path)
        sources = {r["source"] for r in rows}
        assert "handover" in sources
        assert "handover-approach" in sources
        approach_texts = [r["text"] for r in rows if r["source"] == "handover-approach"]
        assert "試過 regex 太脆弱" in approach_texts

    def test_lesson_dt_005_include_insights(self, tmp_path: Path) -> None:
        """LESSON-DT-005：include_insights=True 時也回傳 insight 記錄。"""
        insights_file = make_insights_file(tmp_path, [_SAMPLE_INSIGHT])
        rows = show_lessons(
            db_path=make_db_path(tmp_path),
            include_insights=True,
            insights_path=insights_file,
        )
        assert len(rows) == 1
        assert rows[0]["source"] == "insight"
        assert "這是一個洞察" in rows[0]["text"]

    def test_lesson_eg_001_insights_file_not_exist(self, tmp_path: Path) -> None:
        """LESSON-EG-001：insights.jsonl 不存在時 graceful 回傳空（不拋例外）。"""
        missing = tmp_path / "nonexistent.jsonl"
        rows = show_lessons(
            db_path=make_db_path(tmp_path),
            include_insights=True,
            insights_path=missing,
        )
        assert rows == []

    def test_lesson_eg_002_insights_oserror_returns_empty(self, tmp_path: Path) -> None:
        """LESSON-EG-002：insights.jsonl 讀取 OSError 時 graceful 回傳空（不拋例外）。"""
        db_path = make_db_path(tmp_path)
        insights_file = make_insights_file(tmp_path, [_SAMPLE_INSIGHT])
        with patch.object(Path, "open", side_effect=OSError("disk error")):
            rows = show_lessons(
                db_path=db_path,
                include_insights=True,
                insights_path=insights_file,
            )
        assert rows == []


class TestSearchLessons:
    def test_lesson_dt_006_search_matches_lesson_text(self, tmp_path: Path) -> None:
        """LESSON-DT-006：搜尋關鍵字比對 lessons_learned 文字。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["nom parser 很穩"]))
        db.insert_handover(make_record(id="r2", lessons_learned=["完全無關的教訓"]))
        db.close()

        rows = search_lessons(query="nom", db_path=db_path)
        assert len(rows) == 1
        assert "nom" in rows[0]["text"]

    def test_lesson_dt_007_search_includes_insights(self, tmp_path: Path) -> None:
        """LESSON-DT-007：include_insights=True 且關鍵字符合時回傳 insight。"""
        insights_file = make_insights_file(
            tmp_path,
            [
                {
                    **_SAMPLE_INSIGHT,
                    "insight_text": "pydantic v2 的 model_dump_json 效能比較好",
                }
            ],
        )
        rows = search_lessons(
            query="pydantic",
            db_path=make_db_path(tmp_path),
            include_insights=True,
            insights_path=insights_file,
        )
        assert len(rows) == 1
        assert rows[0]["source"] == "insight"

    def test_lesson_dt_008_search_no_match_returns_empty(self, tmp_path: Path) -> None:
        """LESSON-DT-008：關鍵字無匹配時回傳空 list。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["something unrelated"]))
        db.close()

        rows = search_lessons(query="zzz_notfound", db_path=db_path)
        assert rows == []

    def test_lesson_dt_009_search_matches_attempted_approaches(self, tmp_path: Path) -> None:
        """LESSON-DT-009：搜尋也比對 attempted_approaches 文字，source 為 handover-approach。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(
                lessons_learned=["無關教訓"],
                attempted_approaches=["試過 regex 但太脆弱"],
            )
        )
        db.close()

        rows = search_lessons(query="regex", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["source"] == "handover-approach"
        assert "regex" in rows[0]["text"]

    def test_lesson_dt_010_search_topic_match_does_not_bleed_lessons(self, tmp_path: Path) -> None:
        """LESSON-DT-010：topic 含關鍵字但 lessons 不含時，不應回傳該教訓。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        # topic 含 "parser"，但 lessons 不含
        db.insert_handover(
            make_record(topic="parser refactoring", lessons_learned=["use types instead"])
        )
        db.close()

        rows = search_lessons(query="parser", db_path=db_path)
        assert rows == []

    def test_lesson_dt_011_search_limit_caps_lesson_items(self, tmp_path: Path) -> None:
        """LESSON-DT-011：limit 控制回傳教訓條目數，不是 handover 記錄數。"""
        db_path = make_db_path(tmp_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        for i in range(5):
            db.insert_handover(
                make_record(
                    id=f"r{i}",
                    timestamp=f"2026-04-{i + 10:02d}T00:00:00+00:00",
                    lessons_learned=[f"target lesson {i}", f"another target {i}"],
                )
            )
        db.close()

        rows = search_lessons(query="target", db_path=db_path, limit=3)
        assert len(rows) == 3


class TestLessonsCLI:
    def test_lesson_cli_dt_001_show_empty_outputs_placeholder(self) -> None:
        """LESSON-CLI-DT-001：無教訓時顯示占位訊息。"""
        runner = CliRunner()
        with patch("tasks.mycelium.lessons_service.show_lessons", return_value=[]):
            result = runner.invoke(cli, ["lessons", "show"])
        assert result.exit_code == 0
        assert "尚無教訓記錄" in result.output

    def test_lesson_cli_dt_002_show_json_flag_outputs_valid_json(self) -> None:
        """LESSON-CLI-DT-002：--json 旗標輸出合法 JSON。"""
        sample = [
            {
                "source": "handover",
                "text": "test",
                "timestamp": "2026-04-15",
                "project": "p",
                "context": "c",
            }
        ]
        runner = CliRunner()
        with patch("tasks.mycelium.lessons_service.show_lessons", return_value=sample):
            result = runner.invoke(cli, ["lessons", "show", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1
        assert parsed[0]["text"] == "test"

    def test_lesson_cli_dt_003_search_no_match_outputs_placeholder(self) -> None:
        """LESSON-CLI-DT-003：search 無匹配時顯示占位訊息。"""
        runner = CliRunner()
        with patch("tasks.mycelium.lessons_service.search_lessons", return_value=[]):
            result = runner.invoke(cli, ["lessons", "search", "xyz"])
        assert result.exit_code == 0
        assert "無符合" in result.output

    def test_lesson_cli_dt_004_search_outputs_matches(self) -> None:
        """LESSON-CLI-DT-004：search 有匹配時正確顯示教訓。"""
        sample = [
            {
                "source": "handover",
                "text": "nom 很穩",
                "timestamp": "2026-04-15T10:00:00",
                "project": "proj",
                "context": "topic",
            }
        ]
        runner = CliRunner()
        with patch("tasks.mycelium.lessons_service.search_lessons", return_value=sample):
            result = runner.invoke(cli, ["lessons", "search", "nom"])
        assert result.exit_code == 0
        assert "nom 很穩" in result.output
        assert "交班教訓" in result.output

    def test_lesson_cli_eg_001_show_with_insights_flag(self) -> None:
        """LESSON-CLI-EG-001：--insights 旗標正確傳遞 include_insights=True。"""
        runner = CliRunner()
        with patch("tasks.mycelium.lessons_service.show_lessons", return_value=[]) as mock_show:
            runner.invoke(cli, ["lessons", "show", "--insights"])
        mock_show.assert_called_once()
        assert mock_show.call_args.kwargs.get("include_insights") is True


class TestLessonsAddCLI:
    """I2: lessons add CLI 測試（project 推斷、ValidationError、exception path）。"""

    def test_lsn_add_001_happy_path_explicit_project(self, tmp_path: Path) -> None:
        """LSN-ADD-001: 明確傳 --project 時正常寫入並回傳 id"""
        db_path = tmp_path / "test.db"
        runner = CliRunner()
        with patch(
            "tasks.mycelium.lessons_service.add_lesson",
            side_effect=lambda data, **_kw: add_lesson(data, db_path=db_path),
        ):
            result = runner.invoke(
                cli,
                [
                    "lessons",
                    "add",
                    "--type",
                    "pitfall",
                    "--key",
                    "test-add-key",
                    "--insight",
                    "explicit project add test insight content here",
                    "--confidence",
                    "7",
                    "--source",
                    "observed",
                    "--project",
                    "test-proj",
                ],
                catch_exceptions=False,
            )
        assert result.exit_code == 0, result.output
        assert "id=" in result.output

    def test_lsn_add_002_git_inference_success(self, tmp_path: Path) -> None:
        """LSN-ADD-002: git rev-parse 成功時 project 從 common-dir parent 推斷"""
        tmp_git_dir = str(Path("/tmp") / "my-project" / ".git")
        import subprocess as _sp

        fake_result = _sp.CompletedProcess(
            args=[],
            returncode=0,
            stdout=tmp_git_dir + "\n",
            stderr="",
        )
        captured: list[dict[str, object]] = []

        def capture_add(data: dict[str, object], **_kw: object) -> dict[str, object]:
            captured.append(data)
            return {"id": "fake-id", "trusted": False}

        runner = CliRunner()
        with (
            patch("subprocess.run", return_value=fake_result),
            patch(
                "tasks.mycelium.lessons_service.add_lesson",
                side_effect=capture_add,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "lessons",
                    "add",
                    "--type",
                    "pattern",
                    "--key",
                    "inferred-proj-key",
                    "--insight",
                    "git inference test insight content minimum length",
                    "--confidence",
                    "5",
                    "--source",
                    "observed",
                ],
                catch_exceptions=False,
            )
        assert result.exit_code == 0, result.output
        assert captured[0]["project"] == "my-project"

    def test_lsn_add_003_git_inference_failure_falls_back_to_unknown(self, tmp_path: Path) -> None:
        """LSN-ADD-003: git rev-parse 失敗（returncode != 0）時 project fallback 為 unknown"""
        import subprocess as _sp

        fake_result = _sp.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="not a git repo"
        )
        captured: list[dict[str, object]] = []

        def capture_add(data: dict[str, object], **_kw: object) -> dict[str, object]:
            captured.append(data)
            return {"id": "fake-id", "trusted": False}

        runner = CliRunner()
        with (
            patch("subprocess.run", return_value=fake_result),
            patch(
                "tasks.mycelium.lessons_service.add_lesson",
                side_effect=capture_add,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "lessons",
                    "add",
                    "--type",
                    "pitfall",
                    "--key",
                    "fallback-unknown-key",
                    "--insight",
                    "git inference failure test insight content here",
                    "--confidence",
                    "4",
                    "--source",
                    "observed",
                ],
                catch_exceptions=False,
            )
        assert result.exit_code == 0, result.output
        assert captured[0]["project"] == "unknown"

    def test_lsn_add_004_validation_error_bad_type(self, tmp_path: Path) -> None:
        """LSN-ADD-004: 非法 --type 值觸發 ValidationError exit 1"""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "lessons",
                "add",
                "--type",
                "nonexistent-type",
                "--key",
                "bad-type-key",
                "--insight",
                "validation error test insight content here",
                "--confidence",
                "5",
                "--source",
                "observed",
                "--project",
                "test-proj",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        assert "ValidationError" in result.output or "ValidationError" in (result.stderr or "")


class TestDecayTimezoneNaive:
    """NIT: _apply_decay 對 timezone-naive timestamp 的處理路徑。"""

    def test_lsn_decay_naive_ts_treated_as_utc(self) -> None:
        """LSN-DECAY-001: naive timestamp 補 UTC 後正確計算衰減"""
        now = datetime(2026, 6, 25, tzinfo=UTC)
        result = _apply_decay(8, "observed", "2026-04-26T00:00:00", now=now)
        assert result == 6


class TestFilterBypass:
    """Filter-bypass 回歸測試。

    確保 lesson_type / trusted_only / cross_project filter 正確阻擋 legacy 行。
    """

    def test_lsn_fb_001_lesson_type_blocks_legacy_pattern_rows(self, tmp_path: Path) -> None:
        """LSN-FB-001: lesson_type="pitfall" 時，legacy 行（type="pattern"）全部被排除"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(make_record(lessons_learned=["legacy lesson about pitfalls"]))
        db.close()

        rows = show_lessons_typed(
            project="ainization-skill",
            lesson_type="pitfall",
            include_legacy=True,
            with_decay=False,
            db_path=db_path,
        )
        assert all(r.get("type") == "pitfall" for r in rows), (
            "lesson_type filter 應排除所有 type!=pitfall 的 legacy 行"
        )
        assert not any(r.get("_legacy") for r in rows), (
            "legacy 行的 type 固定為 pattern，不應出現在 lesson_type=pitfall 結果中"
        )

    def test_lsn_fb_002_trusted_only_blocks_legacy(self, tmp_path: Path) -> None:
        """LSN-FB-002: trusted_only=True → _load_legacy_lessons 回傳 [] (legacy=trusted_False)"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(project="yibi-stack", lessons_learned=["legacy trusted bypass test"])
        )
        db.close()

        add_lesson(
            make_lesson_data(
                project="yibi-stack", source=LessonSource.user_stated, key="trusted-k"
            ),
            db_path=db_path,
        )

        rows = show_lessons_typed(
            project="yibi-stack",
            trusted_only=True,
            include_legacy=True,
            with_decay=False,
            db_path=db_path,
        )
        assert not any(r.get("_legacy") for r in rows), (
            "trusted_only=True 應排除全部 legacy 行（legacy 永遠 trusted=False）"
        )
        assert any(r.get("key") == "trusted-k" for r in rows), "typed trusted 行仍應出現"

    def test_lsn_fb_003_cross_project_excludes_legacy(self, tmp_path: Path) -> None:
        """LSN-FB-003: cross_project=True 隱含 trusted_only，legacy 行被全數排除"""
        db_path = tmp_path / "test.db"
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.insert_handover(
            make_record(project="proj-a", lessons_learned=["cross-project legacy test"])
        )
        db.close()

        add_lesson(
            make_lesson_data(project="proj-b", source=LessonSource.user_stated, key="cross-k"),
            db_path=db_path,
        )

        rows = show_lessons_typed(
            cross_project=True,
            include_legacy=True,
            with_decay=False,
            db_path=db_path,
        )
        assert not any(r.get("_legacy") for r in rows), (
            "cross_project=True 應排除 legacy 行（trusted_only 暗含）"
        )
        assert any(r.get("key") == "cross-k" for r in rows), "跨專案 trusted typed 行仍應出現"

    def test_lsn_fb_004_search_lessons_typed_basic_integration(self, tmp_path: Path) -> None:
        """LSN-FB-004: search_lessons_typed 可找到 typed lessons table 中的記錄"""
        db_path = tmp_path / "test.db"
        add_lesson(
            make_lesson_data(
                key="search-integration-key",
                insight="rg uses ERE not BRE; backslash-pipe is literal not alternation",
            ),
            db_path=db_path,
        )

        rows = search_lessons_typed(
            query="backslash-pipe",
            include_legacy=False,
            with_decay=False,
            db_path=db_path,
        )
        assert len(rows) >= 1, "search_lessons_typed 應找到含查詢字串的 typed lesson"
        assert any("backslash-pipe" in r.get("insight", "") for r in rows)

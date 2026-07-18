"""debug_report_service 單元測試。"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from tasks.mycelium.cli import cli
from tasks.mycelium.debug_report_service import list_debug_reports, save_debug_report
from tasks.mycelium.models import DebugReportRecord


def make_report(**kwargs: object) -> DebugReportRecord:
    defaults: dict[str, object] = {
        "keyword": "mypy_follow_imports",
        "report_path": "debugs/2026-04-28_mypy_follow_imports_debug_report.md",
        "symptom_summary": "mypy 在 CI 報 import-untyped，local 不報",
        "root_cause": "follow_imports=normal 在 CI 上走到 site-packages，local 是 skip",
    }
    return save_debug_report(**{**defaults, **kwargs})  # type: ignore[arg-type]


def make_debug_save_args(project: str | None = None) -> list[str]:
    """建立 debug save CLI 參數；project 為 None 時省略旗標。"""
    args = [
        "debug",
        "save",
        "--keyword",
        "test_bug",
        "--report-path",
        "debugs/test.md",
        "--symptom",
        "症狀",
        "--root-cause",
        "根因",
    ]
    if project is not None:
        args.extend(["--project", project])
    return args


class TestSaveDebugReport:
    def test_sm_dr_001_creates_jsonl(self, tmp_path: Path) -> None:
        """SM-DR-001: save_debug_report 寫入 JSONL 並回傳 DebugReportRecord。"""
        out = tmp_path / "debug-reports.jsonl"
        record = make_report(output_path=out)

        assert isinstance(record, DebugReportRecord)
        assert out.exists()
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["keyword"] == "mypy_follow_imports"

    def test_sm_dr_002_appends_idempotent(self, tmp_path: Path) -> None:
        """SM-DR-002: 重複 save 寫入兩筆（各有獨立 id，不去重）。"""
        out = tmp_path / "debug-reports.jsonl"
        r1 = make_report(output_path=out)
        r2 = make_report(output_path=out)

        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert r1.id != r2.id

    def test_sm_dr_003_prevention_tags(self, tmp_path: Path) -> None:
        """SM-DR-003: prevention_tags 正確序列化。"""
        out = tmp_path / "debug-reports.jsonl"
        record = make_report(prevention_tags=["mypy", "ci"], output_path=out)

        assert record.prevention_tags == ["mypy", "ci"]
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["prevention_tags"] == ["mypy", "ci"]

    def test_sm_dr_004_empty_prevention_tags(self, tmp_path: Path) -> None:
        """SM-DR-004: 未傳 prevention_tags 時為空 list，且序列化後為 []。"""
        out = tmp_path / "debug-reports.jsonl"
        record = make_report(output_path=out)
        assert record.prevention_tags == []
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["prevention_tags"] == []

    def test_sm_dr_005_creates_parent_dir(self, tmp_path: Path) -> None:
        """SM-DR-005: 輸出路徑的父目錄不存在時自動建立。"""
        out = tmp_path / "nested" / "dir" / "debug-reports.jsonl"
        make_report(output_path=out)
        assert out.exists()


class TestListDebugReports:
    def test_sm_dr_010_empty_when_no_file(self, tmp_path: Path) -> None:
        """SM-DR-010: JSONL 不存在時回傳空 list。"""
        out = tmp_path / "debug-reports.jsonl"
        assert list_debug_reports(output_path=out) == []

    def test_sm_dr_011_returns_last_n(self, tmp_path: Path) -> None:
        """SM-DR-011: last 參數正確裁切結果。"""
        out = tmp_path / "debug-reports.jsonl"
        for i in range(5):
            make_report(keyword=f"bug_{i}", output_path=out)

        rows = list_debug_reports(last=3, output_path=out)
        assert len(rows) == 3
        assert rows[-1].keyword == "bug_4"

    def test_sm_dr_012_project_filter(self, tmp_path: Path) -> None:
        """SM-DR-012: project filter 僅回傳符合的記錄。"""
        out = tmp_path / "debug-reports.jsonl"
        r1 = save_debug_report(
            keyword="bug_a",
            report_path="debugs/a.md",
            symptom_summary="症狀 a",
            root_cause="根因 a",
            output_path=out,
        )
        fake = {**json.loads(r1.model_dump_json()), "project": "other-project", "id": "fake-id"}
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fake) + "\n")

        rows = list_debug_reports(project=r1.project, output_path=out)
        assert all(r.project == r1.project for r in rows)

    def test_sm_dr_013_skips_corrupt_lines(self, tmp_path: Path) -> None:
        """SM-DR-013: 遇到損壞 JSON 行時跳過，發 UserWarning，不拋例外。"""
        out = tmp_path / "debug-reports.jsonl"
        make_report(output_path=out)
        with out.open("a", encoding="utf-8") as f:
            f.write("not-json\n")
        make_report(keyword="after_corrupt", output_path=out)

        with pytest.warns(UserWarning, match="格式錯誤"):
            rows = list_debug_reports(output_path=out)
        assert len(rows) == 2
        assert rows[-1].keyword == "after_corrupt"

    def test_sm_dr_014_skips_schema_invalid_lines(self, tmp_path: Path) -> None:
        """SM-DR-014: 有效 JSON 但 schema 不符時跳過，並發 UserWarning。"""
        out = tmp_path / "debug-reports.jsonl"
        make_report(output_path=out)
        bad = {"id": "x", "timestamp": "not-a-date", "keyword": "k"}
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(bad) + "\n")
        make_report(keyword="after_invalid", output_path=out)

        with pytest.warns(UserWarning, match="schema 不符"):
            rows = list_debug_reports(output_path=out)
        assert len(rows) == 2
        assert rows[-1].keyword == "after_invalid"

    def test_sm_dr_015_save_raises_on_permission_error(self, tmp_path: Path) -> None:
        """SM-DR-015: 寫入失敗時 save_debug_report 拋 RuntimeError（不是裸 OSError）。"""
        out = tmp_path / "no_write" / "debug-reports.jsonl"
        out.parent.mkdir()
        out.parent.chmod(0o444)
        try:
            with pytest.raises(RuntimeError, match="無法寫入"):
                make_report(output_path=out)
        finally:
            out.parent.chmod(0o755)

    def test_sm_dr_016_unicode_error_raises_runtime_error(self, tmp_path: Path) -> None:
        """SM-DR-016: JSONL 含無效 UTF-8 bytes 時 list_debug_reports 拋 RuntimeError。"""
        out = tmp_path / "debug-reports.jsonl"
        out.write_bytes(b"\xff\xfe invalid utf-8\n")
        with pytest.raises(RuntimeError, match="無法讀取"):
            list_debug_reports(output_path=out)


class TestDebugCLI:
    def test_sm_dr_030_save_splits_prevention_tags(self) -> None:
        """SM-DR-030: debug save 以逗號分隔 prevention_tags 並 strip 空白。"""
        runner = CliRunner()
        mock_record = MagicMock(id="test-id", keyword="test_bug", project="proj")
        with patch(
            "tasks.mycelium.debug_report_service.save_debug_report",
            return_value=mock_record,
        ) as mock_save:
            result = runner.invoke(
                cli,
                [
                    "debug",
                    "save",
                    "--keyword",
                    "test_bug",
                    "--report-path",
                    "debugs/test.md",
                    "--symptom",
                    "症狀",
                    "--root-cause",
                    "根因",
                    "--prevention-tags",
                    "mypy, ci",
                ],
            )
        assert result.exit_code == 0
        assert mock_save.call_args.kwargs["prevention_tags"] == ["mypy", "ci"]

    def test_sm_dr_031_save_whitespace_keyword_exits_1(self) -> None:
        """SM-DR-031: keyword 為純空白時 debug save exit 1，不拋 raw traceback。"""

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "debug",
                "save",
                "--keyword",
                "   ",
                "--report-path",
                "debugs/test.md",
                "--symptom",
                "s",
                "--root-cause",
                "r",
            ],
        )
        assert result.exit_code == 1
        assert "✗" in result.output

    def test_sm_dr_032_list_runtime_error_exits_1(self) -> None:
        """SM-DR-032: list_debug_reports 拋 RuntimeError 時 debug list exit 1。"""
        runner = CliRunner()
        with patch(
            "tasks.mycelium.debug_report_service.list_debug_reports",
            side_effect=RuntimeError("read failed"),
        ):
            result = runner.invoke(cli, ["debug", "list"])
        assert result.exit_code == 1

    def test_sm_dr_033_save_explicit_project_persists_value(self, tmp_path: Path) -> None:
        """SM-DR-033: debug save 的 explicit --project 寫入指定 project。"""
        out = tmp_path / "debug-reports.jsonl"
        runner = CliRunner()
        with (
            patch(
                "tasks.mycelium.debug_report_service.save_debug_report",
                side_effect=partial(save_debug_report, output_path=out),
            ),
            patch(
                "tasks.mycelium.debug_report_service.detect_project",
                return_value="cwd-project",
            ) as mock_detect,
        ):
            result = runner.invoke(cli, make_debug_save_args(project="target-project"))

        assert result.exit_code == 0
        record = list_debug_reports(output_path=out)[0]
        assert record.project == "target-project"
        mock_detect.assert_not_called()

    def test_sm_dr_034_save_omitted_project_uses_inferred_value(self, tmp_path: Path) -> None:
        """SM-DR-034: debug save 省略 --project 時保留 git project 推斷。"""
        out = tmp_path / "debug-reports.jsonl"
        runner = CliRunner()
        with (
            patch(
                "tasks.mycelium.debug_report_service.save_debug_report",
                side_effect=partial(save_debug_report, output_path=out),
            ),
            patch(
                "tasks.mycelium.debug_report_service.detect_project",
                return_value="inferred-project",
            ) as mock_detect,
        ):
            result = runner.invoke(cli, make_debug_save_args())

        assert result.exit_code == 0
        record = list_debug_reports(output_path=out)[0]
        assert record.project == "inferred-project"
        mock_detect.assert_called_once_with()


class TestDebugReportRecordValidation:
    def test_sm_dr_020_rejects_empty_keyword(self) -> None:
        """SM-DR-020: keyword 為空字串時 ValidationError。"""
        with pytest.raises(ValidationError):
            DebugReportRecord(
                id="x",
                timestamp="2026-04-28T00:00:00+00:00",
                project="p",
                working_dir="~/p",
                branch="main",
                keyword="",
                report_path="debugs/r.md",
                symptom_summary="s",
                root_cause="r",
            )

    def test_sm_dr_021_rejects_bad_timestamp(self) -> None:
        """SM-DR-021: timestamp 不符合 ISO 8601 時 ValidationError。"""
        with pytest.raises(ValidationError):
            DebugReportRecord(
                id="x",
                timestamp="not-a-date",
                project="p",
                working_dir="~/p",
                branch="main",
                keyword="k",
                report_path="debugs/r.md",
                symptom_summary="s",
                root_cause="r",
            )

    def test_sm_dr_022_rejects_whitespace_only_keyword(self) -> None:
        """SM-DR-022: keyword 為純空白字串時 ValidationError。"""
        with pytest.raises(ValidationError):
            DebugReportRecord(
                id="x",
                timestamp="2026-04-28T00:00:00+00:00",
                project="p",
                working_dir="~/p",
                branch="main",
                keyword="   ",
                report_path="debugs/r.md",
                symptom_summary="s",
                root_cause="r",
            )

    def test_sm_dr_023_rejects_empty_report_path(self) -> None:
        """SM-DR-023: report_path 為空字串時 ValidationError。"""
        with pytest.raises(ValidationError):
            DebugReportRecord(
                id="x",
                timestamp="2026-04-28T00:00:00+00:00",
                project="p",
                working_dir="~/p",
                branch="main",
                keyword="k",
                report_path="",
                symptom_summary="s",
                root_cause="r",
            )

    def test_sm_dr_024_strips_whitespace_from_keyword(self) -> None:
        """SM-DR-024: keyword 有前後空白時自動 strip，不保留空白。"""
        record = DebugReportRecord(
            id="x",
            timestamp="2026-04-28T00:00:00+00:00",
            project="p",
            working_dir="~/p",
            branch="main",
            keyword="  mypy  ",
            report_path="debugs/r.md",
            symptom_summary="s",
            root_cause="r",
        )
        assert record.keyword == "mypy"

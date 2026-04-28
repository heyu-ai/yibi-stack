"""Debug report 持久化服務：寫入 ~/.agents/debugs/debug-reports.jsonl。"""

from __future__ import annotations

import json
import uuid
import warnings
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .account import detect_account, detect_branch, detect_device, detect_project
from .config import DEBUG_REPORTS_JSONL_PATH, to_portable_path
from .models import DebugReportRecord


def save_debug_report(
    keyword: str,
    report_path: str,
    symptom_summary: str,
    root_cause: str,
    prevention_tags: list[str] | None = None,
    output_path: Path | None = None,
) -> DebugReportRecord:
    """將 debug report 摘要寫入 JSONL，回傳寫入的記錄。"""
    now = datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()
    record = DebugReportRecord(
        id=str(uuid.uuid4()),
        timestamp=now,
        project=detect_project(),
        working_dir=to_portable_path(str(Path.cwd())),
        branch=detect_branch() or "",
        keyword=keyword,
        report_path=report_path,
        symptom_summary=symptom_summary,
        root_cause=root_cause,
        prevention_tags=prevention_tags or [],
        agent_type="claude",
        account=detect_account(warn=False),
        device=detect_device(),
    )
    out_path = output_path or DEBUG_REPORTS_JSONL_PATH
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
    except OSError as e:
        raise RuntimeError(f"無法寫入 debug-reports.jsonl：{out_path}") from e
    return record


def list_debug_reports(
    last: int = 10,
    project: str | None = None,
    output_path: Path | None = None,
) -> list[DebugReportRecord]:
    """讀取 JSONL，回傳最近 N 筆（可依 project filter）。"""
    jsonl_path = output_path or DEBUG_REPORTS_JSONL_PATH
    if not jsonl_path.exists():
        return []

    rows: list[DebugReportRecord] = []
    json_errors = 0
    schema_errors = 0
    try:
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    json_errors += 1
                    continue
                try:
                    validated = DebugReportRecord.model_validate(data)
                except ValidationError:
                    schema_errors += 1
                    continue
                if project and validated.project != project:
                    continue
                rows.append(validated)
    except (OSError, UnicodeDecodeError) as e:
        raise RuntimeError(f"無法讀取 debug-reports.jsonl：{jsonl_path}") from e

    if json_errors:
        warnings.warn(
            f"list_debug_reports：{json_errors} 筆記錄 JSON 格式錯誤，已略過。請檢查 {jsonl_path}",
            stacklevel=2,
        )
    if schema_errors:
        warnings.warn(
            f"list_debug_reports：{schema_errors} 筆記錄 schema 不符，已略過。請檢查 {jsonl_path}",
            stacklevel=2,
        )
    return rows[-last:]

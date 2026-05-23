"""bash-hygiene audit log 讀取與統計分析。"""

from __future__ import annotations

import json
import subprocess  # nosec B404
from pathlib import Path

from .models import AuditRecord, AuditStats, Verdict


def _find_log_path(project_root: Path | None = None) -> Path | None:
    """找到當前 git repo 的 audit log 路徑；找不到時回傳 None。"""
    if project_root is None:
        try:
            result = subprocess.run(  # nosec B603 B607
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None
            project_root = Path(result.stdout.strip()).parent
        except Exception:
            return None
    return project_root / ".runtime" / "logs" / "bash-hygiene-audit.jsonl"


def read_log(
    last: int = 50,
    hook: str | None = None,
    verdict: str | None = None,
    project_root: Path | None = None,
) -> list[AuditRecord]:
    """讀取 audit log，依 last/hook/verdict 過濾，回傳最近 N 筆。"""
    path = _find_log_path(project_root)
    if path is None or not path.is_file():
        return []
    records: list[AuditRecord] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(AuditRecord.model_validate(json.loads(line)))
            except Exception:  # nosec B112
                continue
    if hook:
        records = [r for r in records if r.hook == hook]
    if verdict:
        records = [r for r in records if r.verdict == verdict]
    return records[-last:]


def compute_stats(records: list[AuditRecord]) -> AuditStats:
    """從 AuditRecord 列表計算聚合統計。"""
    stats = AuditStats(total=len(records))
    durations: list[int] = []
    for r in records:
        if r.verdict == Verdict.ALLOW:
            stats.allow_count += 1
        elif r.verdict == Verdict.BLOCK:
            stats.block_count += 1
        else:
            stats.error_count += 1
        stats.by_hook[r.hook] = stats.by_hook.get(r.hook, 0) + 1
        if r.block_reason:
            stats.by_reason[r.block_reason] = stats.by_reason.get(r.block_reason, 0) + 1
        if r.duration_ms is not None:
            durations.append(r.duration_ms)
    if durations:
        stats.avg_duration_ms = sum(durations) / len(durations)
    return stats


def log_path(project_root: Path | None = None) -> Path | None:
    """回傳 audit log 絕對路徑（供 CLI status 指令顯示）。"""
    return _find_log_path(project_root)


def count_log_lines(project_root: Path | None = None) -> int:
    """回傳 audit log 非空行數（不做 Pydantic 解析，供 status 指令輕量計數）。"""
    path = _find_log_path(project_root)
    if path is None or not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())

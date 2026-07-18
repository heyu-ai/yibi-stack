"""bash-hygiene audit log 讀取與統計分析。"""

from __future__ import annotations

import json
import subprocess  # nosec B404
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .models import AuditRecord, AuditStats, RepeatEvent, RepeatStats, Verdict

_LOG_STEM = "bash-hygiene-audit"


def _find_log_dir(project_root: Path | None = None) -> Path | None:
    """找到當前 git repo 的 audit log 目錄；找不到時回傳 None。"""
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
    return project_root / ".runtime" / "logs"


def _find_log_paths(project_root: Path | None = None) -> list[Path]:
    """回傳所有要讀的 audit log，依日期排序（舊 -> 新）。

    log 自 PR #262 起改為每日輪替（`bash-hygiene-audit-YYYY-MM-DD.jsonl`）。
    **同時仍讀舊的單一檔** `bash-hygiene-audit.jsonl`：升級當下那個檔還在（實測 94 MB /
    39 天的歷史），若不讀它，使用者的 stats 會在升級瞬間一片空白——那是靜默的資料消失，
    比留著更糟。舊檔不會再被寫入，也不會被輪替刪掉（它的檔名解析不出日期），
    使用者確認不需要後可自行刪除。
    """
    d = _find_log_dir(project_root)
    if d is None or not d.is_dir():
        return []
    dated = sorted(d.glob(f"{_LOG_STEM}-*.jsonl"))
    legacy = d / f"{_LOG_STEM}.jsonl"
    paths = [legacy] if legacy.is_file() else []
    paths.extend(p for p in dated if p.is_file())
    return paths


def _find_log_path(project_root: Path | None = None) -> Path | None:
    """相容用：回傳最新的一個 log 檔。新程式碼請用 `_find_log_paths`。"""
    paths = _find_log_paths(project_root)
    return paths[-1] if paths else None


def read_log(
    last: int = 50,
    hook: str | None = None,
    verdict: str | None = None,
    project_root: Path | None = None,
) -> list[AuditRecord]:
    """讀取 audit log，依 last/hook/verdict 過濾，回傳最近 N 筆。

    跨所有每日檔 + 舊的單一檔一起讀（見 `_find_log_paths`）。
    """
    records: list[AuditRecord] = []
    for path in _find_log_paths(project_root):
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


def compute_repeats(
    records: list[AuditRecord],
    top_n: int = 5,
    token_per_repeat_estimate: int = 1500,
) -> RepeatStats:
    """計算同 session 同 command_hash 被 block >= 2 次的重複攔截統計。

    token_per_repeat_estimate：每次「額外」block 的估算 token 浪費（不含第一次）。
    時間浪費 = 同群組最後一筆 ts 減最早一筆 ts。
    """
    buckets: dict[tuple[str, str], list[AuditRecord]] = defaultdict(list)
    for r in records:
        if r.verdict == Verdict.BLOCK and r.session_id and r.command_hash:
            buckets[(r.session_id, r.command_hash)].append(r)

    repeat_events: list[RepeatEvent] = []
    for (sid, h), rs in buckets.items():
        if len(rs) < 2:
            continue
        sorted_rs = sorted(rs, key=lambda x: x.ts)
        first = sorted_rs[0]
        last_r = sorted_rs[-1]
        try:
            dt_first = datetime.fromisoformat(first.ts.replace("Z", "+00:00"))
            dt_last = datetime.fromisoformat(last_r.ts.replace("Z", "+00:00"))
            wasted_ms = int((dt_last - dt_first).total_seconds() * 1000)
        except Exception:
            wasted_ms = 0
        # 額外 block 次數 = count - 1（第一次是正常觸發，從第二次起算浪費）
        extra_blocks = len(rs) - 1
        repeat_events.append(
            RepeatEvent(
                session_id=sid,
                command_hash=h,
                command_preview=first.cmd_snippet[:80],
                block_reason=first.block_reason,
                count=len(rs),
                first_ts=first.ts,
                last_ts=last_r.ts,
                estimated_wasted_ms=wasted_ms,
                estimated_wasted_tokens=extra_blocks * token_per_repeat_estimate,
            )
        )

    repeat_events.sort(key=lambda e: -e.count)

    total_blocks = sum(1 for r in records if r.verdict == Verdict.BLOCK)
    repeated_blocks = sum(e.count for e in repeat_events)
    repeat_rate = repeated_blocks / total_blocks if total_blocks else 0.0
    reason_counts: dict[str, int] = defaultdict(int)
    for e in repeat_events:
        if e.block_reason:
            reason_counts[e.block_reason] += e.count

    return RepeatStats(
        total_blocks=total_blocks,
        repeated_blocks=repeated_blocks,
        repeat_rate=repeat_rate,
        unique_repeat_events=len(repeat_events),
        total_wasted_ms=sum(e.estimated_wasted_ms for e in repeat_events),
        total_wasted_tokens=sum(e.estimated_wasted_tokens for e in repeat_events),
        top_offenders=repeat_events[:top_n],
        by_reason=dict(reason_counts),
    )


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

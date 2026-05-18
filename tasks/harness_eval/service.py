"""harness_eval 掃描編排：呼叫所有 scanner，彙整 ScanOutput。"""

from datetime import UTC, datetime
from pathlib import Path

from .models import ScanOutput
from .scanners import (
    scan_claude_md,
    scan_git,
    scan_hooks,
    scan_rules,
    scan_security,
    scan_settings,
    scan_skills,
    scan_testing,
)


def run_scan(target_dir: Path | str) -> ScanOutput:
    """對 target_dir 執行 D1–D8 機械掃描，回傳 ScanOutput。"""
    target = Path(target_dir).resolve()
    dimensions = [
        scan_claude_md(target),
        scan_hooks(target),
        scan_settings(target),
        scan_skills(target),
        scan_testing(target),
        scan_git(target),
        scan_rules(target),
        scan_security(target),
    ]
    return ScanOutput(
        target_dir=str(target),
        scanned_at=datetime.now(tz=UTC).isoformat(),
        dimensions=dimensions,
    )

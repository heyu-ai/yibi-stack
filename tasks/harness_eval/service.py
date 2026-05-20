"""harness_eval 掃描編排：呼叫所有 scanner，彙整 ScanOutput。"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .models import MechanicalFinding, ScanOutput
from .scanners import (
    scan_claude_md,
    scan_git,
    scan_hooks,
    scan_navigation,
    scan_rules,
    scan_security,
    scan_settings,
    scan_skills,
    scan_subagents,
    scan_testing,
)


def _safe_scan(
    scanner_fn: Callable[[Path], MechanicalFinding],
    target: Path,
    dimension: str,
    label: str,
    max_score: int,
) -> MechanicalFinding:
    """安全呼叫 scanner，避免單一 scanner 錯誤中斷整個掃描。"""
    try:
        return scanner_fn(target)
    except Exception as e:  # noqa: BLE001
        return MechanicalFinding(
            dimension=dimension,
            label=label,
            score=0,
            max_score=max_score,
            findings=[f"FAIL: scanner 內部錯誤，請回報：{e}"],
        )


def run_scan(target_dir: Path | str) -> ScanOutput:
    """對 target_dir 執行 D1–D10 機械掃描，回傳 ScanOutput。"""
    target = Path(target_dir).resolve()
    dimensions = [
        _safe_scan(scan_claude_md, target, "D1", "CLAUDE.md 品質", 8),
        _safe_scan(scan_hooks, target, "D2", "Hooks & 自動化", 13),
        _safe_scan(scan_settings, target, "D3", "Settings & 權限", 6),
        _safe_scan(scan_skills, target, "D4", "Skills & Commands", 8),
        _safe_scan(scan_testing, target, "D5", "Testing & CI 整合", 7),
        _safe_scan(scan_git, target, "D6", "Git 工作流程 & Commit", 6),
        _safe_scan(scan_rules, target, "D7", "Rules 文件 & 路徑作用域", 7),
        _safe_scan(scan_security, target, "D8", "Security & Trust", 7),
        _safe_scan(scan_subagents, target, "D9", "Subagents（探索/編輯隔離）", 4),
        _safe_scan(scan_navigation, target, "D10", "Codebase Navigation", 3),
    ]
    return ScanOutput(
        target_dir=str(target),
        scanned_at=datetime.now(tz=UTC).isoformat(),
        dimensions=dimensions,
    )

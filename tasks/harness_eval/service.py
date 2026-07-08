"""harness_eval 掃描編排：呼叫所有 scanner，彙整 ScanOutput。"""

import json
import math
import os
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
    scan_token_economy,
)

# D_repo provisional 縮放係數；真正校準見 issue #143。
_DREPO_SCALE = 50.0
# 各複雜度訊號的 provisional 權重（一個 skill/rule 的結構份量 ≈ 數十至上百行 source）。
_SKILL_WEIGHT = 100
_HOOK_WEIGHT = 50
_RULE_WEIGHT = 80


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


def _count_source_loc(target_dir: Path) -> int:
    """計算 tasks/ 與 scripts/ 下 .py 檔總行數（source 規模 proxy）。"""
    total = 0
    for sub in ("tasks", "scripts"):
        root = target_dir / sub
        if not root.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root, followlinks=True):
            for name in files:
                if not name.endswith(".py"):
                    continue
                try:
                    text = (Path(dirpath) / name).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                total += text.count("\n") + 1
    return total


def _count_skills(target_dir: Path) -> int:
    """計算 skills/ 與 .claude/skills/ 下 SKILL.md 數（rule 02：followlinks）。"""
    count = 0
    for sub in ("skills", ".claude/skills"):
        root = target_dir / sub
        if not root.is_dir():
            continue
        for _dirpath, _dirs, files in os.walk(root, followlinks=True):
            if "SKILL.md" in files:
                count += 1
    return count


def _count_rules(target_dir: Path) -> int:
    """計算 .claude/rules/*.md 檔數。"""
    rules_dir = target_dir / ".claude" / "rules"
    if not rules_dir.is_dir():
        return 0
    return sum(1 for f in rules_dir.iterdir() if f.is_file() and f.suffix == ".md")


def _count_hooks(target_dir: Path) -> int:
    """計算 .claude/settings.json 中註冊的 command hook 數（防禦式解析）。"""
    settings = target_dir / ".claude" / "settings.json"
    if not settings.is_file():
        return 0
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    count = 0
    for matchers in hooks.values():
        if not isinstance(matchers, list):
            continue
        for matcher in matchers:
            inner = matcher.get("hooks") if isinstance(matcher, dict) else None
            if isinstance(inner, list):
                count += sum(1 for h in inner if isinstance(h, dict) and h.get("command"))
    return count


def _compute_d_repo(target_dir: Path) -> tuple[float, list[str]]:
    """計算 repo 複雜度因子 D_repo（>=1.0）與其組成清單。

    provisional：未經 outcome 校準，僅供相對規模調整（issue #136；校準見 #143）。
    """
    loc = _count_source_loc(target_dir)
    skills = _count_skills(target_dir)
    hooks = _count_hooks(target_dir)
    rules = _count_rules(target_dir)
    raw = loc + skills * _SKILL_WEIGHT + hooks * _HOOK_WEIGHT + rules * _RULE_WEIGHT
    d_repo = 1.0 + math.log10(1.0 + raw / _DREPO_SCALE)
    components = [f"loc={loc}", f"skills={skills}", f"hooks={hooks}", f"rules={rules}"]
    return round(d_repo, 3), components


def run_scan(target_dir: Path | str) -> ScanOutput:
    """對 target_dir 執行 D1–D11 機械掃描，回傳 ScanOutput。"""
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
        _safe_scan(scan_token_economy, target, "D11", "Context / Token Economy", 8),
    ]
    d_repo, d_repo_components = _compute_d_repo(target)
    return ScanOutput(
        target_dir=str(target),
        scanned_at=datetime.now(tz=UTC).isoformat(),
        dimensions=dimensions,
        d_repo=d_repo,
        d_repo_components=d_repo_components,
    )

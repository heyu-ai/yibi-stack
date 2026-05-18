"""D2 scanner：Hooks 設定（機械分 12/18）。"""

import json
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 12


def scan_hooks(target_dir: Path) -> MechanicalFinding:
    """掃描 settings.json 的 hooks 設定。語意分（6 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    settings_path = target_dir / ".claude" / "settings.json"
    if not settings_path.exists():
        findings.append("WARN: .claude/settings.json 不存在")
        return MechanicalFinding(
            dimension="D2",
            label="Hooks 設定",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        findings.append(f"FAIL: settings.json 格式錯誤：{e}")
        return MechanicalFinding(
            dimension="D2",
            label="Hooks 設定",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    hooks = data.get("hooks", {})
    if not hooks:
        findings.append("WARN: settings.json 無 hooks 區塊")
        return MechanicalFinding(
            dimension="D2",
            label="Hooks 設定",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    score += 3
    findings.append("hooks 區塊存在")
    semantic_targets.append(str(settings_path))

    if hooks.get("PreToolUse"):
        score += 3
        findings.append("PreToolUse 安全閘存在")
    else:
        findings.append("WARN: PreToolUse hook 未設定")

    if hooks.get("PostToolUse"):
        score += 3
        findings.append("PostToolUse 品質迴圈存在")
    else:
        findings.append("WARN: PostToolUse hook 未設定")

    if hooks.get("Stop"):
        score += 3
        findings.append("Stop hook 驗證閘存在")
    else:
        findings.append("WARN: Stop hook 未設定")

    return MechanicalFinding(
        dimension="D2",
        label="Hooks 設定",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

"""D3 scanner：Settings & 權限（機械分 6/10）。"""

import json
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 6


def scan_settings(target_dir: Path) -> MechanicalFinding:
    """掃描 settings.json deny/allow list。語意分（4 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    settings_path = target_dir / ".claude" / "settings.json"
    if not settings_path.exists():
        findings.append("WARN: .claude/settings.json 不存在")
        return MechanicalFinding(
            dimension="D3", label="Settings & 權限", score=0, max_score=_MECH_MAX, findings=findings
        )

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        findings.append("FAIL: settings.json 格式錯誤")
        return MechanicalFinding(
            dimension="D3", label="Settings & 權限", score=0, max_score=_MECH_MAX, findings=findings
        )

    perms = data.get("permissions", {})
    deny = perms.get("deny", [])
    allow = perms.get("allow", [])

    deny_has_rm = any("rm" in str(d).lower() for d in deny)
    if deny_has_rm:
        score += 3
        findings.append(f"deny list 含 rm 防護（{len(deny)} 條規則）")
    elif deny:
        score += 1
        findings.append(f"WARN: deny list 存在（{len(deny)} 條）但未含 rm -rf 防護")
    else:
        findings.append("WARN: deny list 未設定")

    if allow:
        score += 3
        findings.append(f"allow list 存在（{len(allow)} 條規則）")
    else:
        findings.append("WARN: allow list 未設定（使用預設許可）")

    semantic_targets.append(str(settings_path))

    return MechanicalFinding(
        dimension="D3",
        label="Settings & 權限",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

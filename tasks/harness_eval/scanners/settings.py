"""D3 scanner：Settings & 權限（機械分 6/10）。"""

import json
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 6

# 高風險操作關鍵字，deny list 應涵蓋這些；逐條比對，避免 join 跨條目誤匹配
_DESTRUCTIVE_PATTERNS = [
    ("rm", "rm -rf 刪除防護"),
    ("force", "git push --force 防護"),
    ("reset --hard", "git reset --hard 防護"),
    ("drop", "DROP TABLE 防護"),
    ("alembic", "DB migration 防護"),
]


def _check_deny_coverage(deny: list[object]) -> tuple[int, list[str]]:
    """回傳 (score, findings)：deny list 覆蓋多少高風險操作。

    逐條比對每個 deny entry，避免 join 成單一字串時的跨條目誤匹配
    （如 Bash(enforce*) 不應匹配 force 關鍵字）。
    """
    covered: list[str] = []
    for keyword, label in _DESTRUCTIVE_PATTERNS:
        kw = keyword.lower()
        if any(kw in str(d).lower() for d in deny):
            covered.append(label)
    if len(covered) >= 3:
        return 3, [f"deny list 覆蓋 {len(covered)}/{len(_DESTRUCTIVE_PATTERNS)} 高風險操作：{covered}"]
    if covered:
        missing = [lbl for kw, lbl in _DESTRUCTIVE_PATTERNS if not any(kw.lower() in str(d).lower() for d in deny)]
        return 1, [
            f"WARN: deny list 部分覆蓋（{len(covered)} 項），缺少：{missing[:3]}",
        ]
    return 0, [f"WARN: deny list 存在（{len(deny)} 條）但未覆蓋任何高風險操作"]


def _has_wildcard_allow(allow: list[object]) -> bool:
    """偵測是否有過寬的萬用字元授權。

    使用 substring 偵測 '*' 而非精確匹配，涵蓋 Bash(*) / Bash(git *) / Bash( * ) 等變體。
    """
    for entry in allow:
        s = str(entry)
        if "*" in s:
            return True
    return False


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
    except json.JSONDecodeError as e:
        findings.append(f"FAIL: settings.json 格式錯誤：{e}")
        return MechanicalFinding(
            dimension="D3", label="Settings & 權限", score=0, max_score=_MECH_MAX, findings=findings
        )
    except OSError as e:
        findings.append(f"FAIL: settings.json 無法讀取：{e}")
        return MechanicalFinding(
            dimension="D3", label="Settings & 權限", score=0, max_score=_MECH_MAX, findings=findings
        )

    perms = data.get("permissions", {})
    deny = perms.get("deny", [])
    allow = perms.get("allow", [])

    # deny list 品質評分（0-3 分）
    if deny:
        deny_score, deny_findings = _check_deny_coverage(deny)
        score += deny_score
        findings.extend(deny_findings)
    else:
        findings.append("WARN: deny list 未設定（建議至少防護 rm -rf 與 git push --force）")

    # allow list 精確性評分（0-3 分）
    if allow:
        if _has_wildcard_allow(allow):
            findings.append(
                f"WARN: allow list 含萬用字元過寬授權（{len(allow)} 條），建議改為具體工具名稱"
            )
            score += 1
        else:
            score += 3
            findings.append(f"allow list 精確授權（{len(allow)} 條，無萬用字元）")
    else:
        findings.append("WARN: allow list 未設定（使用預設許可，可能產生過多確認框）")

    semantic_targets.append(str(settings_path))

    return MechanicalFinding(
        dimension="D3",
        label="Settings & 權限",
        score=min(score, _MECH_MAX),
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

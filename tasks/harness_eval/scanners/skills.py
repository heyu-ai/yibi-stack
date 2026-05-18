"""D4 scanner：Skills & Commands（機械分 6/10）。"""

from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 6
_REQUIRED_KEYS = {"name", "type", "scope", "description"}


def _has_valid_frontmatter(skill_md: Path) -> bool:
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError:
        return False
    if not content.startswith("---"):
        return False
    parts = content.split("---", 2)
    if len(parts) < 3:
        return False
    return all(f"{key}:" in parts[1] for key in _REQUIRED_KEYS)


def scan_skills(target_dir: Path) -> MechanicalFinding:
    """掃描 .claude/skills/ 存在性與 frontmatter 完整性。語意分（4 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    skills_dir = target_dir / ".claude" / "skills"
    if not skills_dir.exists():
        findings.append("WARN: .claude/skills/ 不存在")
        return MechanicalFinding(
            dimension="D4",
            label="Skills & Commands",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    skill_mds = list(skills_dir.rglob("SKILL.md"))
    if not skill_mds:
        findings.append("WARN: .claude/skills/ 存在但無任何 SKILL.md")
        return MechanicalFinding(
            dimension="D4",
            label="Skills & Commands",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    score += 3
    findings.append(f".claude/skills/ 存在，共 {len(skill_mds)} 個 skill")

    valid = sum(1 for s in skill_mds if _has_valid_frontmatter(s))
    if valid == len(skill_mds):
        score += 3
        findings.append(f"所有 {valid} 個 skill frontmatter 完整")
    elif valid > 0:
        score += 1
        findings.append(f"WARN: {valid}/{len(skill_mds)} skill frontmatter 完整")
    else:
        findings.append("WARN: 所有 skill 缺少完整 frontmatter（name/type/scope/description）")

    for s in skill_mds[:3]:
        semantic_targets.append(str(s))

    return MechanicalFinding(
        dimension="D4",
        label="Skills & Commands",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

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
    """掃描 skills 目錄存在性與 frontmatter 完整性。語意分（4 分）由 agent 補充。

    搜尋策略：
    1. 優先 .claude/skills/（消費者 repo：從 yibi-stack 安裝的 symlink）
    2. fallback 到 skills/（源碼 repo：ainization-skill / yibi-stack 本身）
    """
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    claude_skills_dir = target_dir / ".claude" / "skills"
    root_skills_dir = target_dir / "skills"
    claude_exists = claude_skills_dir.exists()
    root_exists = root_skills_dir.exists()

    skill_mds: list[Path] = []
    active_dir: Path | None = None

    if claude_exists:
        found = list(claude_skills_dir.rglob("SKILL.md"))
        if found:
            skill_mds = found
            active_dir = claude_skills_dir

    if not skill_mds and root_exists:
        found = list(root_skills_dir.rglob("SKILL.md"))
        if found:
            skill_mds = found
            active_dir = root_skills_dir

    if active_dir is None:
        if claude_exists or root_exists:
            findings.append("WARN: skills 目錄存在但無任何 SKILL.md")
        else:
            findings.append("WARN: .claude/skills/ 不存在")
        return MechanicalFinding(
            dimension="D4",
            label="Skills & Commands",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    dir_label = ".claude/skills/" if active_dir == claude_skills_dir else "skills/"
    score += 3
    findings.append(f"{dir_label} 存在，共 {len(skill_mds)} 個 skill")
    if active_dir != claude_skills_dir:
        findings.append(f"（源碼 repo 模式：技能從 {dir_label} 掃描）")

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

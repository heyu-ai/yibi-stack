"""D4 scanner：Skills & Commands（機械分 6/10）。"""

from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 6
_REQUIRED_KEYS = {"name", "type", "scope", "description"}

# skills 可能的位置：.claude/skills/（symlink 安裝目標）或 skills/（source repo）
_SKILL_DIRS = [".claude/skills", "skills"]


def _has_valid_frontmatter(skill_md: Path) -> bool:
    try:
        with skill_md.open(encoding="utf-8") as f:
            head = f.read(512)
    except OSError:
        return False
    if not head.startswith("---"):
        return False
    parts = head.split("---", 2)
    if len(parts) < 3:
        return False
    return all(f"{key}:" in parts[1] for key in _REQUIRED_KEYS)


def _find_skill_mds(target_dir: Path) -> tuple[list[Path], str]:
    """在多個可能位置搜尋 SKILL.md，回傳（檔案清單, 來源描述）。"""
    for rel_dir in _SKILL_DIRS:
        skills_dir = target_dir / rel_dir
        if not skills_dir.exists():
            continue
        skill_mds = [
            p for p in skills_dir.rglob("SKILL.md")
            if not any(part.startswith(".") and part not in {".claude"} for part in p.parts)
        ]
        if skill_mds:
            return skill_mds, rel_dir
    return [], ""


def scan_skills(target_dir: Path) -> MechanicalFinding:
    """掃描 skills/ 存在性與 frontmatter 完整性。語意分（4 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    skill_mds, source_dir = _find_skill_mds(target_dir)

    if not skill_mds:
        dirs_checked = ", ".join(_SKILL_DIRS)
        findings.append(f"WARN: 找不到 SKILL.md（已查詢：{dirs_checked}）")
    else:
        score += 2
        findings.append(f"skills/ 存在於 {source_dir}，共 {len(skill_mds)} 個 skill")

        valid = sum(1 for s in skill_mds if _has_valid_frontmatter(s))
        if valid == len(skill_mds):
            score += 2
            findings.append(f"所有 {valid} 個 skill frontmatter 完整（name/type/scope/description）")
        elif valid > 0:
            score += 1
            findings.append(f"WARN: {valid}/{len(skill_mds)} skill frontmatter 完整")
        else:
            findings.append("WARN: 所有 skill 缺少完整 frontmatter")

        for s in skill_mds[:3]:
            semantic_targets.append(str(s))

    # commands/ 目錄（slash command 快捷鍵）
    commands_dir = target_dir / ".claude" / "commands"
    if commands_dir.exists():
        cmds = list(commands_dir.glob("*.md"))
        score += 2
        findings.append(f".claude/commands/ 存在（{len(cmds)} 個 slash command）")
    else:
        findings.append("WARN: .claude/commands/ 不存在（slash command 未設定）")

    return MechanicalFinding(
        dimension="D4",
        label="Skills & Commands",
        score=min(score, _MECH_MAX),
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

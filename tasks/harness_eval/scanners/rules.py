"""D7 scanner：Rules 文件 & 路徑作用域（機械分 7/15）。"""

import re
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 7
_NUMBER_RE = re.compile(r"^\d{2}-")


def _has_glob_frontmatter(md_file: Path) -> bool:
    try:
        content = md_file.read_text(encoding="utf-8")
    except OSError:
        return False
    if not content.startswith("---"):
        return False
    parts = content.split("---", 2)
    return len(parts) >= 3 and "glob:" in parts[1]


def scan_rules(target_dir: Path) -> MechanicalFinding:
    """掃描 .claude/rules/ 結構品質。語意分（8 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    rules_dir = target_dir / ".claude" / "rules"
    rule_files = list(rules_dir.glob("*.md")) if rules_dir.exists() else []

    if not rule_files:
        findings.append("WARN: .claude/rules/ 不存在或無 .md 規則檔")
        return MechanicalFinding(
            dimension="D7",
            label="Rules 文件 & 路徑作用域",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    score += 2
    findings.append(f".claude/rules/ 存在，共 {len(rule_files)} 個規則檔")
    for f in rule_files[:5]:
        semantic_targets.append(str(f))

    numbered = [f for f in rule_files if _NUMBER_RE.match(f.name)]
    if numbered:
        score += 2
        findings.append(f"規則有編號分類（{len(numbered)}/{len(rule_files)} 個有 NN- 前綴）")
    else:
        findings.append("WARN: 規則未使用編號前綴（建議 01-*.md 格式）")

    has_glob = any(_has_glob_frontmatter(f) for f in rule_files)
    if has_glob:
        score += 3
        findings.append("規則含 glob frontmatter（path-scoped auto-load）")
    elif len(rule_files) >= 3:
        score += 2
        findings.append("規則使用 topic 命名分類（yibi-stack 編號 + 交叉引用模式）")

    skills_dir = target_dir / ".claude" / "skills"
    has_prune = skills_dir.exists() and any(
        "prune" in d.name.lower() for d in skills_dir.iterdir() if d.is_dir()
    )
    if has_prune:
        score += 2
        findings.append("規則維護循環存在（prune skill）")
    else:
        findings.append("WARN: 未找到 rule prune 機制")

    return MechanicalFinding(
        dimension="D7",
        label="Rules 文件 & 路徑作用域",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

"""D1 scanner：CLAUDE.md 品質（機械分 6/12）。"""

from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 6


def scan_claude_md(target_dir: Path) -> MechanicalFinding:
    """掃描 target_dir 下的 CLAUDE.md 存在性與行數。語意分（6 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    project_md = target_dir / "CLAUDE.md"

    if project_md.exists():
        score += 3
        findings.append(f"CLAUDE.md 存在：{project_md}")
        semantic_targets.append(str(project_md))

        try:
            lines = len(project_md.read_text(encoding="utf-8").splitlines())
            if lines <= 200:
                score += 3
                findings.append(f"行數 {lines} <= 200（OK）")
            else:
                findings.append(f"WARN: 行數 {lines} > 200（Anthropic 建議上限）")
        except OSError as e:
            findings.append(f"WARN: CLAUDE.md 無法讀取行數：{e}")
    else:
        findings.append("WARN: CLAUDE.md 不存在（project root 未找到）")

    return MechanicalFinding(
        dimension="D1",
        label="CLAUDE.md 品質",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

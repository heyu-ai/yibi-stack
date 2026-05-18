"""D6 scanner stub。"""

from pathlib import Path

from ..models import MechanicalFinding


def scan_git(target_dir: Path) -> MechanicalFinding:
    return MechanicalFinding(dimension="D6", label="Git 工作流程 & Commit", score=0, max_score=6)

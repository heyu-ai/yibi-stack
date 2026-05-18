"""D4 scanner stub。"""

from pathlib import Path

from ..models import MechanicalFinding


def scan_skills(target_dir: Path) -> MechanicalFinding:
    return MechanicalFinding(dimension="D4", label="Skills & Commands", score=0, max_score=6)

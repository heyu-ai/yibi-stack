"""D8 scanner stub。"""

from pathlib import Path

from ..models import MechanicalFinding


def scan_security(target_dir: Path) -> MechanicalFinding:
    return MechanicalFinding(dimension="D8", label="Security & Trust", score=0, max_score=8)

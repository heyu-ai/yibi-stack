"""D5 scanner stub。"""

from pathlib import Path

from ..models import MechanicalFinding


def scan_testing(target_dir: Path) -> MechanicalFinding:
    return MechanicalFinding(dimension="D5", label="Testing & CI 整合", score=0, max_score=7)

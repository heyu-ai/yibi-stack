"""D3 scanner stub。"""

from pathlib import Path

from ..models import MechanicalFinding


def scan_settings(target_dir: Path) -> MechanicalFinding:
    return MechanicalFinding(dimension="D3", label="Settings & 權限", score=0, max_score=6)

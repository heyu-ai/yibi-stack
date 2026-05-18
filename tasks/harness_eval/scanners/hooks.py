"""D2 scanner stub。"""

from pathlib import Path

from ..models import MechanicalFinding


def scan_hooks(target_dir: Path) -> MechanicalFinding:
    return MechanicalFinding(dimension="D2", label="Hooks 設定", score=0, max_score=12)

"""D7 scanner stub。"""

from pathlib import Path

from ..models import MechanicalFinding


def scan_rules(target_dir: Path) -> MechanicalFinding:
    return MechanicalFinding(dimension="D7", label="Rules 文件 & 路徑作用域", score=0, max_score=7)

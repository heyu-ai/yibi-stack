"""共用路徑常數：PROJECT_ROOT、RUNTIME_DIR。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"

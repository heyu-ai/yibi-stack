"""skill_eval 設定：fixture 探索與載入、baseline 讀寫。"""

import json
from pathlib import Path

from tasks._paths import PROJECT_ROOT, RUNTIME_DIR

from .models import TriggerEvalFixture

SKILLS_DIR = PROJECT_ROOT / "skills"
BASELINE_PATH = RUNTIME_DIR / "skill_eval_baseline.json"


def fixture_path(skill: str, skills_dir: Path | None = None) -> Path:
    """回傳指定 skill 的 trigger_eval.json 路徑。"""
    root = skills_dir or SKILLS_DIR
    return root / skill / "trigger_eval.json"


def load_fixture(skill: str, skills_dir: Path | None = None) -> TriggerEvalFixture:
    """載入並驗證單一 skill 的 fixture；缺檔或格式錯誤時抛 RuntimeError。"""
    path = fixture_path(skill, skills_dir)
    if not path.is_file():
        raise RuntimeError(f"找不到 fixture：{path}（請在 skill 旁建立 trigger_eval.json）")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"讀取 fixture 失敗：{path}") from e
    return TriggerEvalFixture.model_validate(data)


def discover_fixtures(skills_dir: Path | None = None) -> list[str]:
    """列出所有含 trigger_eval.json 的 skill 名稱（依名稱排序）。"""
    root = skills_dir or SKILLS_DIR
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if (entry / "trigger_eval.json").is_file())


def load_baseline(path: Path | None = None) -> dict[str, dict[str, float]]:
    """載入 baseline（skill -> class -> pass_rate）；檔案不存在回傳空 dict。"""
    p = path or BASELINE_PATH
    if not p.is_file():
        return {}
    try:
        data: dict[str, dict[str, float]] = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"讀取 baseline 失敗：{p}") from e
    return data


def save_baseline(baseline: dict[str, dict[str, float]], path: Path | None = None) -> Path:
    """寫入 baseline 檔並回傳路徑。"""
    p = path or BASELINE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p

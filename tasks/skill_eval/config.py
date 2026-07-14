"""skill_eval 設定：fixture 探索與載入、baseline 讀寫。"""

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, RootModel, ValidationError

from tasks._paths import PROJECT_ROOT, RUNTIME_DIR

from .models import TriggerEvalFixture, TriggerPromptClass

SKILLS_DIR = PROJECT_ROOT / "skills"
PLUGINS_DIR = PROJECT_ROOT / "plugins"
BASELINE_PATH = RUNTIME_DIR / "skill_eval_baseline.json"


class _BaselineFile(RootModel[dict[str, dict[TriggerPromptClass, float]]]):
    """baseline 檔的形狀驗證：skill -> class -> pass_rate（0.0~1.0）。

    **class key 綁 TriggerPromptClass 而非裸 str**：compare_baseline 以
    `skill_base.get(str(score.cls))` 查表，查無即 `if base is None: continue`——所以一個
    錯字 key（`negatve`）會讓該類靜默離開 gate，方向比值域錯誤更危險（靜默放行 vs 報錯）。
    手改壞的檔案正是錯字的來源，故 key 也必須驗。

    pass_rate 是比率，值域外（負數、>1）代表檔案已損壞或被手改壞，不應被當成有效基準。
    """

    root: dict[str, dict[TriggerPromptClass, Annotated[float, Field(ge=0.0, le=1.0)]]]


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
    """列出 skills/ 底下所有含 trigger_eval.json 的 skill 名稱（依名稱排序）。

    只涵蓋 skills/<name>/（含 symlink 到 plugin 的全域 skill），與 load_fixture 的
    name-based 解析一致。**未** symlink 到 skills/ 的 plugin-only fixture 不在此列——
    用 orphan_plugin_fixtures() 偵測那些會被漏掉的檔案，由 CLI 以 [WARN] 顯式回報，
    避免 --all 靜默漏評（見 lint_skill_overlap.py 的 plugins/** 掃描先例）。
    """
    root = skills_dir or SKILLS_DIR
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if (entry / "trigger_eval.json").is_file())


def orphan_plugin_fixtures(
    skills_dir: Path | None = None, plugins_dir: Path | None = None
) -> list[Path]:
    """列出 plugins/ 底下未經 skills/ symlink 觸及的 trigger_eval.json（--all 會漏掉的）。

    以 realpath 判斷是否已被 skills/ 的某個 entry（含 symlink）涵蓋；未涵蓋者即 orphan。
    plugins glob 用 `**`（rule 02：`*` 不跨 `/`，會漏巢狀 sub-skill）。
    """
    root = skills_dir or SKILLS_DIR
    pdir = plugins_dir or PLUGINS_DIR
    reachable: set[Path] = set()
    if root.is_dir():
        for entry in root.iterdir():
            fixture = entry / "trigger_eval.json"
            if fixture.is_file():
                reachable.add(fixture.resolve())
    if not pdir.is_dir():
        return []
    orphans: list[Path] = []
    for fixture in sorted(pdir.glob("*/skills/**/trigger_eval.json")):
        if fixture.resolve() not in reachable:
            orphans.append(fixture)
    return orphans


def load_baseline(path: Path | None = None) -> dict[str, dict[str, float]]:
    """載入 baseline（skill -> class -> pass_rate）；檔案不存在回傳空 dict。

    載入後強制驗證形狀與 class key（rule 05：本模組其他 config 皆走 model_validate）。
    未驗證時，`null` 值、值域外的數字、以及錯字的 class key（`negatve`）都會與「該類別無
    baseline」走同一條 `if base is None: continue`，讓 0.00 的 pass rate 靜默回報無回歸；
    非 dict 形狀則會在 compare_baseline 拋出 raw traceback 而非 [FAIL]。

    回傳的 key 是 TriggerPromptClass（StrEnum），與其字串值同 hash，故 compare_baseline
    的 `skill_base.get(str(score.cls))` 查找不受影響。
    """
    p = path or BASELINE_PATH
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"讀取 baseline 失敗：{p}") from e
    try:
        validated = _BaselineFile(root=data).root
    except ValidationError as e:
        raise RuntimeError(
            f"baseline 格式錯誤：{p}（應為 skill -> direct/indirect/negative -> 0.0~1.0 浮點數）"
        ) from e
    return {
        skill: {str(cls): rate for cls, rate in scores.items()}
        for skill, scores in validated.items()
    }


def save_baseline(baseline: dict[str, dict[str, float]], path: Path | None = None) -> Path:
    """寫入 baseline 檔並回傳路徑。"""
    p = path or BASELINE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p

"""skill_eval 設定：fixture 探索與載入、baseline 讀寫。"""

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, RootModel, ValidationError

from tasks._paths import PROJECT_ROOT

from .models import TriggerEvalFixture, TriggerPromptClass

SKILLS_DIR = PROJECT_ROOT / "skills"
PLUGINS_DIR = PROJECT_ROOT / "plugins"
# baseline 進 git（不放 .runtime/）：gitignore 掉的 baseline 讓回歸 gate 在結構上不可能存在——
# 每次 clone / CI runner 都讀到空 baseline，compare_baseline 一律走 `base is None` 略過，
# 於是 0.00 的 pass rate 也回報無回歸。issue #220。
BASELINE_PATH = PROJECT_ROOT / "tasks" / "skill_eval" / "baselines" / "trigger_baseline.json"


class _BaselineFile(RootModel[dict[str, dict[TriggerPromptClass, float]]]):
    """baseline 檔的形狀驗證：skill -> class -> pass_rate（0.0~1.0）。

    **class key 綁 TriggerPromptClass 而非裸 str**：compare_baseline 以
    `skill_base.get(str(score.cls))` 查表，查無即 `if base is None: continue`——所以一個
    錯字 key（`negatve`）會讓該類靜默離開 gate，方向比值域錯誤更危險（靜默放行 vs 報錯）。
    手改壞的檔案正是錯字的來源，故 key 也必須驗。

    pass_rate 是比率，值域外（負數、>1）代表檔案已損壞或被手改壞，不應被當成有效基準。
    """

    root: dict[str, dict[TriggerPromptClass, Annotated[float, Field(ge=0.0, le=1.0)]]]


def resolve_fixture_index(
    skills_dir: Path | None = None, plugins_dir: Path | None = None
) -> dict[str, Path]:
    """建立 skill 名稱 -> trigger_eval.json 路徑索引，聯集 skills/ 第一層與 plugins/ 全深度。

    只掃 skills/ 會漏掉 plugin-only skill：12 個 plugin skill 刻意沒有 skills/ symlink
    （`spectra-amplifier` 是明確被降級為 plugin-only 的先例）。此索引最初上線時 repo
    唯一一份 fixture（`plugins/dev-cycle/skills/pr-cycle-fast/`）正躺在其中之一，使得
    `--all` 曾經掃不到任何東西。補 symlink 不是解法——那會違反那些 skill 被降級的理由。

    plugins glob 用 `**`（rule 02：`*` 不跨 `/`，會漏 mycelium 的巢狀 sub-skill）。
    skills/ 優先：symlink 與其 target 以 realpath 去重，同一個實體檔只留 skills/ 這個名字。

    名稱衝突（兩個**不同**實體檔同名，如 plugin A 與 plugin B 各有一個 `recap/`）一律
    RuntimeError：靜默留下其中一個會讓另一個永久離開 gate，而 baseline 是按名字存的，
    兩者還會互相覆寫彼此的基準。
    """
    root = skills_dir or SKILLS_DIR
    pdir = plugins_dir or PLUGINS_DIR

    index: dict[str, Path] = {}
    seen: dict[str, Path] = {}  # name -> realpath，用來判斷是否為同一實體檔

    def _add(name: str, fixture: Path) -> None:
        real = fixture.resolve()
        prior = seen.get(name)
        if prior is not None:
            if prior == real:
                return  # symlink 與 target 指向同一份，保留先登記的（skills/ 優先）
            raise RuntimeError(
                f"fixture 名稱衝突：`{name}` 同時對應 {index[name]} 與 {fixture}；"
                "兩者是不同的實體檔，baseline 依名稱存放會互相覆寫。請改名其中之一"
            )
        seen[name] = real
        index[name] = fixture

    if root.is_dir():
        for entry in sorted(root.iterdir()):
            fixture = entry / "trigger_eval.json"
            if fixture.is_file():
                _add(entry.name, fixture)
    if pdir.is_dir():
        for fixture in sorted(pdir.glob("*/skills/**/trigger_eval.json")):
            _add(fixture.parent.name, fixture)
    return index


def load_fixture(
    skill: str, skills_dir: Path | None = None, plugins_dir: Path | None = None
) -> TriggerEvalFixture:
    """載入並驗證單一 skill 的 fixture；缺檔或格式錯誤時抛 RuntimeError。"""
    path = resolve_fixture_index(skills_dir, plugins_dir).get(skill)
    if path is None:
        raise RuntimeError(
            f"找不到 skill `{skill}` 的 fixture（skills/ 與 plugins/*/skills/ 底下皆無）；"
            "請在該 skill 的 SKILL.md 旁建立 trigger_eval.json"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"讀取 fixture 失敗：{path}") from e
    return TriggerEvalFixture.model_validate(data)


def discover_fixtures(skills_dir: Path | None = None, plugins_dir: Path | None = None) -> list[str]:
    """列出所有含 trigger_eval.json 的 skill 名稱（依名稱排序），涵蓋 skills/ 與 plugins/。"""
    return sorted(resolve_fixture_index(skills_dir, plugins_dir))


def load_baseline(path: Path | None = None) -> dict[str, dict[str, float]]:
    """載入 baseline（skill -> class -> pass_rate）；檔案不存在回傳空 dict。

    載入後強制驗證形狀與 class key（rule 05：本模組其他 config 皆走 model_validate）。
    未驗證時有三條路殊途同歸，都讓 0.00 的 pass rate 靜默回報無回歸：
    `null` 值與錯字的 class key（`negatve`）查表得 None，走 `if base is None: continue`；
    值域外的數字（如 -1.0）查得到、不是 None，改讓 `pass_rate < base - tol` 恆為 False。
    非 dict 形狀則會在 compare_baseline 拋出 raw traceback 而非 [FAIL]。

    驗證後的 class key 是 TriggerPromptClass；下方轉回 str 以符合回傳型別（dict key 不可
    協變，mypy 會擋）。轉換純為型別對齊，非行為所需：StrEnum 與其字串值同 hash，
    compare_baseline 的 `skill_base.get(str(score.cls))` 兩種型別都查得到。
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


def save_baseline(
    baseline: dict[str, dict[str, float]], path: Path | None = None, merge: bool = False
) -> Path:
    """寫入 baseline 檔並回傳路徑。

    merge=True 時只更新 `baseline` 內出現的 skill，其餘條目原樣保留——`baseline --skill foo`
    過去整檔覆寫，等於把其他所有 skill 的基準一次抹掉，之後每個都變成「無基準」而靜默
    離開 gate（issue #219）。merge=False 為 `--all` 的權威重寫，讓已刪除 fixture 的
    陳舊條目能真的消失。

    寫入後依 key 排序，讓 `git diff` 只顯示真正變動的 skill（dict 插入序會製造假 diff）。
    """
    p = path or BASELINE_PATH
    merged = dict(load_baseline(p)) if merge else {}
    merged.update(baseline)
    ordered = {skill: merged[skill] for skill in sorted(merged)}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p

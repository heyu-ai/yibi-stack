"""gate_eval 設定：oracle 與 fixture 的載入與一致性檢查（stdlib json，不引入 yaml 依賴）。"""

import json
from pathlib import Path

from pydantic import ValidationError

from tasks._paths import PROJECT_ROOT

from .models import (
    DISPUTED,
    ConformanceFixture,
    DispositionOracle,
    FixtureSet,
)

GATE_EVAL_DIR = PROJECT_ROOT / "tasks" / "gate_eval"
FIXTURES_DIR = GATE_EVAL_DIR / "fixtures"
ORACLE_PATH = FIXTURES_DIR / "oracle.json"
FINDINGS_DIR = FIXTURES_DIR / "findings"


def load_oracle(path: Path | None = None) -> DispositionOracle:
    """載入並驗證 disposition oracle；缺檔或格式錯誤即 raise RuntimeError。"""
    p = path or ORACLE_PATH
    if not p.is_file():
        raise RuntimeError(f"找不到 oracle：{p}（請先轉錄 SKILL.md disposition 矩陣）")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"讀取 oracle 失敗：{p}") from e
    try:
        return DispositionOracle.model_validate(data)
    except ValidationError as e:
        raise RuntimeError(f"oracle 格式錯誤：{p}") from e


def load_fixture_file(path: Path) -> ConformanceFixture:
    """載入單一 fixture 檔；缺欄位或期望 disposition 不在列舉內即 raise RuntimeError。"""
    if not path.is_file():
        raise RuntimeError(f"找不到 fixture：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"讀取 fixture 失敗：{path}") from e
    try:
        return ConformanceFixture.model_validate(data)
    except ValidationError as e:
        raise RuntimeError(f"fixture 格式錯誤：{path}") from e


def load_fixtures(findings_dir: Path | None = None) -> FixtureSet:
    """載入目錄下所有 fixture 並做集合層驗證；空集合或退化集合即 raise RuntimeError。"""
    root = findings_dir or FINDINGS_DIR
    if not root.is_dir():
        raise RuntimeError(f"找不到 fixture 目錄：{root}")
    fixtures = [load_fixture_file(p) for p in sorted(root.glob("*.json"))]
    try:
        return FixtureSet(fixtures=fixtures)
    except ValidationError as e:
        raise RuntimeError(f"fixture 集合驗證失敗：{e}") from e


def check_fixture_oracle_consistency(fixtures: FixtureSet, oracle: DispositionOracle) -> None:
    """核對每個 fixture 的因子組合在 oracle 中存在，且期望 disposition 與 oracle 一致。

    三種不一致皆 raise RuntimeError 並指名該 fixture，不回退預設、不靜默略過：
    - 因子組合在 oracle 中找不到（fixture factor combination absent from the oracle）
    - oracle 該格為 disputed（runbook 未無歧義定義，無法對其評分）
    - fixture 標註的期望 disposition 與 oracle 不符（驗收對照組一：刻意標錯者須被指名）
    """
    for fx in fixtures.fixtures:
        entry = oracle.lookup(fx.factors)
        if entry is None:
            raise RuntimeError(
                f"fixture {fx.id} 的因子組合 {fx.factors.key()} 在 oracle 中找不到對應項；"
                "中止，不得視為通過"
            )
        if entry.disposition == DISPUTED:
            raise RuntimeError(
                f"fixture {fx.id} 指向 disputed 的 oracle 格 {fx.factors.key()}："
                f"{entry.note}；runbook 未無歧義定義此格，無法評分"
            )
        if str(fx.expected_disposition) != str(entry.disposition):
            raise RuntimeError(
                f"fixture {fx.id} 標註的期望 disposition（{fx.expected_disposition}）"
                f"與 oracle（{entry.disposition}）不符——請修正 fixture 或 oracle"
            )

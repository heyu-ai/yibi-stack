"""gate_eval 的 mutation 驗證與 sunset 協議：fixture 有效性、prune、suite 退場觸發。

mutation 機制對『目標檔』就地改寫再還原，並清除受影響模組樹的快取位元碼、更新來源檔
時間戳（避免以還原前的 bytecode 重跑，CLAUDE.md 血淚）。所有純規則求值不觸碰檔案，可完整單測。
"""

import os
import shutil
from pathlib import Path

from .models import (
    AlertClass,
    FixtureWindowRecord,
    MutationDescriptor,
    PruneAction,
    PruneRecommendation,
    StabilityVerdict,
    SuiteSunsetResult,
    SuiteWindow,
    SunsetTrigger,
)


class MutationAnchorNotFound(RuntimeError):
    """mutation 的 anchor 在目標檔中找不到——代表變更未套用，該次驗證是空的。"""


def apply_mutation(target: Path, mutation: MutationDescriptor, fixture_id: str) -> str:
    """就地套用 mutation，回傳原始內容供還原。

    anchor 找不到即 raise（不記錄存活或被殺）——找不到代表變更未套用，
    繼續跑會得到一個看似有效卻空洞的結論。
    """
    original = target.read_text(encoding="utf-8")
    if mutation.anchor not in original:
        raise MutationAnchorNotFound(
            f"fixture {fixture_id} 的 mutation anchor 在 {target} 中找不到："
            f"{mutation.anchor!r}（變更未套用，中止）"
        )
    mutated = original.replace(mutation.anchor, mutation.replacement, 1)
    target.write_text(mutated, encoding="utf-8")
    return original


def restore_and_invalidate(target: Path, original: str, module_root: Path) -> None:
    """還原目標檔內容，清除 module_root 下所有 __pycache__，並把來源檔 mtime 更新為現在。

    順序無關但三者缺一不可：只還原內容而不清 bytecode，下一輪可能讀到 mutation 版的 .pyc；
    只清 bytecode 而不 bump mtime，CPython 以 (source mtime 秒, size) 判新鮮度時仍可能誤判。
    """
    target.write_text(original, encoding="utf-8")
    if module_root.is_dir():
        for cache_dir in module_root.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)
    os.utime(target, None)  # 設為現在，跨秒使 .pyc 判為過期


def is_effective(before: StabilityVerdict, after: StabilityVerdict) -> bool:
    """fixture 有效 iff 套用其 mutation 使 verdict 由 CONFORMANT 轉為 NONCONFORMANT。

    不以 suite 整體 pass rate 作為有效性訊號——pass rate 無法區分『規則被遵守』與
    『根本沒測到規則』，兩者都呈現為綠燈。
    """
    return before == StabilityVerdict.CONFORMANT and after == StabilityVerdict.NONCONFORMANT


def _resolve_alert(alert: AlertClass) -> AlertClass:
    """未分類的紅燈預設併入假警報（歧義的預設方向偏向 sunset）。"""
    return AlertClass.FALSE if alert == AlertClass.UNCLASSIFIED else alert


def classify_prune(record: FixtureWindowRecord) -> PruneRecommendation:
    """依有效性與窗口內警報歷史，為單一 fixture 產出 prune 建議。"""
    fid = record.fixture_id
    if not record.mutation_kills:
        return PruneRecommendation(
            fixture_id=fid,
            action=PruneAction.REMOVE,
            reason="mutation 無法使其轉紅——沒有測到它宣稱測的規則",
        )
    if not record.alerts:
        return PruneRecommendation(
            fixture_id=fid,
            action=PruneAction.DEMOTE,
            reason="mutation 仍能使其轉紅但從未紅過——保留並降至每季執行",
        )
    resolved = [_resolve_alert(a) for a in record.alerts]
    if any(a == AlertClass.TRUE for a in resolved):
        return PruneRecommendation(
            fixture_id=fid,
            action=PruneAction.KEEP,
            reason="窗口內曾因真實回歸而紅——保留於常規頻率",
        )
    # 全為假警報（含未分類）
    if record.false_alarm_repaired_once:
        return PruneRecommendation(
            fixture_id=fid,
            action=PruneAction.REMOVE,
            reason="全為假警報且已修正過一次——第二次即移除",
        )
    return PruneRecommendation(
        fixture_id=fid,
        action=PruneAction.REPAIR,
        reason="全為假警報且第一次——修正一次",
    )


def evaluate_suite_sunset(
    windows: list[SuiteWindow], superseded_by_code: bool
) -> SuiteSunsetResult:
    """求值三個 suite 層 sunset 觸發條件；任一成立即回報進入移除評估。

    windows 依時間排序（最新在末），且**僅**由已記錄在檢視 issue 的窗口建構——未記錄的
    窗口視為未發生，不得計入『連續兩窗口無警報』。
    """
    triggers: list[SunsetTrigger] = []
    notes: list[str] = []

    if (
        len(windows) >= 2
        and not windows[-1].any_fixture_alerted
        and not windows[-2].any_fixture_alerted
    ):
        triggers.append(SunsetTrigger.NO_ALERTS_TWO_WINDOWS)
        notes.append("連續兩個已記錄窗口所有存活 fixture 皆未紅——已無回歸可偵測")

    if windows and windows[-1].false_alarms > windows[-1].true_alerts:
        triggers.append(SunsetTrigger.NOISE_DOMINANT)
        notes.append("最近窗口假警報多於真警報——淨負面，會訓練使用者忽略紅燈")

    if superseded_by_code:
        triggers.append(SunsetTrigger.SUPERSEDED_BY_CODE)
        notes.append("disposition 判定已移入程式並由 pytest 涵蓋——屬被取代而非失敗")

    return SuiteSunsetResult(due_for_removal=bool(triggers), triggers=triggers, notes=notes)

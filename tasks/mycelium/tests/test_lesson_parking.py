"""Tier 3 lesson parking、recurrence 與 default exclusion 回歸測試。

結構依 rule 09（`class TestXxx` + `<MODULE>-<CATEGORY>-<NUMBER>` docstring ID），
與姊妹功能 `test_lessons_retire.py` 的 DT / ST / CV 分層一致。

**覆蓋面說明（PR #347 mob review）**：初版只測了 parked 排除的四個入口之一
（`show_lessons_typed`），三家 reviewer 各自以 mutation 實證另外三個入口——
`search_lessons_typed` 的 SQL、CLI 兩個 `--include-parked` routing、以及 demotion 側的排除
——刪掉任一個，整套測試照樣全綠。`park_lesson` 四條分支中「同 key 已有未 parked lesson →
拒絕覆寫」那條同樣零覆蓋，而拿掉它會把 confidence 8/9 的 active lesson 夾成 4 並掛 parked，
是一次靜默的可見性損失。以下逐一補齊。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from tasks.mycelium.cli import cli
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.lessons_service import (
    add_lesson,
    finalize_reassessed_lesson,
    park_lesson,
    search_lessons_typed,
    show_lessons_typed,
)
from tasks.mycelium.tier_service import run_promotion_check

_PROJECT = "yibi-stack"
_KEY = "cli-parked-friction"
_INSIGHT = "Original title and description must remain unchanged."


def _lesson(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "project": _PROJECT,
        "type": "pitfall",
        "key": _KEY,
        "insight": _INSIGHT,
        "confidence": 4,
        "source": "inferred",
    }
    data.update(overrides)
    return data


def _cli_add_args(*extra: str) -> list[str]:
    return [
        "lessons",
        "add",
        "--type",
        "pitfall",
        "--key",
        _KEY,
        "--insight",
        _INSIGHT,
        "--confidence",
        "4",
        "--source",
        "inferred",
        "--project",
        _PROJECT,
        *extra,
    ]


def _backdate(db_path: Path, lesson_id: str, days: int) -> None:
    """把 lesson 的 ts 往前推，用來觸發 age-based demotion。"""
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    db = AgentsDB(db_path=db_path)
    db.init_db()
    db.conn.execute("UPDATE lessons SET ts = ? WHERE id = ?", (old, lesson_id))
    db.conn.commit()
    db.close()


class TestParkTransitions:
    """`park_lesson` 的四條分支（AC-1）。"""

    def test_lsn_park_dt_001_initial_park_persists_tags_and_confidence(self, tmp_path: Path):
        """LSN-PARK-DT-001: 首次 park 寫入 parked + recurrence-1 且 confidence 夾到 4"""
        result = park_lesson(_lesson(), db_path=tmp_path / "lessons.db")

        assert result["status"] == "parked"
        assert result["recurrence"] == 1
        row = result["lesson"]
        # `== 4` 而非 `<= 4`：後者在本 fixture 下恆真（`_lesson()` 的 confidence 就是 4），
        # 是一條沒有資訊量的斷言（PR #347 mob review 指出）。
        assert row["confidence"] == 4
        assert set(row["tags"]) >= {"parked", "recurrence-1"}

    def test_lsn_park_dt_002_db_layer_clamps_confidence_above_four(self, tmp_path: Path):
        """LSN-PARK-DT-002: 繞過 service 前置檢查時，DB 層仍把 confidence 夾到 4"""
        # service 對 > 4 是 hard reject，所以 db 的兩處夾取要直接呼叫 DB 才測得到。
        db = AgentsDB(db_path=tmp_path / "lessons.db")
        db.init_db()
        try:
            from tasks.mycelium.models import LessonRecord

            result = db.park_lesson(LessonRecord.model_validate(_lesson(confidence=9)))
        finally:
            db.close()
        assert result["lesson"]["confidence"] == 4

    def test_lsn_park_eg_001_dirty_recurrence_tag_does_not_skew_the_counter(self, tmp_path: Path):
        """LSN-PARK-EG-001: 傳入自帶 recurrence-N 髒 tag 時，計數仍從 1 起算

        `park_lesson` 是 public service，`record_data` 可含 `tags`。若初次 park 只濾掉字面上的
        `recurrence-1`，一個自帶 `recurrence-5` 的 record 會讓兩個 tag 並存，下一次呼叫的
        `max(recurrence_values)` 讀到 5，recurrence 靜默跳號。
        """
        db_path = tmp_path / "lessons.db"
        first = park_lesson(_lesson(tags=["recurrence-5", "unrelated"]), db_path=db_path)

        assert first["recurrence"] == 1
        tags = first["lesson"]["tags"]
        assert "recurrence-5" not in tags
        assert "recurrence-1" in tags
        assert "unrelated" in tags, "非 recurrence 的既有 tag 不該被誤刪"

        second = park_lesson(_lesson(), db_path=db_path)
        assert second["recurrence"] == 2, "計數應從 1 遞增到 2，而非受髒 tag 影響"

    def test_lsn_park_dt_003_second_occurrence_unparks_and_preserves_text(self, tmp_path: Path):
        """LSN-PARK-DT-003: 同 key 再現 bump recurrence 到 2、解除 park、原文不被覆寫"""
        db_path = tmp_path / "lessons.db"
        first = park_lesson(_lesson(), db_path=db_path)
        second = park_lesson(
            _lesson(insight="A later summary must not overwrite the original."),
            db_path=db_path,
        )

        assert second["id"] == first["id"]
        assert second["status"] == "reassess"
        assert second["recurrence"] == 2
        assert "parked" not in second["lesson"]["tags"]
        assert second["lesson"]["insight"] == _INSIGHT

    def test_lsn_park_dt_004_repark_after_failed_reassessment_does_not_double_bump(
        self, tmp_path: Path
    ):
        """LSN-PARK-DT-004: 重評仍為 Tier 3 時只重套 parked，不再次 bump recurrence"""
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)
        park_lesson(_lesson(), db_path=db_path)
        result = park_lesson(_lesson(), db_path=db_path)

        assert result["status"] == "parked"
        assert result["recurrence"] == 2
        assert set(result["lesson"]["tags"]) >= {"parked", "recurrence-2"}

    def test_lsn_park_dt_005_refuses_to_overwrite_an_unparked_lesson(self, tmp_path: Path):
        """LSN-PARK-DT-005: 同 key 已有未 parked lesson 時拒絕覆寫，且原 row 不被改動

        這條守衛是唯一擋住「把已驗證的 Tier 1/2 lesson 打成 Tier 3」的東西。拿掉它，
        `UPDATE ... confidence = MIN(confidence, 4)` 會把 confidence 9 夾成 4 並掛上 parked，
        於是該 lesson 從 show / search / tier promotion 的預設查詢中消失——靜默的可見性損失。
        """
        db_path = tmp_path / "lessons.db"
        added = add_lesson(_lesson(confidence=9, source="cross-model"), db_path=db_path)

        with pytest.raises(RuntimeError, match="拒絕覆寫"):
            park_lesson(_lesson(), db_path=db_path)

        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.get_lesson(str(added["id"]))
        db.close()
        assert row is not None
        assert row["confidence"] == 9, "rollback 失效：既有 lesson 的 confidence 被夾了"
        assert "parked" not in row["tags"], "rollback 失效：既有 lesson 被掛上 parked"

    def test_lsn_park_vl_001_service_rejects_confidence_above_four(self, tmp_path: Path):
        """LSN-PARK-VL-001: service 層對 confidence > 4 直接 reject（非 clamp）"""
        with pytest.raises(ValueError, match="confidence"):
            park_lesson(_lesson(confidence=5), db_path=tmp_path / "lessons.db")


class TestParkedRecallExclusion:
    """AC-2 的排除面——show / search 兩條 recall 路徑各自獨立實作，必須各自測。"""

    def test_lsn_park_st_001_show_excludes_parked_unless_requested(self, tmp_path: Path):
        """LSN-PARK-ST-001: show_lessons_typed 預設排除 parked，--include-parked 可納入"""
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)

        assert show_lessons_typed(project=_PROJECT, include_legacy=False, db_path=db_path) == []
        visible = show_lessons_typed(
            project=_PROJECT, include_legacy=False, include_parked=True, db_path=db_path
        )
        assert len(visible) == 1
        assert "parked" in visible[0]["tags"]

    def test_lsn_park_st_002_search_excludes_parked_unless_requested(self, tmp_path: Path):
        """LSN-PARK-ST-002: search_lessons_typed 預設排除 parked，--include-parked 可納入

        search 的排除是 db 層**另一處獨立 SQL**（不是 show 那處）。初版只測 show，
        刪掉 search 那兩行時整套測試全綠（mob review 以 anchor 計數確認突變確實套用 14 次）。
        """
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)

        assert (
            search_lessons_typed(
                query="Original", project=_PROJECT, include_legacy=False, db_path=db_path
            )
            == []
        )
        visible = search_lessons_typed(
            query="Original",
            project=_PROJECT,
            include_legacy=False,
            include_parked=True,
            db_path=db_path,
        )
        assert len(visible) == 1
        assert "parked" in visible[0]["tags"]


class TestParkedTierExclusion:
    """AC-2 的 promotion 面——升 hot 與降 cold 是兩條分支，delta spec 兩者都要求排除。"""

    def test_lsn_park_st_003_promotion_skips_parked(self, tmp_path: Path):
        """LSN-PARK-ST-003: parked lesson 的 access_count 達 3 也不升 hot"""
        db_path = tmp_path / "lessons.db"
        parked = park_lesson(_lesson(), db_path=db_path)
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.conn.execute("UPDATE lessons SET access_count = 3 WHERE id = ?", (parked["id"],))
        db.conn.commit()
        db.close()

        result = run_promotion_check(db_path=db_path)

        assert result.promoted_to_hot == 0
        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.get_lesson(str(parked["id"]))
        db.close()
        assert row is not None
        assert row["tier"] == "working"

    def test_lsn_park_st_004_demotion_also_skips_parked(self, tmp_path: Path):
        """LSN-PARK-ST-004: parked lesson 超過 90 天且 access_count=0 也不降 cold

        delta spec 明文要求「the same exclusion MUST apply to the cold / archival demotion
        transitions」。把 parked 過濾從 `_fetch_non_archival` 移到升 hot 分支時，
        升 hot 測試仍綠但這條會紅——兩條分支必須各自 pin（mob review 實證）。
        """
        db_path = tmp_path / "lessons.db"
        parked = park_lesson(_lesson(), db_path=db_path)
        _backdate(db_path, str(parked["id"]), days=200)

        result = run_promotion_check(db_path=db_path)

        assert result.demoted_to_cold == 0
        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.get_lesson(str(parked["id"]))
        db.close()
        assert row is not None
        assert row["tier"] == "working"


class TestReassessHandoff:
    """reassess 通過 Tier 1/2 之後的收尾——runbook Tier 3 流程第 4 步。"""

    def test_lsn_park_st_005_plain_add_after_reassess_leaves_an_orphan_in_promotion(
        self, tmp_path: Path
    ):
        """LSN-PARK-ST-005: 只跑一般 add 會留下孤兒列，且它會進 tier promotion

        這條**釘住缺陷本身**（現況為真），讓下一條的修法有對照。reassess 已把舊列的 parked
        拿掉，而 `add_lesson` 是無條件 INSERT 新 UUID——於是同 key 兩列，舊列未 parked、
        未 retired，通過 promotion 的三個過濾條件。
        """
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)
        reassessed = park_lesson(_lesson(), db_path=db_path)
        assert reassessed["status"] == "reassess"

        add_lesson(_lesson(confidence=8, source="cross-model"), db_path=db_path)

        db = AgentsDB(db_path=db_path)
        db.init_db()
        rows = db.conn.execute(
            "SELECT id FROM lessons WHERE key = ? AND retired_at IS NULL", (_KEY,)
        ).fetchall()
        db.close()
        assert len(rows) == 2, "前提改變：reassess 後一般 add 不再產生第二列，本測試需重寫"

        from tasks.mycelium import tier_service

        db = AgentsDB(db_path=db_path)
        db.init_db()
        fetched = tier_service._fetch_non_archival(db)  # noqa: SLF001
        db.close()
        assert len(fetched) == 2, "孤兒列應通過 promotion 過濾（缺陷現況）"

    def test_lsn_park_st_006_finalize_upgrades_in_place_without_a_second_row(self, tmp_path: Path):
        """LSN-PARK-ST-006: `finalize` 原地升級同一列，不新增列、原文保留"""
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)
        old_id = str(park_lesson(_lesson(), db_path=db_path)["id"])

        result = finalize_reassessed_lesson(
            old_id, confidence=8, source="cross-model", db_path=db_path
        )

        assert result["id"] == old_id, "應原地升級，不得換 id"
        assert result["lesson"]["confidence"] == 8
        assert result["lesson"]["insight"] == _INSIGHT, "省略 insight 時原文必須逐字保留"

        from tasks.mycelium import tier_service

        db = AgentsDB(db_path=db_path)
        db.init_db()
        rows = db.conn.execute(
            "SELECT id FROM lessons WHERE key = ? AND retired_at IS NULL", (_KEY,)
        ).fetchall()
        fetched = tier_service._fetch_non_archival(db)  # noqa: SLF001
        db.close()
        assert len(rows) == 1, "finalize 不得新增第二列"
        assert len(fetched) == 1, "promotion 只應看到這一列，沒有孤兒"

    def test_lsn_park_st_007_finalize_is_idempotent_on_retry(self, tmp_path: Path):
        """LSN-PARK-ST-007: 重跑 finalize 不新增列——runbook 對失敗的指示就是「重跑 script」

        先前設計的「先 add 後 retire」在此情境下會再 INSERT 一列，讓狀況比修之前更糟
        （Codex 於 R2 與 re-review 兩輪指出，第二輪以「不可重試」為由升為 Critical）。
        """
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)
        old_id = str(park_lesson(_lesson(), db_path=db_path)["id"])

        first = finalize_reassessed_lesson(
            old_id, confidence=8, source="cross-model", db_path=db_path
        )
        second = finalize_reassessed_lesson(
            old_id, confidence=8, source="cross-model", db_path=db_path
        )

        assert first["lesson"]["confidence"] == second["lesson"]["confidence"] == 8
        db = AgentsDB(db_path=db_path)
        db.init_db()
        rows = db.conn.execute("SELECT id FROM lessons WHERE key = ?", (_KEY,)).fetchall()
        db.close()
        assert len(rows) == 1, "重跑 finalize 產生了第二列——冪等性失效"

    def test_lsn_park_dt_006_finalize_refuses_a_lesson_that_is_still_parked(self, tmp_path: Path):
        """LSN-PARK-DT-006: 仍為 parked（尚未 reassess）時 finalize 必須拒絕"""
        db_path = tmp_path / "lessons.db"
        parked = park_lesson(_lesson(), db_path=db_path)

        with pytest.raises(RuntimeError, match="仍為 parked"):
            finalize_reassessed_lesson(
                str(parked["id"]), confidence=8, source="cross-model", db_path=db_path
            )

    def test_lsn_park_dt_007_finalize_refuses_an_arbitrary_active_lesson(self, tmp_path: Path):
        """LSN-PARK-DT-007: 沒有 recurrence tag 的一般 active lesson 不得被 finalize 改動

        compare-and-set 的重點：`finalize` 只能作用在「等待重評結論」的那一列，
        不得變成一個可以任意改寫他人 lesson 的後門。
        """
        db_path = tmp_path / "lessons.db"
        added = add_lesson(_lesson(confidence=9, source="cross-model"), db_path=db_path)

        # confidence 用**合法**的 8：否則會先被 service 的 5-10 下限擋掉，這條就變成在測
        # 下限而不是在測 CAS——測試因錯的理由變綠/變紅都是假驗證。
        with pytest.raises(RuntimeError, match="recurrence ≥ 2"):
            finalize_reassessed_lesson(
                str(added["id"]), confidence=8, source="cross-model", db_path=db_path
            )

        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.get_lesson(str(added["id"]))
        db.close()
        assert row is not None
        assert row["confidence"] == 9, "被拒絕時不得有部分更新"

    def test_lsn_park_dt_008_park_refuses_a_finalized_lesson(self, tmp_path: Path):
        """LSN-PARK-DT-008: finalize 過的 active lesson 不得被後續 --park 從側門夾回 Tier 3

        `finalize` 刻意保留 `recurrence-<n>` tag（拿它當 compare-and-set 前提），於是該列
        變成「未 parked + recurrence≥2 + confidence 8」。`park_lesson` 的
        `elif recurrence >= 2` 分支原本只看 tag 不看 confidence，會把它重新 park 並用
        `MIN(confidence, 4)` 夾成 4——DT-005 宣稱擋住的靜默可見性損失，從側門發生。
        （PR #347 re-review：此缺陷在 finalize 落地前是 latent，落地後變 live。）
        """
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)
        old_id = str(park_lesson(_lesson(), db_path=db_path)["id"])
        finalize_reassessed_lesson(old_id, confidence=8, source="cross-model", db_path=db_path)

        with pytest.raises(RuntimeError, match="拒絕覆寫"):
            park_lesson(_lesson(), db_path=db_path)

        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.get_lesson(old_id)
        db.close()
        assert row is not None
        assert row["confidence"] == 8, "已 finalize 的 lesson 被夾成 Tier 3 信心度"
        assert "parked" not in row["tags"], "已 finalize 的 lesson 被重新掛上 parked"

    def test_lsn_park_vl_002_finalize_rejects_tier_three_confidence(self, tmp_path: Path):
        """LSN-PARK-VL-002: finalize 的 confidence 必須 ≥ 5，不得讓 Tier 3 直接轉 active

        `confidence ≤ 4` 就是 Tier 3 的水位定義。允許 1–4 會讓一筆仍屬 Tier 3 的教訓完全
        不經過 park 就進入一般 recall 與 tier promotion——Evidence Gate 要防的正是這件事。
        （PR #347 Round 2：Codex 提出，lead 實證重現 confidence=2 的 finalize 進了 promotion。）
        """
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)
        rid = str(park_lesson(_lesson(), db_path=db_path)["id"])

        with pytest.raises(ValueError, match="5 到 10"):
            finalize_reassessed_lesson(rid, confidence=2, source="inferred", db_path=db_path)

    def test_lsn_park_dt_009_finalize_requires_proof_of_a_second_park(self, tmp_path: Path):
        """LSN-PARK-DT-009: 只帶 recurrence tag 不足以通過 CAS，必須是 recurrence ≥ 2

        `startswith("recurrence-")` 太鬆：`recurrence-1`、格式壞掉的 tag、甚至外部
        `add_lesson({... "tags": ["recurrence-2"]})` 造出的普通 active lesson 都會通過，
        finalize 就變成「可任意改寫他人 lesson confidence」的後門。
        （PR #347 Round 2：Codex 提出，lead 實證重現——confidence 9 的 active lesson 被改成 1。）
        """
        db_path = tmp_path / "lessons.db"

        # (a) 偽造 recurrence-2 的普通 active lesson：confidence 已 > 4，必須被擋
        forged = add_lesson(
            _lesson(key="forged", confidence=9, source="cross-model", tags=["recurrence-2"]),
            db_path=db_path,
        )
        with pytest.raises(RuntimeError, match="confidence 已 > 4"):
            finalize_reassessed_lesson(
                str(forged["id"]), confidence=8, source="cross-model", db_path=db_path
            )

        # (b) recurrence 只有 1（從未走到第二次 park）：必須被擋
        only_once = add_lesson(
            _lesson(key="once", confidence=4, source="inferred", tags=["recurrence-1"]),
            db_path=db_path,
        )
        with pytest.raises(RuntimeError, match="recurrence ≥ 2"):
            finalize_reassessed_lesson(
                str(only_once["id"]), confidence=8, source="cross-model", db_path=db_path
            )

        db = AgentsDB(db_path=db_path)
        db.init_db()
        row = db.get_lesson(str(forged["id"]))
        db.close()
        assert row is not None
        assert row["confidence"] == 9, "被拒絕時不得有部分更新"

    @pytest.mark.parametrize(
        ("park_source", "final_source", "expected_trusted"),
        [
            ("observed", "user-stated", True),
            ("user-stated", "inferred", False),
        ],
    )
    def test_lsn_park_dt_010_finalize_keeps_trusted_derived_from_source(
        self, tmp_path: Path, park_source: str, final_source: str, expected_trusted: bool
    ):
        """LSN-PARK-DT-010: finalize 改寫 source 時必須同步重算 trusted

        `trusted` 是 `source` 的衍生不變量（`models.py` 的 `_set_trusted`）。finalize 是唯一
        在 `LessonRecord` 之外寫 `source` 的路徑，漏掉重算會讓兩者去同步，**雙向**都有後果：
        user-stated 但 trusted=False 會在 cross-project recall 中隱形；inferred 但
        trusted=True 會被當成可信送給其他 project。兩個方向都要鎖——只鎖一邊等於只證明一半。
        （PR #347 Round 2：test-analyzer 雙向實證。）
        """
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(source=park_source), db_path=db_path)
        rid = str(park_lesson(_lesson(source=park_source), db_path=db_path)["id"])

        result = finalize_reassessed_lesson(rid, confidence=8, source=final_source, db_path=db_path)

        assert result["lesson"]["source"] == final_source
        assert bool(result["lesson"]["trusted"]) is expected_trusted, (
            f"source={final_source} 時 trusted 應為 {expected_trusted}——"
            "trusted 與 source 去同步會影響 cross-project recall"
        )

    def test_lsn_park_st_008_repark_is_the_exit_when_promotion_gate_fails(self, tmp_path: Path):
        """LSN-PARK-ST-008: 重評過 Tier 1/2 但 Promotion Gate 未過時，re-park 是終止轉移

        這條分支若沒有出口，舊列會停在「已解除 park、confidence ≤ 4」的孤兒狀態並重新進入
        recall 與 promotion——與 ST-005 相同的後果，只是入口不同（Codex re-review Critical）。
        """
        db_path = tmp_path / "lessons.db"
        park_lesson(_lesson(), db_path=db_path)
        assert park_lesson(_lesson(), db_path=db_path)["status"] == "reassess"

        # Promotion Gate 未過 -> 不 finalize，改為再跑 --park
        back = park_lesson(_lesson(), db_path=db_path)

        assert back["status"] == "parked"
        assert back["recurrence"] == 2, "re-park 不得再次 bump recurrence"

        from tasks.mycelium import tier_service

        db = AgentsDB(db_path=db_path)
        db.init_db()
        fetched = tier_service._fetch_non_archival(db)  # noqa: SLF001
        db.close()
        assert fetched == [], "放回 parked 之後不應再有任何列進 promotion"


class TestParkCli:
    """CLI 端到端——flag 靜默變成 no-op 時 service 層測試抓不到。"""

    def test_lsn_park_cv_001_add_park_reports_status_and_recurrence(
        self, tmp_path: Path, monkeypatch
    ):
        """LSN-PARK-CV-001: `lessons add --park` 兩次呼叫回報 parked -> reassess"""
        monkeypatch.setenv("MYCELIUM_DB_OVERRIDE", str(tmp_path / "lessons.db"))

        first = CliRunner().invoke(cli, _cli_add_args("--park"), catch_exceptions=False)
        second = CliRunner().invoke(cli, _cli_add_args("--park"), catch_exceptions=False)

        assert first.exit_code == 0
        assert "status=parked recurrence=1" in first.output
        assert second.exit_code == 0
        assert "status=reassess recurrence=2" in second.output

    def test_lsn_park_cv_002_add_park_rejects_skip_if_exists(self, tmp_path: Path, monkeypatch):
        """LSN-PARK-CV-002: `--park` 與 `--skip-if-exists` 併用時乾淨失敗（非 stack trace）"""
        monkeypatch.setenv("MYCELIUM_DB_OVERRIDE", str(tmp_path / "lessons.db"))

        res = CliRunner().invoke(cli, _cli_add_args("--park", "--skip-if-exists"))

        assert res.exit_code == 1
        assert "--park 與 --skip-if-exists 不可同時使用" in res.output
        assert "Traceback" not in res.output

    def test_lsn_park_cv_003_show_include_parked_flag_is_wired(self, tmp_path: Path, monkeypatch):
        """LSN-PARK-CV-003: `lessons show --include-parked` 真的把 parked 帶出來

        把 CLI 的 `or include_parked` 改成 `or False` 時，flag 靜默變成 no-op 且 exit 0
        ——service 層測試抓不到，必須從 CLI 端 pin（mob review 實證）。
        """
        monkeypatch.setenv("MYCELIUM_DB_OVERRIDE", str(tmp_path / "lessons.db"))
        CliRunner().invoke(cli, _cli_add_args("--park"), catch_exceptions=False)

        without = CliRunner().invoke(
            cli, ["lessons", "show", "--project", _PROJECT], catch_exceptions=False
        )
        with_parked = CliRunner().invoke(
            cli,
            ["lessons", "show", "--project", _PROJECT, "--include-parked"],
            catch_exceptions=False,
        )

        assert without.exit_code == 0
        assert _INSIGHT not in without.output
        assert with_parked.exit_code == 0
        assert _INSIGHT in with_parked.output

    def test_lsn_park_cv_004_search_include_parked_flag_is_wired(self, tmp_path: Path, monkeypatch):
        """LSN-PARK-CV-004: `lessons search --include-parked` 真的把 parked 帶出來"""
        monkeypatch.setenv("MYCELIUM_DB_OVERRIDE", str(tmp_path / "lessons.db"))
        CliRunner().invoke(cli, _cli_add_args("--park"), catch_exceptions=False)

        without = CliRunner().invoke(
            cli, ["lessons", "search", "Original", "--project", _PROJECT], catch_exceptions=False
        )
        with_parked = CliRunner().invoke(
            cli,
            ["lessons", "search", "Original", "--project", _PROJECT, "--include-parked"],
            catch_exceptions=False,
        )

        assert without.exit_code == 0
        assert _INSIGHT not in without.output
        assert with_parked.exit_code == 0
        assert _INSIGHT in with_parked.output

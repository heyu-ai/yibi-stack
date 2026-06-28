"""Distill service 測試：harvest / cluster / score / watermark 冪等。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.distill_service import (
    _jaccard,
    _key_prefix,
    _parse_since,
    _tokenize,
    cluster,
    harvest,
    load_watermark,
    run_distill,
    score,
)
from tasks.mycelium.models import DistilledCluster, LessonRecord, LessonSource, LessonType

# 固定「現在」讓 ts / since 計算可重現
NOW = datetime(2026, 6, 1, tzinfo=UTC)


# ─── helper factories ──────────────────────────────────────────────────────


def _make_db(tmp_path: Path) -> AgentsDB:
    db = AgentsDB(db_path=str(tmp_path / "test.db"))
    db.init_db()
    return db


def _insert(
    db: AgentsDB,
    *,
    key: str,
    insight: str,
    confidence: int,
    ltype: LessonType = LessonType.pattern,
    retro_pr: int | None = None,
    skill: str | None = None,
    age_days: float = 1.0,
) -> str:
    ts = (NOW - timedelta(days=age_days)).isoformat()
    rec = LessonRecord(
        project="test",
        type=ltype,
        key=key,
        insight=insight,
        confidence=confidence,
        source=LessonSource.inferred,
        retro_pr=retro_pr,
        skill=skill,
        ts=ts,
    )
    db.insert_lesson(rec)
    return rec.id


def _lesson(
    lesson_id: str,
    *,
    key: str,
    insight: str,
    ltype: str = "pattern",
    confidence: int = 8,
    retro_pr: int | None = None,
    skill: str | None = None,
    age_days: float = 1.0,
) -> dict[str, object]:
    """組一個 harvest 輸出格式的 lesson dict（給 cluster() 直接吃）。"""
    return {
        "id": lesson_id,
        "key": key,
        "type": ltype,
        "insight": insight,
        "confidence": confidence,
        "retro_pr": retro_pr,
        "skill": skill,
        "project": "test",
        "ts": (NOW - timedelta(days=age_days)).isoformat(),
    }


def _cluster_of(
    size: int,
    *,
    prs: list[int],
    avg_confidence: float,
    types: list[str],
    newest_age_days: float = 1.0,
) -> DistilledCluster:
    """直接構造 DistilledCluster 給 score() 門檻測試。"""
    members = [
        {"id": f"id{i}", "ts": (NOW - timedelta(days=newest_age_days)).isoformat()}
        for i in range(size)
    ]
    return DistilledCluster(
        cluster_id=f"cl-test-{size}",
        lesson_ids=[f"id{i}" for i in range(size)],
        member_keys=["bash-cd"],
        types=types,
        retro_prs=prs,
        avg_confidence=avg_confidence,
        representative_insight="x" * 12,
        member_lessons=members,
    )


# ─── 小工具單元測試 ─────────────────────────────────────────────────────────


class TestPrimitives:
    def test_myc_distill_cv_001_parse_since_relative(self) -> None:
        """MYC-DISTILL-CV-001: '<N>d' 解析為相對天數"""
        assert _parse_since("90d", NOW) == NOW - timedelta(days=90)

    def test_myc_distill_cv_002_parse_since_iso(self) -> None:
        """MYC-DISTILL-CV-002: ISO 字串解析（無時區補 UTC）"""
        assert _parse_since("2026-01-01", NOW) == datetime(2026, 1, 1, tzinfo=UTC)

    def test_myc_distill_vl_001_parse_since_invalid(self) -> None:
        """MYC-DISTILL-VL-001: 格式錯誤 raise ValueError"""
        import pytest

        with pytest.raises(ValueError, match="--since 格式錯誤"):
            _parse_since("garbage", NOW)

    def test_myc_distill_eg_001_jaccard_ratios(self) -> None:
        """MYC-DISTILL-EG-001: Jaccard 交集/聯集比例（disjoint / partial / identical / empty）"""
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0
        assert _jaccard({"a", "b", "c"}, {"a", "b", "d"}) == 0.5  # 2 交集 / 4 聯集
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0
        assert _jaccard(set(), {"a"}) == 0.0  # 空集合早退

    def test_myc_distill_eg_002_key_prefix_generic(self) -> None:
        """MYC-DISTILL-EG-002: 泛用前綴回空字串"""
        assert _key_prefix("legacy-foo") == ""
        assert _key_prefix("bash-cd-git") == "bash"

    def test_myc_distill_cv_003_tokenize_cjk_bigram(self) -> None:
        """MYC-DISTILL-CV-003: CJK 取 bigram，ASCII 取 len>=2 word"""
        toks = _tokenize("用 git -C 取代 cd")
        assert "git" in toks
        assert "用g" not in toks  # 跨 ASCII/CJK 不組 bigram
        assert any(len(t) == 2 and "一" <= t[0] <= "鿿" for t in toks)


# ─── harvest 時間視窗 ───────────────────────────────────────────────────────


class TestHarvest:
    def test_myc_distill_dt_001_window_filters_old(self, tmp_path: Path) -> None:
        """MYC-DISTILL-DT-001: since 視窗外的舊 lesson 被濾掉"""
        db = _make_db(tmp_path)
        _insert(db, key="bash-recent", insight="recent bash lesson here", confidence=8, age_days=10)
        _insert(db, key="bash-old", insight="old bash lesson here too", confidence=8, age_days=200)
        db.close()

        result = harvest(since="90d", db_path=str(tmp_path / "test.db"), now=NOW)

        keys = {r["key"] for r in result.lessons}
        assert "bash-recent" in keys
        assert "bash-old" not in keys
        assert result.dropped_unparseable_ts == 0
        assert result.truncated is False

    def test_myc_distill_eg_003_unparseable_ts_counted(self, tmp_path: Path) -> None:
        """MYC-DISTILL-EG-003: ts 無法解析的 lesson 被計入 dropped，不靜默丟失"""
        db = _make_db(tmp_path)
        _insert(db, key="bash-ok", insight="parseable ts lesson here", confidence=8, age_days=2)
        # 直接寫一筆壞 ts 繞過 model 驗證（模擬跨來源髒資料）
        db.conn.execute("UPDATE lessons SET ts = ? WHERE key = ?", ("not-a-timestamp", "bash-ok"))
        _insert(db, key="bash-ok2", insight="another good lesson row", confidence=8, age_days=2)
        db.close()

        result = harvest(since="90d", db_path=str(tmp_path / "test.db"), now=NOW)
        assert result.dropped_unparseable_ts == 1
        assert {r["key"] for r in result.lessons} == {"bash-ok2"}


# ─── cluster ────────────────────────────────────────────────────────────────


class TestCluster:
    def test_myc_distill_dt_002_same_prefix_with_overlap_groups(self) -> None:
        """MYC-DISTILL-DT-002: 同 type + 同前綴 + 有 token 重疊（>=floor）併為一團"""
        lessons = [
            _lesson("a", key="bash-cd-git", insight="use git -C path instead of cd"),
            _lesson("b", key="bash-cd-hook", insight="use git -C to avoid cd breaking hook path"),
        ]
        clusters = cluster(lessons)
        assert len(clusters) == 1
        assert set(clusters[0].lesson_ids) == {"a", "b"}

    def test_myc_distill_dt_002b_same_prefix_zero_overlap_not_grouped(self) -> None:
        """MYC-DISTILL-DT-002b: 同前綴但 token 零重疊不併（避免 grab-bag mega-cluster）"""
        lessons = [
            _lesson("a", key="bash-cd-git", insight="alpha beta gamma delta epsilon"),
            _lesson("b", key="bash-heredoc", insight="omega sigma tau upsilon phi"),
        ]
        clusters = cluster(lessons)
        assert len(clusters) == 2

    def test_myc_distill_dt_005_union_find_transitive(self) -> None:
        """MYC-DISTILL-DT-005: A~B、B~C、A 與 C 不直接相似 -> union-find 仍併為一團"""
        # a~b 與 b~c 各 >=0.34；a~c 僅共享 "common"(0.11) 不直接相似 -> 需靠 union-find 遞移
        lessons = [
            _lesson("a", key="x-1", insight="alpha beta gamma shared common"),
            _lesson("b", key="y-2", insight="gamma shared common delta epsilon"),
            _lesson("c", key="z-3", insight="delta epsilon common zeta eta"),
        ]
        clusters = cluster(lessons)
        assert len(clusters) == 1
        assert set(clusters[0].lesson_ids) == {"a", "b", "c"}

    def test_myc_distill_dt_003_similar_insight_groups(self) -> None:
        """MYC-DISTILL-DT-003: 不同前綴但 token 高度相似仍併團"""
        lessons = [
            _lesson("a", key="x-one", insight="pydantic field validator must raise ValueError"),
            _lesson("b", key="y-two", insight="pydantic field validator should raise ValueError"),
        ]
        clusters = cluster(lessons)
        assert len(clusters) == 1

    def test_myc_distill_dt_004_different_type_not_grouped(self) -> None:
        """MYC-DISTILL-DT-004: type 不同即使前綴相同也不併"""
        lessons = [
            _lesson("a", key="bash-cd", insight="use git -C path instead of cd", ltype="pattern"),
            _lesson("b", key="bash-cd", insight="use git -C path instead of cd", ltype="pitfall"),
        ]
        clusters = cluster(lessons)
        assert len(clusters) == 2


# ─── score 門檻（Decision Table）────────────────────────────────────────────


class TestScore:
    def test_myc_distill_dt_010_passes_all_gates(self) -> None:
        """MYC-DISTILL-DT-010: 全門檻通過 -> 1 candidate"""
        c = _cluster_of(3, prs=[101, 102], avg_confidence=7.5, types=["pattern"])
        cands = score([c], watermark=None)
        assert len(cands) == 1
        assert cands[0].recurrence_pr_count == 2

    def test_myc_distill_dt_011_too_small(self) -> None:
        """MYC-DISTILL-DT-011: cluster size < 3 -> 0"""
        c = _cluster_of(2, prs=[101, 102], avg_confidence=8.0, types=["pattern"])
        assert score([c], watermark=None) == []

    def test_myc_distill_dt_012_single_pr(self) -> None:
        """MYC-DISTILL-DT-012: 只跨 1 個 PR（非反覆）-> 0"""
        c = _cluster_of(3, prs=[101], avg_confidence=8.0, types=["pattern"])
        assert score([c], watermark=None) == []

    def test_myc_distill_dt_013_low_confidence(self) -> None:
        """MYC-DISTILL-DT-013: avg_confidence < 7 -> 0"""
        c = _cluster_of(3, prs=[101, 102], avg_confidence=6.0, types=["pattern"])
        assert score([c], watermark=None) == []

    def test_myc_distill_bva_001_confidence_exactly_7(self) -> None:
        """MYC-DISTILL-BVA-001: avg_confidence 剛好等於門檻 7.0 -> 通過（>= 邊界）"""
        c = _cluster_of(3, prs=[101, 102], avg_confidence=7.0, types=["pattern"])
        assert len(score([c], watermark=None)) == 1

    def test_myc_distill_dt_014_non_procedural_type(self) -> None:
        """MYC-DISTILL-DT-014: type 非 procedural（pitfall）-> 0"""
        c = _cluster_of(3, prs=[101, 102], avg_confidence=8.0, types=["pitfall"])
        assert score([c], watermark=None) == []

    def test_myc_distill_dt_015_no_new_evidence(self) -> None:
        """MYC-DISTILL-DT-015: 全部成員 ts <= watermark（無新證據）-> 0"""
        c = _cluster_of(3, prs=[101, 102], avg_confidence=8.0, types=["pattern"], newest_age_days=5)
        watermark = (NOW - timedelta(days=1)).isoformat()  # 比所有成員都新
        assert score([c], watermark=watermark) == []

    def test_myc_distill_dt_017_new_evidence_resurfaces(self) -> None:
        """MYC-DISTILL-DT-017: watermark 非空 + 至少一條成員比 watermark 新 -> candidate 浮現

        這是 periodic-nudge 的**正向路徑**（先前測試只證明壓制，未證明復現）。
        """
        c = _cluster_of(3, prs=[101, 102], avg_confidence=8.0, types=["pattern"], newest_age_days=2)
        watermark = (NOW - timedelta(days=4)).isoformat()  # 比成員(age 2d)舊 -> 成員算「新證據」
        cands = score([c], watermark=watermark)
        assert len(cands) == 1
        assert cands[0].has_new_evidence is True

    def test_myc_distill_dt_018_mixed_membership_one_new(self) -> None:
        """MYC-DISTILL-DT-018: 混合成員，只要一條比 watermark 新即浮現"""
        members = [
            {"id": "old1", "ts": (NOW - timedelta(days=10)).isoformat()},
            {"id": "old2", "ts": (NOW - timedelta(days=9)).isoformat()},
            {"id": "fresh", "ts": (NOW - timedelta(days=1)).isoformat()},  # 唯一的新證據
        ]
        c = DistilledCluster(
            cluster_id="cl-mixed",
            lesson_ids=["old1", "old2", "fresh"],
            types=["pattern"],
            retro_prs=[101, 102],
            avg_confidence=8.0,
            member_lessons=members,
        )
        watermark = (NOW - timedelta(days=5)).isoformat()  # old1/old2 舊、fresh 新
        assert len(score([c], watermark=watermark)) == 1

    def test_myc_distill_dt_016_min_cluster_override(self) -> None:
        """MYC-DISTILL-DT-016: min_cluster 覆寫門檻"""
        c = _cluster_of(2, prs=[101, 102], avg_confidence=8.0, types=["pattern"])
        assert len(score([c], watermark=None, min_cluster=2)) == 1


# ─── run_distill 整合 + watermark 冪等 ──────────────────────────────────────


class TestRunDistill:
    def _seed_candidate(self, db: AgentsDB) -> None:
        """塞一個會通過所有門檻的 cluster：3 條 bash-pattern、跨 PR 101/102/103。"""
        _insert(
            db,
            key="bash-cd-git",
            insight="use git -C path instead of cd statement",
            confidence=8,
            retro_pr=101,
            skill="",
            age_days=2,
        )
        _insert(
            db,
            key="bash-cd-prefix",
            insight="use git -C path not cd then git command",
            confidence=8,
            retro_pr=102,
            skill="",
            age_days=2,
        )
        _insert(
            db,
            key="bash-cd-hook",
            insight="cd before git breaks the hook path resolution",
            confidence=7,
            retro_pr=103,
            skill="",
            age_days=2,
        )

    def test_myc_distill_st_001_end_to_end(self, tmp_path: Path) -> None:
        """MYC-DISTILL-ST-001: 種子 -> run -> 產出 1 candidate + digest 檔"""
        db = _make_db(tmp_path)
        self._seed_candidate(db)
        db.close()
        out = tmp_path / "digest.json"

        report = run_distill(
            since="90d",
            db_path=str(tmp_path / "test.db"),
            watermark_path=str(tmp_path / "state.json"),
            out_path=str(out),
            now=NOW,
        )

        assert report.candidate_count == 1
        assert report.total_lessons_scanned == 3
        assert out.exists()
        assert report.candidates[0].recurrence_pr_count == 3

    def test_myc_distill_st_002_watermark_idempotent(self, tmp_path: Path) -> None:
        """MYC-DISTILL-ST-002: 第二次 run（watermark 已前進）無新 candidate"""
        db = _make_db(tmp_path)
        self._seed_candidate(db)
        db.close()
        state = str(tmp_path / "state.json")

        first = run_distill(
            since="90d",
            db_path=str(tmp_path / "test.db"),
            watermark_path=state,
            out_path=str(tmp_path / "d1.json"),
            now=NOW,
        )
        second = run_distill(
            since="90d",
            db_path=str(tmp_path / "test.db"),
            watermark_path=state,
            out_path=str(tmp_path / "d2.json"),
            now=NOW,
        )

        assert first.candidate_count == 1
        assert second.candidate_count == 0
        assert load_watermark(state) == NOW.isoformat()

    def test_myc_distill_st_003_no_watermark_flag(self, tmp_path: Path) -> None:
        """MYC-DISTILL-ST-003: --no-watermark 不前進水位，重跑仍出 candidate"""
        db = _make_db(tmp_path)
        self._seed_candidate(db)
        db.close()
        state = str(tmp_path / "state.json")

        run_distill(
            since="90d",
            db_path=str(tmp_path / "test.db"),
            watermark_path=state,
            out_path=str(tmp_path / "d1.json"),
            now=NOW,
            update_watermark=False,
        )
        again = run_distill(
            since="90d",
            db_path=str(tmp_path / "test.db"),
            watermark_path=state,
            out_path=str(tmp_path / "d2.json"),
            now=NOW,
            update_watermark=False,
        )

        assert again.candidate_count == 1
        assert load_watermark(state) is None

    def test_myc_distill_eg_004_corrupt_watermark_treated_as_first_run(
        self, tmp_path: Path
    ) -> None:
        """MYC-DISTILL-EG-004: 損壞的 watermark 視為首跑（load 回 None），不靜默吞成既有水位"""
        state = tmp_path / "state.json"
        state.write_text("{not valid json", encoding="utf-8")
        assert load_watermark(state) is None

        db = _make_db(tmp_path)
        self._seed_candidate(db)
        db.close()
        report = run_distill(
            since="90d",
            db_path=str(tmp_path / "test.db"),
            watermark_path=str(state),
            out_path=str(tmp_path / "d.json"),
            now=NOW,
        )
        # 損壞 watermark -> 視為首跑 -> candidate 正常浮現（而非被當成已處理而靜默歸零）
        assert report.candidate_count == 1

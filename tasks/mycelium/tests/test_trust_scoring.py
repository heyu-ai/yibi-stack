"""Bot trust scoring 測試。"""

from __future__ import annotations

from tasks.mycelium.models import LessonRecord, LessonSource, LessonType
from tasks.mycelium.trust_scoring import compute_bot_trust_weight


def _make_lesson(
    source_bot: str | None, source: LessonSource = LessonSource.observed
) -> LessonRecord:
    return LessonRecord(
        project="test",
        type=LessonType.pattern,
        key="trust-test",
        insight="Trust scoring test insight text.",
        confidence=7,
        source=source,
        source_bot=source_bot,
    )


class TestComputeBotTrustWeight:
    def test_myc_trust_dt_001_user_stated_source(self) -> None:
        """MYC-TRUST-DT-001: source=user-stated -> weight 1.0"""
        lesson = _make_lesson(source_bot="claude", source=LessonSource.user_stated)
        weight = compute_bot_trust_weight(lesson, "claude", [])
        assert weight == 1.0

    def test_myc_trust_dt_002_same_bot(self) -> None:
        """MYC-TRUST-DT-002: source_bot == querying_agent -> weight 0.9"""
        lesson = _make_lesson(source_bot="claude")
        weight = compute_bot_trust_weight(lesson, "claude", [])
        assert weight == pytest.approx(0.9)

    def test_myc_trust_dt_003_trusted_other_bot(self) -> None:
        """MYC-TRUST-DT-003: source_bot in trusted_bots -> weight 0.7"""
        lesson = _make_lesson(source_bot="codex")
        weight = compute_bot_trust_weight(lesson, "claude", ["codex"])
        assert weight == pytest.approx(0.7)

    def test_myc_trust_dt_004_unknown_bot(self) -> None:
        """MYC-TRUST-DT-004: source_bot unknown -> weight 0.4"""
        lesson = _make_lesson(source_bot="unknown-bot")
        weight = compute_bot_trust_weight(lesson, "claude", [])
        assert weight == pytest.approx(0.4)

    def test_myc_trust_dt_005_source_bot_none(self) -> None:
        """MYC-TRUST-DT-005: source_bot=None -> weight 0.4 (unknown tier)"""
        lesson = _make_lesson(source_bot=None)
        weight = compute_bot_trust_weight(lesson, "claude", [])
        assert weight == pytest.approx(0.4)

    def test_myc_trust_dt_006_user_stated_beats_same_bot(self) -> None:
        """MYC-TRUST-DT-006: user-stated takes priority over same_bot check"""
        lesson = _make_lesson(source_bot="claude", source=LessonSource.user_stated)
        weight = compute_bot_trust_weight(lesson, "claude", [])
        assert weight == 1.0  # user-stated, not 0.9 (same_bot)


import pytest

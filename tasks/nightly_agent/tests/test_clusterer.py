"""NIGHTLY-clusterer tests."""

from __future__ import annotations

import uuid

from tasks.nightly_agent.clusterer import FrictionClusterer, _jaccard, _extract_keywords
from tasks.nightly_agent.models import FrictionEvent, FrictionType


def make_event(
    friction_type: FrictionType = FrictionType.AP2_BLOCK,
    description: str = "test friction",
    raw_text: str = "",
    session_id: str = "",
) -> FrictionEvent:
    return FrictionEvent(
        id=str(uuid.uuid4()),
        session_id=session_id or str(uuid.uuid4()),
        timestamp="2026-05-27T03:00:00Z",
        project="test-project",
        friction_type=friction_type,
        description=description,
        raw_text=raw_text,
        source_file="fake.jsonl",
    )


class TestJaccard:
    def test_identical_sets(self) -> None:
        a = frozenset({"bash", "error", "unicode"})
        assert _jaccard(a, a) == 1.0

    def test_disjoint_sets(self) -> None:
        a = frozenset({"bash", "error"})
        b = frozenset({"worktree", "conflict"})
        assert _jaccard(a, b) == 0.0

    def test_partial_overlap(self) -> None:
        a = frozenset({"bash", "error", "hook"})
        b = frozenset({"bash", "error", "unicode"})
        # intersection=2, union=4
        assert abs(_jaccard(a, b) - 0.5) < 0.01

    def test_empty_sets(self) -> None:
        assert _jaccard(frozenset(), frozenset()) == 0.0


class TestExtractKeywords:
    def test_basic_extraction(self) -> None:
        kws = _extract_keywords("worktree conflict fatal error")
        assert "worktree" in kws
        assert "conflict" in kws
        assert "fatal" in kws
        assert "error" in kws

    def test_stopwords_removed(self) -> None:
        kws = _extract_keywords("the error is in the code")
        assert "the" not in kws
        assert "is" not in kws
        assert "in" not in kws

    def test_short_words_excluded(self) -> None:
        kws = _extract_keywords("an or it at to")
        assert len(kws) == 0

    def test_case_insensitive(self) -> None:
        kws = _extract_keywords("WORKTREE Conflict")
        assert "worktree" in kws


class TestFrictionClusterer:
    def test_similar_events_merged(self) -> None:
        events = [
            make_event(
                FrictionType.AP2_BLOCK,
                "AP2 bash unicode em dash blocked",
                "bash hook error em dash",
            ),
            make_event(
                FrictionType.AP2_BLOCK,
                "AP2 bash em dash detected hook error",
                "unicode bash",
            ),
        ]
        clusterer = FrictionClusterer(threshold=0.15)
        clusters = clusterer.cluster(events)
        assert len(clusters) == 1
        assert clusters[0].count == 2

    def test_different_types_not_merged(self) -> None:
        events = [
            make_event(FrictionType.AP2_BLOCK, "bash ap2 unicode"),
            make_event(FrictionType.WORKTREE_CONFLICT, "worktree conflict fatal"),
        ]
        clusterer = FrictionClusterer(threshold=0.25)
        clusters = clusterer.cluster(events)
        assert len(clusters) == 2
        assert all(c.count == 1 for c in clusters)

    def test_dissimilar_same_type_not_merged(self) -> None:
        events = [
            make_event(FrictionType.BUGGY_CODE, "traceback python assertion error"),
            make_event(FrictionType.BUGGY_CODE, "ruff lint formatting issue"),
        ]
        clusterer = FrictionClusterer(threshold=0.5)
        clusters = clusterer.cluster(events)
        assert len(clusters) == 2

    def test_eligible_filters_min_size(self) -> None:
        events = [
            make_event(FrictionType.AP2_BLOCK, "bash ap2 unicode em dash error hook"),
            make_event(FrictionType.AP2_BLOCK, "bash ap2 em dash unicode hook error"),
            make_event(FrictionType.WORKTREE_CONFLICT, "worktree conflict only once"),
        ]
        clusterer = FrictionClusterer(threshold=0.2, min_cluster_size=2)
        clusters = clusterer.cluster(events)
        eligible = clusterer.eligible(clusters)
        assert len(eligible) == 1
        assert eligible[0].friction_type == FrictionType.AP2_BLOCK

    def test_empty_events(self) -> None:
        clusterer = FrictionClusterer()
        assert clusterer.cluster([]) == []

    def test_common_keywords_populated(self) -> None:
        events = [
            make_event(FrictionType.AP2_BLOCK, "bash hook ap2 unicode error"),
            make_event(FrictionType.AP2_BLOCK, "bash hook ap2 unicode block"),
        ]
        clusterer = FrictionClusterer(threshold=0.2)
        clusters = clusterer.cluster(events)
        assert len(clusters) == 1
        kws = clusters[0].common_keywords
        assert len(kws) > 0
        assert "bash" in kws or "hook" in kws or "unicode" in kws

    def test_source_session_ids_unique(self) -> None:
        events = [
            make_event(
                FrictionType.AP2_BLOCK, "bash ap2 block unicode error", session_id="session-A"
            ),
            make_event(
                FrictionType.AP2_BLOCK, "bash ap2 block unicode error", session_id="session-A"
            ),
            make_event(
                FrictionType.AP2_BLOCK, "bash ap2 block unicode error", session_id="session-B"
            ),
        ]
        clusterer = FrictionClusterer(threshold=0.2)
        clusters = clusterer.cluster(events)
        assert len(clusters) == 1
        # source_session_ids should be deduplicated
        assert len(clusters[0].source_session_ids) == 2

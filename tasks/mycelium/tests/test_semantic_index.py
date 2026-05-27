"""Semantic index 測試。"""

from __future__ import annotations

import pytest

from tasks.mycelium.semantic_index import SqliteVecIndex, _rrf_merge


class TestSqliteVecIndex:
    def test_myc_idx_dt_001_upsert_and_keyword_search(self, tmp_path) -> None:
        """MYC-IDX-DT-001: upsert then keyword search returns the lesson"""
        idx = SqliteVecIndex(str(tmp_path / "idx.db"))
        idx.upsert("lesson-1", "Python async programming patterns")
        idx.upsert("lesson-2", "SQLite database optimization")

        results = idx.search("Python", mode="keyword", limit=5)
        ids = [r[0] for r in results]
        assert "lesson-1" in ids

    def test_myc_idx_dt_002_delete_removes_from_search(self, tmp_path) -> None:
        """MYC-IDX-DT-002: delete removes lesson from search results"""
        idx = SqliteVecIndex(str(tmp_path / "idx.db"))
        idx.upsert("lesson-del", "Unique deletion test content xyz123")

        results_before = idx.search("xyz123", mode="keyword", limit=5)
        assert any(r[0] == "lesson-del" for r in results_before)

        idx.delete("lesson-del")
        results_after = idx.search("xyz123", mode="keyword", limit=5)
        assert not any(r[0] == "lesson-del" for r in results_after)

    def test_myc_idx_dt_003_embed_returns_empty_list(self, tmp_path) -> None:
        """MYC-IDX-DT-003: embed() is a Phase 4 placeholder returning []"""
        idx = SqliteVecIndex(str(tmp_path / "idx.db"))
        result = idx.embed("any text")
        assert result == []

    def test_myc_idx_dt_004_vector_mode_same_as_keyword(self, tmp_path) -> None:
        """MYC-IDX-DT-004: mode=vector behaves same as keyword (Phase 4 placeholder)"""
        idx = SqliteVecIndex(str(tmp_path / "idx.db"))
        idx.upsert("v-lesson", "Vector search placeholder content test")

        kw = idx.search("placeholder", mode="keyword", limit=5)
        vec = idx.search("placeholder", mode="vector", limit=5)
        assert [r[0] for r in kw] == [r[0] for r in vec]

    def test_myc_idx_dt_005_hybrid_mode_returns_results(self, tmp_path) -> None:
        """MYC-IDX-DT-005: mode=hybrid (RRF merge) returns results"""
        idx = SqliteVecIndex(str(tmp_path / "idx.db"))
        idx.upsert("h1", "hybrid search test one")
        idx.upsert("h2", "hybrid search test two")

        results = idx.search("hybrid", mode="hybrid", limit=5)
        assert len(results) >= 1


class TestRrfMerge:
    def test_myc_idx_dt_006_rrf_merge_combines_results(self) -> None:
        """MYC-IDX-DT-006: RRF merge with k=60 combines lists correctly"""
        list_a = [("a", 1.0), ("b", 0.8)]
        list_b = [("b", 0.9), ("c", 0.7)]
        merged = _rrf_merge(list_a, list_b, k=60, limit=3)
        ids = [r[0] for r in merged]
        # b appears in both → should rank higher
        assert "b" in ids
        assert len(merged) <= 3

    def test_myc_idx_dt_007_rrf_merge_spec_formula(self) -> None:
        """MYC-IDX-DT-007: RRF score formula: sum(1/(k+rank)) per source list"""
        # a is rank 1 in list_a only: score = 1/(60+1) ≈ 0.01639
        # b is rank 1 in list_b only: score = 1/(60+1) ≈ 0.01639
        # c is rank 1 in list_a AND rank 2 in list_b: score = 1/61 + 1/62 ≈ 0.02778
        list_a = [("c", 1.0), ("a", 0.5)]
        list_b = [("c", 1.0), ("b", 0.5)]
        merged = _rrf_merge(list_a, list_b, k=60, limit=3)
        assert merged[0][0] == "c"  # c appears in both → highest RRF score

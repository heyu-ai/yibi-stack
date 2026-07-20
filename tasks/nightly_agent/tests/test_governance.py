"""NIGHTLY-GOV：跨夜 dedup 治理測試。"""

from pathlib import Path

from tasks.nightly_agent.governance import FrictionRegistry, friction_fingerprint
from tasks.nightly_agent.tests.test_drafter import make_cluster


class TestFrictionRegistry:
    def test_nightly_gov_001_duplicate_is_skipped_across_runs(self, tmp_path: Path) -> None:
        """NIGHTLY-GOV-001：已記錄 friction 的相同 cluster 不得再次提案。"""
        state = tmp_path / "frictions.json"
        cluster = make_cluster(keywords=["language", "reply", "english"])
        first = FrictionRegistry(state, tmp_path)
        assert first.find_duplicate(cluster) is None
        first.record(cluster, "pr_opened")

        next_run = FrictionRegistry(state, tmp_path)
        assert next_run.find_duplicate(cluster) == "跨夜 friction state"

    def test_distinct_chinese_frictions_do_not_deduplicate(self, tmp_path: Path) -> None:
        first_cluster = make_cluster(keywords=["中文輸入英文回覆"])
        second_cluster = make_cluster(keywords=["工作樹切換分支衝突"])
        assert friction_fingerprint(first_cluster) != friction_fingerprint(second_cluster)

        registry = FrictionRegistry(tmp_path / "frictions.json", tmp_path)
        registry.record(first_cluster, "pr_opened")
        assert registry.find_duplicate(second_cluster) is None

    def test_same_chinese_friction_matches_across_nights(self, tmp_path: Path) -> None:
        cluster = make_cluster(keywords=["中文輸入英文回覆"])
        state = tmp_path / "frictions.json"
        FrictionRegistry(state, tmp_path).record(cluster, "pr_opened")
        assert FrictionRegistry(state, tmp_path).find_duplicate(cluster) == "跨夜 friction state"

    def test_failed_attempt_is_retryable(self, tmp_path: Path) -> None:
        cluster = make_cluster(keywords=["中文輸入英文回覆"])
        state = tmp_path / "frictions.json"
        FrictionRegistry(state, tmp_path).record(cluster, "failed")
        assert FrictionRegistry(state, tmp_path).find_duplicate(cluster) is None

    def test_corrupt_state_is_quarantined(self, tmp_path: Path, capsys) -> None:
        state = tmp_path / "frictions.json"
        state.write_text("{broken", encoding="utf-8")
        registry = FrictionRegistry(state, tmp_path)
        assert registry.records == []
        assert not state.exists()
        assert list(tmp_path.glob("frictions.json.corrupt-*"))
        assert "[WARN]" in capsys.readouterr().err

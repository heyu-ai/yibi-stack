"""NIGHTLY-GOV：跨夜 dedup 治理測試。"""

from pathlib import Path

from tasks.nightly_agent.governance import FrictionRegistry
from tasks.nightly_agent.tests.test_drafter import make_cluster


class TestFrictionRegistry:
    def test_nightly_gov_001_duplicate_is_skipped_across_runs(self, tmp_path: Path) -> None:
        """NIGHTLY-GOV-001：已記錄 friction 的相同 cluster 不得再次提案。"""
        state = tmp_path / "frictions.json"
        cluster = make_cluster(keywords=["language", "reply", "english"])
        first = FrictionRegistry(state, tmp_path)
        assert first.find_duplicate(cluster) is None
        first.record(cluster, "seen")

        next_run = FrictionRegistry(state, tmp_path)
        assert next_run.find_duplicate(cluster) == "跨夜 friction state"

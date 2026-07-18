"""PROR-ST-05N：repo-scoped sibling artifact tests。"""

from pathlib import Path

import pytest

from tasks.pr_orchestrator import dispatcher, log
from tasks.pr_orchestrator.models import OrchestratorState


def _state(repo: str) -> OrchestratorState:
    return OrchestratorState(
        repo=repo,
        pr_number=42,
        branch="feature/test",
        head_sha="deadbeef",
    )


def test_pror_st_050_logs_are_isolated_by_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(log, "_LOG_BASE", tmp_path / "logs")

    log.append("owner/alpha", 42, "INIT", "DETECTED")
    log.append("owner/beta", 42, "INIT", "FAILED")

    assert log.read("owner/alpha", 42)[0]["to"] == "DETECTED"
    assert log.read("owner/beta", 42)[0]["to"] == "FAILED"
    assert log.log_path("owner/alpha", 42) != log.log_path("owner/beta", 42)


def test_pror_st_051_manifests_are_isolated_by_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dispatcher, "_MANIFEST_BASE", tmp_path / "manifests")

    alpha = dispatcher.write_review_manifest(_state("owner/alpha"))
    beta = dispatcher.write_review_manifest(_state("owner/beta"))

    assert alpha.is_file()
    assert beta.is_file()
    assert alpha != beta

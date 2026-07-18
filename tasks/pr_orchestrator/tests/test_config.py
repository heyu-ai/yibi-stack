"""PROR-ST-04N：State 檔 repo 隔離與舊檔遷移測試。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tasks.pr_orchestrator import config
from tasks.pr_orchestrator.models import OrchestratorState


def _state(repo: str, pr_number: int = 42) -> OrchestratorState:
    return OrchestratorState(
        repo=repo,
        pr_number=pr_number,
        branch="feature/test",
        head_sha="deadbeef",
    )


def test_pror_st_040_same_pr_number_is_isolated_by_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PROR-ST-040：不同 repo 的相同 PR 號碼不會互相覆寫。"""
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)
    config.persist_state(_state("owner/alpha"))
    config.persist_state(_state("owner/beta"))

    alpha = config.state_path("owner/alpha", 42)
    beta = config.state_path("owner/beta", 42)
    assert alpha.is_file()
    assert beta.is_file()
    assert alpha != beta
    assert config.load_state_file("owner/alpha", 42)["repo"] == "owner/alpha"
    assert config.load_state_file("owner/beta", 42)["repo"] == "owner/beta"


def test_pror_st_041_repo_mismatch_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PROR-ST-041：State 內容與目前 repo 不一致時明確拒絕讀取。"""
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)
    path = config.state_path("owner/current", 42)
    path.parent.mkdir(parents=True)
    path.write_text(_state("owner/other").model_dump_json(), encoding="utf-8")

    with pytest.raises(RuntimeError, match="State repo 不一致.*state 檔碰撞"):
        config.load_state_file("owner/current", 42)


def test_pror_st_042_flat_state_migration_is_repo_scoped_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PROR-ST-042：舊版扁平檔依 repo 遷移，重複執行不會改變結果。"""
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)
    flat = tmp_path / "42.json"
    source = _state("owner/alpha").model_copy(update={"head_sha": "source-a"})
    authoritative = _state("owner/alpha").model_copy(update={"head_sha": "dest-b"})
    flat.write_text(source.model_dump_json(), encoding="utf-8")
    dest = config.state_path("owner/alpha", 42)
    dest.parent.mkdir(parents=True)
    dest.write_text(authoritative.model_dump_json(), encoding="utf-8")

    config.migrate_flat_state_files()
    config.migrate_flat_state_files()

    assert not flat.is_file()
    assert json.loads(dest.read_text(encoding="utf-8"))["head_sha"] == "dest-b"


def test_pror_st_043_flat_state_without_repo_moves_to_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PROR-ST-043：缺少 repo 欄位的舊版扁平檔移至 unknown bucket。"""
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)
    flat = tmp_path / "7.json"
    flat.write_text(json.dumps({"pr_number": 7}), encoding="utf-8")

    config.migrate_flat_state_files()

    assert not flat.is_file()
    assert config.state_path("unknown", 7).is_file()


@pytest.mark.parametrize(("stored_repo", "current_repo"), [("", "owner/current"), ("", "")])
def test_pror_st_044_empty_repo_never_passes_mismatch_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stored_repo: str,
    current_repo: str,
) -> None:
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)
    path = config.state_path(current_repo, 42)
    path.parent.mkdir(parents=True)
    path.write_text(_state(stored_repo).model_dump_json(), encoding="utf-8")

    with pytest.raises(RuntimeError, match="State repo 不一致"):
        config.load_state_file(current_repo, 42)


def test_pror_st_045_persist_rejects_empty_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="無法安全隔離 state"):
        config.persist_state(_state("  "))
    assert not config.state_path("unknown", 42).is_file()


def test_pror_st_046_corrupt_flat_state_warns_and_stays_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)
    flat = tmp_path / "9.json"
    flat.write_text("{broken", encoding="utf-8")

    config.migrate_flat_state_files()

    assert flat.is_file()
    assert not config.state_path("unknown", 9).is_file()
    stderr = capsys.readouterr().err
    assert "[WARN]" in stderr
    assert str(flat) in stderr


def test_pror_st_047_latest_warns_on_corrupt_and_uses_filename_pr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "_STATE_DIR", tmp_path)
    repo_dir = config.state_path("owner/alpha", 1).parent
    repo_dir.mkdir(parents=True)
    (repo_dir / "99.json").write_text("{broken", encoding="utf-8")
    (repo_dir / "42.json").write_text(
        json.dumps({"last_transition_at": "2026-01-01T00:00:00Z"}), encoding="utf-8"
    )

    assert config.find_latest_state("owner/alpha") == 42
    stderr = capsys.readouterr().err
    assert "[WARN]" in stderr
    assert str(repo_dir / "99.json") in stderr

"""PCP: plugin-cache-prune.prune_plugin_cache 的孤兒版本目錄偵測與刪除測試。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    REPO_ROOT
    / "plugins"
    / "harness"
    / "skills"
    / "plugin-cache-prune"
    / "scripts"
    / "prune_plugin_cache.py"
)

_spec = importlib.util.spec_from_file_location("prune_plugin_cache", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
prune_plugin_cache = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("prune_plugin_cache", prune_plugin_cache)
_spec.loader.exec_module(prune_plugin_cache)


def _write_installed(home: Path, active_paths: list[str]) -> None:
    """active_paths：目前釘選的 installPath 絕對路徑清單。"""
    entries = {}
    for i, install_path in enumerate(active_paths):
        entries[f"pack-{i}@yibi-stack"] = [
            {
                "scope": "user",
                "installPath": install_path,
                "version": "1.0.0",
                "installedAt": "2026-01-01T00:00:00Z",
                "lastUpdated": "2026-01-01T00:00:00Z",
            }
        ]
    path = home / ".claude" / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    (path / "installed_plugins.json").write_text(json.dumps({"plugins": entries}), encoding="utf-8")


def _make_version_dir(cache_root: Path, marketplace: str, plugin: str, version: str) -> Path:
    version_dir = cache_root / marketplace / plugin / version
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "SKILL.md").write_text("dummy", encoding="utf-8")
    return version_dir


class TestDryRunPreservesFiles:
    def test_pcp_dt_001_dry_run_lists_stale_without_deleting(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-001: dry-run 列出未被參照的版本目錄，但不刪除。"""
        cache_root = tmp_path / "cache"
        active_dir = _make_version_dir(cache_root, "yibi-stack", "pr-flow", "1.15.2")
        stale_dir = _make_version_dir(cache_root, "yibi-stack", "pr-flow", "1.14.0")
        _write_installed(tmp_path, [str(active_dir)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=True)

        out = capsys.readouterr().out
        assert rc == 0
        assert "[DRY-RUN]" in out
        assert str(stale_dir) in out
        assert stale_dir.exists()
        assert active_dir.exists()


class TestApplyRemovesStaleOnly:
    def test_pcp_dt_002_apply_removes_stale_keeps_active(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-002: --apply 實際刪除未被參照的版本目錄，保留目前釘選版本。"""
        cache_root = tmp_path / "cache"
        active_dir = _make_version_dir(cache_root, "yibi-stack", "pr-flow", "1.15.2")
        stale_dir = _make_version_dir(cache_root, "yibi-stack", "pr-flow", "1.14.0")
        _write_installed(tmp_path, [str(active_dir)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=False)

        out = capsys.readouterr().out
        assert rc == 0
        assert "[REMOVE]" in out
        assert not stale_dir.exists()
        assert active_dir.exists()


class TestMultipleMarketplaces:
    def test_pcp_dt_003_scans_all_marketplaces_not_just_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-003: 同時掃描多個 marketplace，各自獨立判斷孤兒版本。"""
        cache_root = tmp_path / "cache"
        active_a = _make_version_dir(cache_root, "yibi-stack", "pr-flow", "1.15.2")
        stale_a = _make_version_dir(cache_root, "yibi-stack", "pr-flow", "1.14.0")
        active_b = _make_version_dir(cache_root, "claude-plugins-official", "superpowers", "6.2.0")
        stale_b = _make_version_dir(cache_root, "claude-plugins-official", "superpowers", "6.1.1")
        _write_installed(tmp_path, [str(active_a), str(active_b)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=True)

        out = capsys.readouterr().out
        assert rc == 0
        assert str(stale_a) in out
        assert str(stale_b) in out
        assert str(active_a) not in out
        assert str(active_b) not in out


class TestEmptyCache:
    def test_pcp_dt_004_no_stale_dirs_reports_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-004: 全部版本目錄都被參照 -> 回報 0 個孤兒。"""
        cache_root = tmp_path / "cache"
        active_dir = _make_version_dir(cache_root, "yibi-stack", "pr-flow", "1.15.2")
        _write_installed(tmp_path, [str(active_dir)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=True)

        out = capsys.readouterr().out
        assert rc == 0
        assert "共 0 個未被參照的舊版本目錄" in out

    def test_pcp_dt_005_missing_cache_root_reports_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-005: cache 目錄本身不存在（尚未裝過任何 plugin）-> 回報 0 個孤兒，不 crash。"""
        cache_root = tmp_path / "cache-does-not-exist"
        _write_installed(tmp_path, [])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=True)

        out = capsys.readouterr().out
        assert rc == 0
        assert "共 0 個未被參照的舊版本目錄" in out


class TestFailureModes:
    def test_pcp_eg_001_missing_installed_plugins_json_exits_1(self, tmp_path: Path) -> None:
        """PCP-EG-001: installed_plugins.json 不存在 -> sys.exit(1)。"""
        cache_root = tmp_path / "cache"
        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            prune_plugin_cache.prune(cache_root, dry_run=True)
        assert exc_info.value.code == 1

    def test_pcp_eg_002_corrupt_installed_plugins_json_exits_1(self, tmp_path: Path) -> None:
        """PCP-EG-002: installed_plugins.json 格式錯誤（非法 JSON） -> sys.exit(1)。"""
        path = tmp_path / ".claude" / "plugins"
        path.mkdir(parents=True, exist_ok=True)
        (path / "installed_plugins.json").write_text("not valid json", encoding="utf-8")
        cache_root = tmp_path / "cache"
        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            prune_plugin_cache.prune(cache_root, dry_run=True)
        assert exc_info.value.code == 1

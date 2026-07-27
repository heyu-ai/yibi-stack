"""PMC: plugin-migration-check.check_migration 的孤兒 pack 偵測與遷移建議測試。

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
    / "plugin-migration-check"
    / "scripts"
    / "check_migration.py"
)

_spec = importlib.util.spec_from_file_location("check_migration", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
check_migration = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("check_migration", check_migration)
_spec.loader.exec_module(check_migration)


def _write_installed(home: Path, packs: dict[str, str]) -> None:
    """packs: {pack_name: version}；key 不含 '@yibi-stack' 後綴。"""
    entries = {}
    for pack, version in packs.items():
        entries[f"{pack}@yibi-stack"] = [
            {
                "scope": "user",
                "installPath": f"/fake/cache/{pack}/{version}",
                "version": version,
                "installedAt": "2026-01-01T00:00:00Z",
                "lastUpdated": "2026-01-01T00:00:00Z",
                "gitCommitSha": "deadbeef",
            }
        ]
    path = home / ".claude" / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    (path / "installed_plugins.json").write_text(json.dumps({"plugins": entries}), encoding="utf-8")


def _write_marketplace_cache(home: Path, pack_names: list[str]) -> None:
    path = home / ".claude" / "plugins" / "marketplaces" / "yibi-stack" / ".claude-plugin"
    path.mkdir(parents=True, exist_ok=True)
    payload = {"plugins": [{"name": n} for n in pack_names]}
    (path / "marketplace.json").write_text(json.dumps(payload), encoding="utf-8")


class TestNoInstall:
    def test_pmc_dt_001_no_yibi_stack_packs_returns_ok(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-001: 未安裝任何 yibi-stack pack -> [OK]，exit 0。"""
        _write_installed(tmp_path, {})
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        assert rc == 0
        assert "[OK]" in capsys.readouterr().out


class TestAllCurrent:
    def test_pmc_dt_002_all_packs_still_registered_returns_ok(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-002: 已裝的 pack 全部仍在目前 marketplace -> 0 個孤兒，exit 0。"""
        _write_installed(tmp_path, {"growth": "1.16.0", "sdd": "1.16.0"})
        _write_marketplace_cache(
            tmp_path, ["harness", "sdd", "growth", "dev-cycle", "3rd-tools", "methodology"]
        )
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 0
        assert "0 個孤兒安裝需要處理，2 個正常" in out


class TestStaleSingleTarget:
    def test_pmc_dt_003_renamed_pack_single_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-003: pr-flow（單一遷移目標）-> [stale] + uninstall/install 建議，exit 1。"""
        _write_installed(tmp_path, {"pr-flow": "1.15.2"})
        _write_marketplace_cache(
            tmp_path, ["harness", "sdd", "growth", "dev-cycle", "3rd-tools", "methodology"]
        )
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 1
        assert "[stale] pr-flow@yibi-stack" in out
        assert "claude plugin uninstall pr-flow@yibi-stack" in out
        assert "claude plugin install dev-cycle@yibi-stack" in out


class TestStaleMultiTarget:
    def test_pmc_dt_004_split_pack_multiple_targets(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-004: tdd（拆成兩個目標）-> install 指令須包含兩個 pack 名。"""
        _write_installed(tmp_path, {"tdd": "1.15.2"})
        _write_marketplace_cache(
            tmp_path, ["harness", "sdd", "growth", "dev-cycle", "3rd-tools", "methodology"]
        )
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 1
        assert "claude plugin install methodology@yibi-stack dev-cycle@yibi-stack" in out


class TestRemovedNoReplacement:
    def test_pmc_dt_005_removed_pack_no_install_suggestion(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-005: writing（已移除無替代）-> [removed]，只有 uninstall，沒有 install 建議。"""
        _write_installed(tmp_path, {"writing": "1.15.2"})
        _write_marketplace_cache(
            tmp_path, ["harness", "sdd", "growth", "dev-cycle", "3rd-tools", "methodology"]
        )
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 1
        assert "[removed] writing@yibi-stack" in out
        assert "claude plugin uninstall writing@yibi-stack" in out
        assert "claude plugin install" not in out


class TestUnknownOrphan:
    def test_pmc_dt_006_orphan_not_in_migration_map_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-006: 已消失但不在 MIGRATION_MAP 裡的 pack -> [WARN]，找不到已知遷移路徑。"""
        _write_installed(tmp_path, {"some-future-retired-pack": "1.15.2"})
        _write_marketplace_cache(
            tmp_path, ["harness", "sdd", "growth", "dev-cycle", "3rd-tools", "methodology"]
        )
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 1
        assert "[WARN] some-future-retired-pack@yibi-stack" in out
        assert "找不到已知的遷移路徑" in out


class TestMarketplaceCacheFallback:
    def test_pmc_dt_007_missing_cache_falls_back_to_static_list(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-007: 讀不到本機 marketplace 快取 -> 用內建靜態清單，並印出 [WARN]。"""
        _write_installed(tmp_path, {"growth": "1.16.0"})
        # 不寫 marketplace.json，模擬快取不存在
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 0
        assert "[WARN] 讀不到本機 marketplace 快取" in out

    def test_pmc_dt_008_live_cache_present_no_fallback_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-008: 本機 marketplace 快取存在且可讀 -> 不印 fallback 警告。"""
        _write_installed(tmp_path, {"growth": "1.16.0"})
        _write_marketplace_cache(tmp_path, ["growth"])
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 0
        assert "讀不到本機 marketplace 快取" not in out


class TestFailureModes:
    def test_pmc_eg_001_missing_installed_plugins_json_exits_1(self, tmp_path: Path) -> None:
        """PMC-EG-001: installed_plugins.json 不存在 -> sys.exit(1)。"""
        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            check_migration.check()
        assert exc_info.value.code == 1

    def test_pmc_eg_002_corrupt_installed_plugins_json_exits_1(self, tmp_path: Path) -> None:
        """PMC-EG-002: installed_plugins.json 格式錯誤（非法 JSON） -> sys.exit(1)。"""
        path = tmp_path / ".claude" / "plugins"
        path.mkdir(parents=True, exist_ok=True)
        (path / "installed_plugins.json").write_text("not valid json", encoding="utf-8")
        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            check_migration.check()
        assert exc_info.value.code == 1

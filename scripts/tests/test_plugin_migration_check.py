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


_ALL_PACKS = ["harness", "sdd", "growth", "dev-cycle", "3rd-tools", "methodology"]


def _dangling_link(home: Path, base: str, name: str) -> Path:
    """在 ~/<base>/<name> 建一個指向不存在目錄的 symlink（模擬 skill 被刪後殘留）。"""
    parent = home / base
    parent.mkdir(parents=True, exist_ok=True)
    link = parent / name
    link.symlink_to(home / "deleted-checkout" / name)
    return link


class TestRemovedSkills:
    def test_pmc_dt_009_old_methodology_gets_upcoming_removal_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-009: methodology 版本早於移除版 -> [notice] 說更新後會消失，列出替代做法；不影響 exit code。"""
        _write_installed(tmp_path, {"methodology": "1.22.5"})
        _write_marketplace_cache(tmp_path, _ALL_PACKS)
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 0
        assert "[notice] tdd-kentbeck" in out
        assert "[notice] flutter-tdd" in out
        assert "更新到 methodology 1.23.0 後會消失" in out
        assert "red-first gate" in out

    def test_pmc_dt_010_current_methodology_gets_removed_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-010: methodology 已是移除版之後 -> [notice] 說已移除。"""
        _write_installed(tmp_path, {"methodology": "1.23.1"})
        _write_marketplace_cache(tmp_path, _ALL_PACKS)
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 0
        assert "已於 methodology 1.23.0 移除" in out

    def test_pmc_dt_011_old_tdd_pack_also_gets_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-011: 舊的 tdd pack 當初也裝了這兩支 skill -> 同樣提示。"""
        _write_installed(tmp_path, {"tdd": "1.15.2"})
        _write_marketplace_cache(tmp_path, _ALL_PACKS)
        with patch.object(Path, "home", return_value=tmp_path):
            check_migration.check()
        assert "[notice] tdd-kentbeck" in capsys.readouterr().out

    def test_pmc_dt_012_unrelated_packs_get_no_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-012: 沒裝 methodology／tdd -> 不印 skill 移除提示（對照組）。"""
        _write_installed(tmp_path, {"growth": "1.23.1"})
        _write_marketplace_cache(tmp_path, _ALL_PACKS)
        with patch.object(Path, "home", return_value=tmp_path):
            check_migration.check()
        assert "[notice]" not in capsys.readouterr().out

    @pytest.mark.parametrize("base", [".claude/skills", ".agents/skills"])
    def test_pmc_dt_013_dangling_skill_symlink_is_stale(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], base: str
    ) -> None:
        """PMC-DT-013: 已移除 skill 的 symlink 指向不存在目錄 -> [stale-link]，exit 1，計入待處理。"""
        _write_installed(tmp_path, {"growth": "1.23.1"})
        _write_marketplace_cache(tmp_path, _ALL_PACKS)
        link = _dangling_link(tmp_path, base, "tdd-kentbeck")
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 1
        assert f"[stale-link] {link}" in out
        assert "1 個孤兒安裝需要處理" in out

    def test_pmc_dt_014_live_skill_symlink_is_not_stale(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-014: symlink 指向仍存在的目錄 -> 不算殘留（DT-013 的對照組）。"""
        _write_installed(tmp_path, {"growth": "1.23.1"})
        _write_marketplace_cache(tmp_path, _ALL_PACKS)
        target = tmp_path / "checkout" / "tdd-kentbeck"
        target.mkdir(parents=True)
        (tmp_path / ".claude" / "skills").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "tdd-kentbeck").symlink_to(target)
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        assert rc == 0
        assert "[stale-link]" not in capsys.readouterr().out

    def test_pmc_dt_015_dangling_link_reported_without_any_plugin(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PMC-DT-015: 只用 make install（沒裝任何 yibi-stack plugin）也要報殘留 symlink，不可提早回 [OK]。"""
        _write_installed(tmp_path, {})
        _dangling_link(tmp_path, ".claude/skills", "flutter-tdd")
        with patch.object(Path, "home", return_value=tmp_path):
            rc = check_migration.check()
        out = capsys.readouterr().out
        assert rc == 1
        assert "[stale-link]" in out


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

"""PCP: plugin-cache-prune.prune_plugin_cache 的孤兒版本目錄偵測與刪除測試。

Test ID 規則見 .claude/rules/09-test-conventions.md。

覆蓋對映（Review Contract AC-1..AC-6）：
- AC-1 dry-run 不刪 + 容量回報：PCP-DT-001 / PCP-DT-010 / PCP-DT-011 / PCP-DT-013
- AC-2 apply 只刪未參照者：PCP-DT-002 / PCP-DT-012
- AC-3 掃描所有 marketplace：PCP-DT-003
- AC-4 fail loud + 空 active set 守衛：PCP-DT-004 / PCP-DT-005 / PCP-DT-006
  / PCP-EG-001 / PCP-EG-002 / PCP-EG-003 / PCP-EG-004
- AC-6 刪除前重新確認：PCP-DT-007 / PCP-DT-008
- 破壞半徑不得超出 cache root（symlink）：PCP-DT-009 / PCP-DT-014
- 刪除失敗不得中斷整批且不得謊報：PCP-EG-005 / PCP-EG-006
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
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


def _write_raw_installed(home: Path, payload: str) -> None:
    """直接寫入原始字串，用於結構非預期的失敗模式測試。"""
    path = home / ".claude" / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    (path / "installed_plugins.json").write_text(payload, encoding="utf-8")


def _make_version_dir(
    cache_root: Path, marketplace: str, plugin: str, version: str, payload: str = "dummy"
) -> Path:
    version_dir = cache_root / marketplace / plugin / version
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "SKILL.md").write_text(payload, encoding="utf-8")
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
        """PCP-DT-005: cache 目錄本身不存在 -> 回報 0 個孤兒，不 crash。

        安裝清單必須有至少一筆有效安裝，否則會走 PCP-DT-006 的空 active set 守衛。
        """
        cache_root = tmp_path / "cache-does-not-exist"
        _write_installed(tmp_path, [str(tmp_path / "somewhere" / "1.0.0")])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=True)

        out = capsys.readouterr().out
        assert rc == 0
        assert "共 0 個未被參照的舊版本目錄" in out


class TestEmptyActiveSetGuard:
    """AC-4 第二子句：清單可解析但推導不出 active set 時，不得清空整個 cache。"""

    def test_pcp_dt_006_empty_active_set_with_populated_cache_refuses_to_delete(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-006: 空 active set + 已填充的 cache + apply -> exit 1 且一個都不刪。"""
        cache_root = tmp_path / "cache"
        pinned = _make_version_dir(cache_root, "yibi-stack", "harness", "1.16.0")
        other = _make_version_dir(cache_root, "claude-plugins-official", "superpowers", "6.2.0")
        _write_installed(tmp_path, [])

        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            prune_plugin_cache.prune(cache_root, dry_run=False)

        assert exc_info.value.code == 1
        assert pinned.exists()
        assert other.exists()
        assert "[FAIL]" in capsys.readouterr().err


class TestDeleteTimeReconfirmation:
    """AC-6：刪除前必須以當下的安裝清單重新確認，不依賴掃描時的快照。"""

    def test_pcp_dt_007_directory_pinned_after_scan_is_not_deleted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-007: 掃描後才被重新釘選的目錄，在刪除迴圈中必須跳過。"""
        cache_root = tmp_path / "cache"
        active = _make_version_dir(cache_root, "yibi-stack", "harness", "1.16.0")
        stale = _make_version_dir(cache_root, "yibi-stack", "harness", "1.14.0")
        newly_pinned = _make_version_dir(cache_root, "yibi-stack", "harness", "1.15.0")
        _write_installed(tmp_path, [str(active)])

        real_rmtree = prune_plugin_cache.shutil.rmtree
        fired = {"done": False}

        def racing_rmtree(path: Any, *a: Any, **kw: Any) -> None:
            # 模擬：第一次刪除發生時，另一個 session 把 1.15.0 設為釘選版本。
            if not fired["done"]:
                fired["done"] = True
                _write_installed(tmp_path, [str(active), str(newly_pinned)])
            real_rmtree(path, *a, **kw)

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(prune_plugin_cache.shutil, "rmtree", racing_rmtree),
        ):
            rc = prune_plugin_cache.prune(cache_root, dry_run=False)

        err = capsys.readouterr().err
        assert rc == 0
        assert not stale.exists(), "掃描時與刪除時皆為孤兒者應被刪除"
        assert newly_pinned.exists(), "刪除前重新確認應保住掃描後才被釘選的目錄"
        assert active.exists()
        assert "[SKIP]" in err

    def test_pcp_dt_008_unreadable_manifest_at_delete_time_skips_instead_of_deleting(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-008: 刪除前重讀清單失敗 -> 跳過該筆，不依舊快照刪除。"""
        cache_root = tmp_path / "cache"
        active = _make_version_dir(cache_root, "yibi-stack", "harness", "1.16.0")
        stale = _make_version_dir(cache_root, "yibi-stack", "harness", "1.14.0")
        _write_installed(tmp_path, [str(active)])

        calls = {"n": 0}
        real_read = prune_plugin_cache._read_active_paths

        def flaky_read() -> set[str]:
            calls["n"] += 1
            if calls["n"] == 1:  # 初次載入成功
                return real_read()
            raise RuntimeError("模擬刪除前重讀失敗")

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(prune_plugin_cache, "_read_active_paths", flaky_read),
        ):
            rc = prune_plugin_cache.prune(cache_root, dry_run=False)

        err = capsys.readouterr().err
        assert rc == 0
        assert stale.exists(), "無法重新確認時必須跳過，不得依舊快照刪除"
        assert "[SKIP]" in err


class TestSymlinkContainment:
    """破壞半徑不得超出 cache root。"""

    def test_pcp_dt_009_symlinked_marketplace_is_not_traversed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-009: symlink 進來的 marketplace 不得被走訪，cache 外的目錄必須存活。"""
        cache_root = tmp_path / "cache"
        cache_root.mkdir(parents=True)

        outside = tmp_path / "precious"
        (outside / "mkt-plugin" / "9.9.9").mkdir(parents=True)
        victim = outside / "mkt-plugin" / "9.9.9" / "IMPORTANT.txt"
        victim.write_text("do not delete", encoding="utf-8")
        (cache_root / "devmkt").symlink_to(outside, target_is_directory=True)

        active = _make_version_dir(cache_root, "realmkt", "somepack", "1.0.0")
        _write_installed(tmp_path, [str(active)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=False)

        err = capsys.readouterr().err
        assert rc == 0
        assert victim.exists(), "cache root 之外的目錄不得被刪除"
        assert "[SKIP]" in err

    def test_pcp_dt_014_symlinked_version_dir_is_skipped_not_deleted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-014: symlink 的版本目錄應被跳過，不得印 [REMOVE] 也不得 crash。"""
        cache_root = tmp_path / "cache"
        active = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "SKILL.md").write_text("payload", encoding="utf-8")
        link = cache_root / "mkt" / "pack" / "0.9.0"
        link.symlink_to(elsewhere, target_is_directory=True)

        _write_installed(tmp_path, [str(active)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.prune(cache_root, dry_run=False)

        captured = capsys.readouterr()
        assert rc == 0
        assert link.is_symlink(), "symlink 本身不應被移除"
        assert elsewhere.exists()
        assert "[REMOVE]" not in captured.out
        assert "[SKIP]" in captured.err

    def test_pcp_dt_015_symlinked_version_dir_inside_cache_is_reported_as_skipped(
        self, tmp_path: Path
    ) -> None:
        """PCP-DT-015: symlink 即使指向 cache root 內部，也必須被歸入 skipped 而非候選。

        DT-009／DT-014 的 symlink 都指向 cache 外，因此「拒絕 symlink」與「邊界檢查」
        互為備援，任一被移除另一個仍會擋下 -- 兩者的 mutation 都會存活。本測試把目標
        放在 cache root 內，讓邊界檢查失效，成為唯一能證明 symlink 拒絕確實生效的案例。
        """
        cache_root = tmp_path / "cache"
        active = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")
        link = cache_root / "mkt" / "pack" / "0.9.0"
        link.symlink_to(active, target_is_directory=True)

        stale, skipped = prune_plugin_cache._find_stale_dirs(cache_root, {str(active.resolve())})

        assert link in skipped, "symlink 必須被明確回報為跳過，不得靜默忽略"
        assert stale == [], "symlink 不得成為刪除候選"

    def test_pcp_dt_016_is_within_predicate_bounds_the_blast_radius(self, tmp_path: Path) -> None:
        """PCP-DT-016: `_is_within` 述詞本身的雙向驗證（belt-and-braces 防線的單元測試）。"""
        root = (tmp_path / "cache").resolve()
        root.mkdir(parents=True)

        assert prune_plugin_cache._is_within(root, root) is True
        assert prune_plugin_cache._is_within(root / "mkt" / "pack" / "1.0.0", root) is True
        assert prune_plugin_cache._is_within((tmp_path / "outside").resolve(), root) is False
        assert prune_plugin_cache._is_within(root.parent, root) is False


class TestSizeReporting:
    def test_pcp_dt_010_reported_total_matches_bytes_on_disk(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-010: dry-run 回報的容量必須等於實際位元組數（含巢狀子目錄）。"""
        cache_root = tmp_path / "cache"
        active = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")
        stale = _make_version_dir(cache_root, "mkt", "pack", "0.9.0", payload="a" * 1000)
        nested = stale / "sub" / "deeper"
        nested.mkdir(parents=True)
        (nested / "extra.txt").write_text("b" * 2000, encoding="utf-8")
        _write_installed(tmp_path, [str(active)])

        expected = sum(f.stat().st_size for f in stale.rglob("*") if f.is_file())
        assert expected == 3000, "fixture 前提：1000 + 2000 位元組"

        with patch.object(Path, "home", return_value=tmp_path):
            prune_plugin_cache.prune(cache_root, dry_run=True)

        out = capsys.readouterr().out
        assert prune_plugin_cache._dir_size(stale) == expected
        # 3000 bytes -> "(3 KB)"；非遞迴實作只會看到 1 KB
        assert f"({expected / 1024:.0f} KB)" in out


class TestMainEntryPoint:
    """`main()` 是「預設 dry-run」這條安全預設的唯一實作處，必須有覆蓋。"""

    def test_pcp_dt_011_main_without_flag_defaults_to_dry_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-011: 不帶旗標呼叫 main() 不得刪除任何檔案。"""
        cache_root = tmp_path / ".claude" / "plugins" / "cache"
        active = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")
        stale = _make_version_dir(cache_root, "mkt", "pack", "0.9.0")
        _write_installed(tmp_path, [str(active)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.main([])

        assert rc == 0
        assert stale.exists(), "預設必須是 dry-run"
        assert "[DRY-RUN]" in capsys.readouterr().out

    def test_pcp_dt_012_main_with_apply_removes_stale(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-012: main(["--apply"]) 會實際刪除孤兒目錄。"""
        cache_root = tmp_path / ".claude" / "plugins" / "cache"
        active = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")
        stale = _make_version_dir(cache_root, "mkt", "pack", "0.9.0")
        _write_installed(tmp_path, [str(active)])

        with patch.object(Path, "home", return_value=tmp_path):
            rc = prune_plugin_cache.main(["--apply"])

        assert rc == 0
        assert not stale.exists()
        assert active.exists()
        assert "[REMOVE]" in capsys.readouterr().out

    def test_pcp_dt_013_main_reads_sys_argv_when_argv_omitted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-DT-013: 省略 argv 時 main() 由 sys.argv 取值，預設仍為 dry-run。"""
        cache_root = tmp_path / ".claude" / "plugins" / "cache"
        active = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")
        stale = _make_version_dir(cache_root, "mkt", "pack", "0.9.0")
        _write_installed(tmp_path, [str(active)])

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(sys, "argv", ["prune_plugin_cache.py"]),
        ):
            rc = prune_plugin_cache.main()

        assert rc == 0
        assert stale.exists()
        assert "[DRY-RUN]" in capsys.readouterr().out

    @pytest.mark.parametrize("bad_argv", [["--dry-run"], ["--marketplace", "yibi-stack"], ["-x"]])
    def test_pcp_eg_007_unknown_argument_is_rejected(
        self, tmp_path: Path, bad_argv: list[str]
    ) -> None:
        """PCP-EG-007: 未知旗標必須被拒絕（argparse exit 2），不得靜默忽略。"""
        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            prune_plugin_cache.main(["--apply", *bad_argv])
        assert exc_info.value.code == 2


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
        _write_raw_installed(tmp_path, "not valid json")
        cache_root = tmp_path / "cache"
        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            prune_plugin_cache.prune(cache_root, dry_run=True)
        assert exc_info.value.code == 1

    def test_pcp_eg_003_entry_without_install_path_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-EG-003: 任一筆安裝缺 installPath -> 無法確認釘選目標，exit 1。"""
        _write_raw_installed(
            tmp_path,
            json.dumps({"plugins": {"pack@mkt": [{"scope": "user", "version": "1.0.0"}]}}),
        )
        cache_root = tmp_path / "cache"
        stale = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")

        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            prune_plugin_cache.prune(cache_root, dry_run=False)

        assert exc_info.value.code == 1
        assert stale.exists()
        assert "installPath" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "payload",
        [
            '{"plugins": ["x"]}',
            '{"plugins": "x"}',
            '{"version": 2}',
            '{"plugins": {"pack@mkt": "not-a-list"}}',
            '{"plugins": {"pack@mkt": ["not-a-dict"]}}',
            '["not", "a", "dict"]',
        ],
    )
    def test_pcp_eg_004_unexpected_shape_fails_loud_not_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: str
    ) -> None:
        """PCP-EG-004: 結構非預期 -> 乾淨的 [FAIL] + exit 1，不得噴 AttributeError。"""
        _write_raw_installed(tmp_path, payload)
        cache_root = tmp_path / "cache"

        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            prune_plugin_cache.prune(cache_root, dry_run=True)

        assert exc_info.value.code == 1
        assert "[FAIL]" in capsys.readouterr().err

    def test_pcp_eg_005_rmtree_failure_does_not_abort_batch_or_claim_removal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PCP-EG-005: 單一目錄刪除失敗 -> 不印 [REMOVE]、續刪其餘、退出碼非零。"""
        cache_root = tmp_path / "cache"
        active = _make_version_dir(cache_root, "mkt", "pack", "2.0.0")
        doomed = _make_version_dir(cache_root, "mkt", "pack", "0.9.0")
        survivor_target = _make_version_dir(cache_root, "mkt", "pack", "1.0.0")
        _write_installed(tmp_path, [str(active)])

        real_rmtree = prune_plugin_cache.shutil.rmtree

        def selective_rmtree(path: Any, *a: Any, **kw: Any) -> None:
            if Path(path) == doomed:
                raise PermissionError("模擬唯讀檔案")
            real_rmtree(path, *a, **kw)

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(prune_plugin_cache.shutil, "rmtree", selective_rmtree),
        ):
            rc = prune_plugin_cache.prune(cache_root, dry_run=False)

        captured = capsys.readouterr()
        assert rc == 1, "有刪除失敗時必須以非零退出碼結束"
        assert doomed.exists()
        assert str(doomed) not in captured.out, "刪除失敗不得印出 [REMOVE] 宣稱已刪"
        assert not survivor_target.exists(), "單一目錄失敗不得中斷整批"
        assert "[FAIL]" in captured.err
        assert "實際刪除" in captured.out, "失敗後仍必須印出摘要"

    def test_pcp_eg_006_dir_size_skips_vanished_and_symlinked_entries(self, tmp_path: Path) -> None:
        """PCP-EG-006: _dir_size 遇到掃描中消失的檔案或 symlink 時跳過，不 crash。"""
        target = tmp_path / "d"
        target.mkdir()
        (target / "real.txt").write_text("x" * 100, encoding="utf-8")
        (target / "dangling").symlink_to(tmp_path / "nope")

        assert prune_plugin_cache._dir_size(target) == 100, "dangling symlink 不得使其 crash"

        real_stat = Path.stat

        def flaky_stat(self: Path, *a: Any, **kw: Any) -> Any:
            if self.name == "real.txt":
                raise FileNotFoundError("模擬掃描中檔案消失")
            return real_stat(self, *a, **kw)

        with patch.object(Path, "stat", flaky_stat):
            assert prune_plugin_cache._dir_size(target) == 0

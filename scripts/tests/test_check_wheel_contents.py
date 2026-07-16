"""check_wheel_contents.py 的守衛測試。

為何需要（PR #249 round-2 review）：本 PR 之後，wheel 的 packages / exclude / entry-point
metadata 契約**只由 check_wheel_contents.py 執行**，而它自己沒有測試。一個沒有測試的守衛，
其「PASS」在你證明它會對已知壞輸入失敗之前，不帶任何資訊——未來 forbidden 條件寫錯、或
_declared_scripts() 靜默回傳 {}，它就會永遠印 [OK] 而沒有人發現。

本檔的每個壞 wheel 案例都取自 round-2 review 用來擊破**舊版 block-list 實作**的合成 wheel：
那一版擋 4 個寫死前綴卻印「全部在 tasks/ 之下」，於是帶 openspec/、頂層 tests/、根目錄 .env
的 wheel 全數通過。這些案例現在是回歸測試。

先例：scripts/tests/test_assert_not_worktree.py（同樣是「測試一個守衛」）。
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_wheel_contents", PROJECT_ROOT / "scripts" / "check_wheel_contents.py"
)
assert _SPEC and _SPEC.loader
cwc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cwc)

_DIST_INFO = "yibi_stack-1.9.0.dist-info"
_GOOD_ENTRY_POINTS = "[console_scripts]\nportman = tasks.local_port_manager.cli:cli\n"


def _make_wheel(tmp_path: Path, names: dict[str, str], *, name: str = "probe.whl") -> Path:
    """建一個合成 wheel（純 zip；本腳本只讀 namelist 與 entry_points.txt）。"""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for arcname, content in names.items():
            zf.writestr(arcname, content)
    return path


def _good_wheel_contents() -> dict[str, str]:
    return {
        "tasks/__init__.py": "",
        "tasks/local_port_manager/cli.py": "cli = None",
        f"{_DIST_INFO}/METADATA": "Name: yibi-stack\n",
        f"{_DIST_INFO}/entry_points.txt": _GOOD_ENTRY_POINTS,
    }


class TestAcceptsValidWheel:
    def test_cwc_st_001_clean_wheel_passes(self, tmp_path: Path, monkeypatch) -> None:
        """CWC-ST-001: 合法 wheel 通過（正向對照）。

        沒有這個案例，下方所有「壞 wheel 被擋下」的測試在「守衛永遠 fail」時也會通過。
        """
        wheel = _make_wheel(tmp_path, _good_wheel_contents())
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        cwc.main()  # 不拋 SystemExit 即通過


class TestRejectsBadWheel:
    """每個案例都曾讓舊版 block-list 實作靜默放行。"""

    @pytest.mark.parametrize(
        ("case", "extra"),
        [
            # round-2 review 的合成 wheel：block-list 版全數放行
            ("越界的頂層套件", {"openspec/specs/foo.md": "x", "openspec/__init__.py": ""}),
            ("根目錄設定檔", {".env": "SECRET=1", "Makefile": "all:"}),
            ("夾帶帳務工具", {"secret_ledger/db.py": "DSN='localhost:5435/ledgerone'"}),
            # 舊版 block-list 本來就擋得住的，確保反轉後沒有退化
            ("scripts/", {"scripts/compare_billing.py": "import pandas"}),
            ("plugins/", {"plugins/util/README.md": "x"}),
        ],
    )
    def test_cwc_dt_010_stray_paths_rejected(
        self, tmp_path: Path, monkeypatch, case: str, extra: dict[str, str]
    ) -> None:
        """CWC-DT-010: 任何 tasks/ 與 dist-info 之外的檔案都被擋下。"""
        wheel = _make_wheel(tmp_path, {**_good_wheel_contents(), **extra})
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1, f"{case} 應被擋下"

    @pytest.mark.parametrize(
        ("case", "extra"),
        [
            ("巢狀 tests/", {"tasks/local_port_manager/tests/test_cli.py": "x"}),
            # 舊版用 "/tests/" 子字串比對，頂層 tests/ 無前導斜線而漏掉
            ("頂層 tests/", {"tests/test_secret.py": "x"}),
        ],
    )
    def test_cwc_dt_011_tests_rejected(
        self, tmp_path: Path, monkeypatch, case: str, extra: dict[str, str]
    ) -> None:
        """CWC-DT-011: 測試不得出貨（含頂層 tests/——舊版的子字串比對漏掉它）。"""
        wheel = _make_wheel(tmp_path, {**_good_wheel_contents(), **extra})
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1, f"{case} 應被擋下"

    def test_cwc_dt_012_missing_tasks_rejected(self, tmp_path: Path, monkeypatch) -> None:
        """CWC-DT-012: 不含 tasks/ 的空殼 wheel 被擋下。"""
        wheel = _make_wheel(
            tmp_path,
            {
                f"{_DIST_INFO}/METADATA": "Name: yibi-stack\n",
                f"{_DIST_INFO}/entry_points.txt": _GOOD_ENTRY_POINTS,
            },
        )
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1

    def test_cwc_dt_013_missing_entry_points_rejected(self, tmp_path: Path, monkeypatch) -> None:
        """CWC-DT-013: 缺 entry_points.txt 被擋下（安裝後不會有該指令）。"""
        contents = _good_wheel_contents()
        del contents[f"{_DIST_INFO}/entry_points.txt"]
        wheel = _make_wheel(tmp_path, contents)
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1

    def test_cwc_dt_014_entry_point_target_mismatch_rejected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """CWC-DT-014: entry point 目標與 pyproject 宣告不符時被擋下。"""
        contents = _good_wheel_contents()
        contents[f"{_DIST_INFO}/entry_points.txt"] = (
            "[console_scripts]\nportman = tasks.local_port_manager.cli:WRONG\n"
        )
        wheel = _make_wheel(tmp_path, contents)
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1

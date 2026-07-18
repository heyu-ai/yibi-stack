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
            # round-3 review：allow-list 第一版用 `".dist-info/" in n` 子字串比對，
            # 於是任何路徑只要含該子字串就整個通過。實測確認後改為比對頂層目錄。
            # 這與 round-2 修掉的「`"/tests/" in n` 漏掉頂層 tests/」是同一類缺陷。
            ("偽裝的巢狀 .dist-info", {"plugins/my.dist-info/evil.py": "MALICIOUS = True"}),
            (
                "偽裝的 .dist-info 夾帶帳務工具",
                {"scripts/hack.dist-info/ledger.py": "DSN='localhost:5435/ledgerone'"},
            ),
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

    def test_cwc_dt_015_decoy_dist_info_rejected(self, tmp_path: Path, monkeypatch) -> None:
        """CWC-DT-015: 含兩個 dist-info 時被擋下（誘餌不得勝出）。

        round-3 review：舊版用 `next(n for n in names if n.endswith(".dist-info/
        entry_points.txt"))` 取第一個命中。實測——誘餌 dist-info 帶「正確」的 entry point、
        真品帶壞的，守衛讀誘餌後放行，而安裝出來的指令是壞的。
        """
        contents = _good_wheel_contents()
        # 誘餌字典序在真品之前，且 entry point 是對的
        contents["aaa_decoy-0.0.1.dist-info/METADATA"] = "Name: aaa-decoy\n"
        contents["aaa_decoy-0.0.1.dist-info/entry_points.txt"] = _GOOD_ENTRY_POINTS
        # 真品的 entry point 是壞的——若守衛讀誘餌就不會發現
        contents[f"{_DIST_INFO}/entry_points.txt"] = (
            "[console_scripts]\nportman = tasks.local_port_manager.cli:BROKEN\n"
        )
        wheel = _make_wheel(tmp_path, contents)
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1

    def test_cwc_dt_017_prefix_matching_decoy_dist_info_rejected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """CWC-DT-017: 誘餌 dist-info 名稱**也符合** project prefix 時，仍須被 count guard 擋下。

        這是專門鎖定 `if len(dist_infos) != 1` 這條 count guard 的回歸測試。CWC-DT-015 的
        誘餌名為 aaa_decoy-*（不符 yibi_stack- prefix），故即使拿掉 count guard 也會被
        name-prefix 檢查擋下——那條 assertion 因此對 count guard 不帶資訊。此處誘餌名為
        yibi_stack-0.0.1（符合 prefix、字典序在真品 1.9.0 之前、帶正確 entry point），真品
        帶壞的 entry point。若拿掉 count guard：誘餌通過 name 檢查、sort first 勝出、讀到
        好 entry point 而放行，真品的壞 entry point 從未被檢查——正是 PR #249 round-3 的 bug。
        只有 count guard 能擋，故本測試若在 count guard 被移除後仍綠即為失敗（mutation 反證）。
        """
        contents = _good_wheel_contents()
        contents["yibi_stack-0.0.1.dist-info/METADATA"] = "Name: yibi-stack\n"
        contents["yibi_stack-0.0.1.dist-info/entry_points.txt"] = _GOOD_ENTRY_POINTS
        contents[f"{_DIST_INFO}/entry_points.txt"] = (
            "[console_scripts]\nportman = tasks.local_port_manager.cli:BROKEN\n"
        )
        wheel = _make_wheel(tmp_path, contents)
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1

    def test_cwc_dt_018_path_traversal_member_rejected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """CWC-DT-018: 含 `..` 路徑遍歷／絕對路徑的成員名稱被擋下（防禦縱深）。

        `tasks/../evil.py` 的頂層元件是 tasks，會通過 allow-list，但邏輯上逃出 tasks/。
        正常 uv build 不會產出此類名稱，故此為 hand-crafted-wheel 的防禦縱深。
        """
        contents = _good_wheel_contents()
        contents["tasks/../evil.py"] = "MALICIOUS = True"
        wheel = _make_wheel(tmp_path, contents)
        monkeypatch.setattr(cwc.sys, "argv", ["check_wheel_contents.py", str(wheel)])

        with pytest.raises(SystemExit) as exc:
            cwc.main()

        assert exc.value.code == 1

    def test_cwc_dt_016_mismatched_dist_info_name_rejected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """CWC-DT-016: dist-info 名稱與 pyproject 的 project.name 不符時被擋下。"""
        contents = {
            "tasks/__init__.py": "",
            "tasks/local_port_manager/cli.py": "cli = None",
            "someone_else-1.0.dist-info/METADATA": "Name: someone-else\n",
            "someone_else-1.0.dist-info/entry_points.txt": _GOOD_ENTRY_POINTS,
        }
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

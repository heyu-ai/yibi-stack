"""打包契約測試：[project.scripts] 的 entry point 必須真的解析得到。

背景（ADR-0004 / PR #249 mob review）：本 repo 的 Phase 1 交付物是「tasks/* 可經
`uv tool install` 安裝，skill 直接呼叫裸指令」。但所有 CLI 測試都是
`from tasks.<mod>.cli import cli` 直接 import——**entry point 路徑打錯、module 改名、
packages 設定寫錯，這些測試全數照綠**，缺陷會先在使用者的安裝現場爆，而非 CI。

本檔補上那道缺口的**快速半**：不需要 build wheel，直接驗證 [project.scripts] 宣告的
`module:attr` 真的 import 得到且是個 click command。

**已知覆蓋缺口**：另一半——實際 build wheel、驗證打包範圍（不得夾帶 scripts/ 等）、裝進
乾淨環境執行——**不在本 PR**。那套驗證在 PR #249 的 mob review 中連續三輪成為缺陷來源
（block-list 印 allow-list 訊息、子字串比對可繞過、誘餌 dist-info 讓驗證選錯 metadata），
故抽出獨立 PR 單獨審查，見 issue #262。在它落地之前，wheel 的打包範圍**只靠人工驗證**。

泛用寫法：迭代 [project.scripts] 的所有條目，故 Phase 2/3 加入 mycelium /
pr-orchestrator 時自動涵蓋，不需改動本檔。
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import click
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


def _console_scripts() -> dict[str, str]:
    """讀取 pyproject.toml 的 [project.scripts]。"""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return data.get("project", {}).get("scripts", {})


def _resolve(target: str) -> object:
    """把 'module.path:attr' 解析成實際物件；失敗時 raise（由測試捕捉）。"""
    module_path, _, attr = target.partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


class TestConsoleScripts:
    def test_pkg_st_001_pyproject_declares_at_least_one_console_script(self) -> None:
        """PKG-ST-001: [project.scripts] 非空。

        若這裡變空，代表打包骨架被回退——ADR-0004 的整個前提消失，而其他測試
        （直接 import cli）不會察覺。
        """
        scripts = _console_scripts()

        assert scripts, f"{PYPROJECT_PATH} 的 [project.scripts] 是空的；Phase 1 至少應宣告 portman"

    def test_pkg_st_002_portman_is_declared(self) -> None:
        """PKG-ST-002: portman 已宣告（Phase 1 的白老鼠，SKILL.md 直接呼叫它）。"""
        scripts = _console_scripts()

        assert "portman" in scripts, (
            "plugins/util/skills/local-port-manager/SKILL.md 直接呼叫裸 portman 指令；"
            "移除此宣告會讓該 skill 在所有 plugin-only 安裝上失效"
        )

    @pytest.mark.parametrize("name", sorted(_console_scripts()))
    def test_pkg_st_003_every_entry_point_resolves_to_a_click_command(self, name: str) -> None:
        """PKG-ST-003: 每個 [project.scripts] 條目都解析得到，且是 click command。

        這是 `uv tool install` 後 `<name> --help` 能跑的前提。打錯 module 路徑或 attr
        名稱時，wheel 仍建得出來、所有既有測試仍綠，但安裝出來的指令一執行就 ImportError
        或 AttributeError。
        """
        target = _console_scripts()[name]

        assert ":" in target, f"{name} 的 entry point 應為 'module:attr' 格式，實得 {target!r}"

        resolved = _resolve(target)

        # 用 Command 而非 BaseCommand：後者於 Click 9.0 移除（DeprecationWarning）。
        # Group 繼承自 Command，故涵蓋範圍不變。
        assert isinstance(resolved, click.Command), (
            f"{name} = {target!r} 解析到 {type(resolved).__name__}，不是 click command；"
            f"安裝後執行該指令會失敗"
        )

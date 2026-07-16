"""LPM CLI 測試：版本閘門。

ADR-0004 把「版本落差」列為 plugin-primary 交付的首要風險：安裝的 CLI 可能落後
plugin 的 SKILL.md。少了可靠的 --version，skill 的 preflight 無從判斷，等於把大聲的
路徑失敗換成安靜的行為不一致。故 --version 必須回報套件 metadata 的真實版本，
不得硬編碼。
"""

from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tasks.local_port_manager.cli import cli

CLI_SVC = "tasks.local_port_manager.service"


class TestInit:
    def test_lpm_st_001_init_creates_empty_registry(self, tmp_path: Path) -> None:
        """LPM-ST-001: init 建立空 registry，不預載任何專案資料。

        本工具會公開發佈，不得預載作者的個人專案（yibi-mvp / voice-lab / coachly /
        coaching365）。init 只該建立通用骨架，由使用者自行 reserve。
        """
        registry_path = tmp_path / "ports.json"
        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["init"])

        assert result.exit_code == 0
        assert registry_path.exists()

        from tasks.local_port_manager.models import PortRegistry

        registry = PortRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        assert registry.entries == []

    def test_lpm_st_002_init_keeps_generic_ranges(self, tmp_path: Path) -> None:
        """LPM-ST-002: init 仍寫入通用 port range（那不是個人資料）。"""
        registry_path = tmp_path / "ports.json"
        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            CliRunner().invoke(cli, ["init"])

        from tasks.local_port_manager.models import PortRegistry

        registry = PortRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        assert registry.ranges["db"] == [5400, 5499]


class TestVersionOption:
    def test_lpm_cv_001_version_flag_reports_package_version(self) -> None:
        """LPM-CV-001: --version 輸出與套件 metadata 一致的版本號。"""
        result = CliRunner().invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert version("yibi-stack") in result.output

    def test_lpm_cv_002_version_flag_not_hardcoded(self) -> None:
        """LPM-CV-002: --version 取自 metadata，非硬編碼字串。

        以 metadata 為單一真相來源：若有人改 pyproject 的 version 卻沒同步 CLI，
        本測試會抓到（硬編碼版本會與 metadata 分歧）。
        """
        result = CliRunner().invoke(cli, ["--version"])

        expected = version("yibi-stack")
        # 版本號必須完整出現，且不是空字串／佔位值
        assert expected
        assert expected not in {"0.0.0", "unknown"}
        assert expected in result.output

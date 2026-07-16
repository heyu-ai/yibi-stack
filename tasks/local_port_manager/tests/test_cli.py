"""LPM CLI 測試：版本閘門。

ADR-0004 把「版本落差」列為 plugin-primary 交付的首要風險：安裝的 CLI 可能落後
plugin 的 SKILL.md。少了可靠的 --version，skill 的 preflight 無從判斷，等於把大聲的
路徑失敗換成安靜的行為不一致。故 --version 必須回報套件 metadata 的真實版本，
不得硬編碼。
"""

from importlib.metadata import version

from click.testing import CliRunner

from tasks.local_port_manager.cli import cli


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

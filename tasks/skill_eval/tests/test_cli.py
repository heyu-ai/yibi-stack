"""skill_eval CLI 測試（CliRunner，fixture 以 tmp 目錄自足）。"""

import json
from pathlib import Path

from click.testing import CliRunner

from tasks.skill_eval.cli import cli


def write_fixture(skills_dir: Path, skill: str = "demo") -> None:
    """在 tmp skills 目錄建立一份 trigger_eval.json。"""
    d = skills_dir / skill
    d.mkdir(parents=True, exist_ok=True)
    (d / "trigger_eval.json").write_text(
        json.dumps(
            {
                "skill": skill,
                "direct": [{"prompt": "run demo", "expect_trigger": True}],
                "indirect": [{"prompt": "start the demo", "expect_trigger": True}],
                "negative": [{"prompt": "unrelated", "expect_trigger": False}],
            }
        ),
        encoding="utf-8",
    )


class TestCliHelp:
    def test_seval_cli_001_subcommands_registered(self) -> None:
        """SEVAL-CLI-001: --help 列出 eval 與 baseline（rule 08 dead-code trap）。"""
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "eval" in result.output
        assert "baseline" in result.output


class TestEval:
    def test_seval_cli_002_emit_manifest(self, tmp_path: Path) -> None:
        """SEVAL-CLI-002: eval --emit-manifest 印出任務 manifest JSON。"""
        write_fixture(tmp_path)
        result = CliRunner().invoke(
            cli,
            ["eval", "--skill", "demo", "--skills-dir", str(tmp_path), "--emit-manifest"],
        )
        assert result.exit_code == 0
        manifest = json.loads(result.output)
        assert len(manifest) == 3
        assert manifest[0]["skill"] == "demo"

    def test_seval_cli_003_eval_with_judgments_ok(self, tmp_path: Path) -> None:
        """SEVAL-CLI-003: eval 帶 judgments + baseline 跑通，無回歸回 [OK]。"""
        write_fixture(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"demo": {"direct": 1.0}}), encoding="utf-8")
        result = CliRunner().invoke(
            cli,
            [
                "eval",
                "--skill",
                "demo",
                "--skills-dir",
                str(tmp_path),
                "--judgments",
                str(judgments),
                "--baseline",
                str(baseline),
            ],
        )
        assert result.exit_code == 0
        assert "[OK]" in result.output

    def test_seval_cli_004_missing_fixture_fails(self, tmp_path: Path) -> None:
        """SEVAL-CLI-004: 缺 fixture 的 skill -> exit 1 且 [FAIL]（不當作通過）。"""
        result = CliRunner().invoke(
            cli,
            ["eval", "--skill", "ghost", "--skills-dir", str(tmp_path), "--emit-manifest"],
        )
        assert result.exit_code == 1
        assert "[FAIL]" in result.output

    def test_seval_cli_005_regression_exits_nonzero(self, tmp_path: Path) -> None:
        """SEVAL-CLI-005: baseline 高於當前 -> eval 偵測回歸 exit 1。"""
        write_fixture(tmp_path)
        judgments = tmp_path / "j.json"
        # negative 被誤觸發 -> negative pass rate 0.0
        judgments.write_text(json.dumps([True, True, True]), encoding="utf-8")
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"demo": {"negative": 1.0}}), encoding="utf-8")
        result = CliRunner().invoke(
            cli,
            [
                "eval",
                "--skill",
                "demo",
                "--skills-dir",
                str(tmp_path),
                "--judgments",
                str(judgments),
                "--baseline",
                str(baseline),
            ],
        )
        assert result.exit_code == 1
        assert "回歸" in result.output


class TestBaseline:
    def test_seval_cli_006_baseline_writes_file(self, tmp_path: Path) -> None:
        """SEVAL-CLI-006: baseline subcommand 以 judgments 寫出 baseline 檔。"""
        write_fixture(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        out = tmp_path / "baseline.json"
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "--skill",
                "demo",
                "--skills-dir",
                str(tmp_path),
                "--judgments",
                str(judgments),
                "--baseline",
                str(out),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["demo"]["direct"] == 1.0
        assert data["demo"]["negative"] == 1.0

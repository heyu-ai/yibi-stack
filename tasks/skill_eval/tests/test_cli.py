"""skill_eval CLI 測試（CliRunner，fixture 以 tmp 目錄自足）。"""

import json
from pathlib import Path

from click.testing import CliRunner

from tasks.skill_eval.cli import cli
from tasks.skill_eval.config import orphan_plugin_fixtures


def write_fixture(skills_dir: Path, skill: str = "demo", **arrays: object) -> None:
    """在 tmp skills 目錄建立一份 trigger_eval.json（arrays 可覆寫三類內容）。"""
    d = skills_dir / skill
    d.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "skill": skill,
        "direct": [{"prompt": "run demo", "expect_trigger": True}],
        "indirect": [{"prompt": "start the demo", "expect_trigger": True}],
        "negative": [{"prompt": "unrelated", "expect_trigger": False}],
    }
    payload.update(arrays)
    (d / "trigger_eval.json").write_text(json.dumps(payload), encoding="utf-8")


class TestCliHelp:
    def test_seval_cli_001_subcommands_registered(self) -> None:
        """SEVAL-CLI-001: --help 列出 eval 與 baseline（rule 08 dead-code trap）。
        spec: skill-trigger-eval#eval-baseline-discoverable"""
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "eval" in result.output
        assert "baseline" in result.output


class TestEval:
    def test_seval_cli_002_emit_manifest(self, tmp_path: Path) -> None:
        """SEVAL-CLI-002: eval --emit-manifest 印出任務 manifest JSON。
        spec: skill-trigger-eval#core-scores-via-interface"""
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
        """SEVAL-CLI-003: eval 帶 judgments + baseline 跑通，無回歸回 [OK]。
        spec: skill-trigger-eval#within-tolerance-passes"""
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
        """SEVAL-CLI-004: 缺 fixture 的 skill -> exit 1 且 [FAIL]（不當作通過）。
        spec: skill-trigger-eval#absent-fixture-fails-loud"""
        result = CliRunner().invoke(
            cli,
            ["eval", "--skill", "ghost", "--skills-dir", str(tmp_path), "--emit-manifest"],
        )
        assert result.exit_code == 1
        assert "[FAIL]" in result.output

    def test_seval_cli_005_regression_exits_nonzero(self, tmp_path: Path) -> None:
        """SEVAL-CLI-005: baseline 高於當前 -> eval 偵測回歸 exit 1。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
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

    def test_seval_cli_007_empty_fixture_fails(self, tmp_path: Path) -> None:
        """SEVAL-CLI-007: fixture 三類皆空 -> [FAIL] exit 1（不 vacuous pass）。
        spec: skill-trigger-eval#absent-fixture-fails-loud"""
        write_fixture(tmp_path, skill="empty", direct=[], indirect=[], negative=[])
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([]), encoding="utf-8")
        result = CliRunner().invoke(
            cli,
            [
                "eval",
                "--skill",
                "empty",
                "--skills-dir",
                str(tmp_path),
                "--judgments",
                str(judgments),
            ],
        )
        assert result.exit_code == 1
        assert "無可評測項目" in result.output

    def test_seval_cli_008_manifest_mismatch_fails(self, tmp_path: Path) -> None:
        """SEVAL-CLI-008: fixture 在 emit-manifest 後變動 -> --manifest 核對失敗 exit 1。
        spec: skill-trigger-eval#verdict-count-mismatch-surfaced"""
        write_fixture(tmp_path)
        emit = CliRunner().invoke(
            cli, ["eval", "--skill", "demo", "--skills-dir", str(tmp_path), "--emit-manifest"]
        )
        manifest = tmp_path / "manifest.json"
        manifest.write_text(emit.output, encoding="utf-8")
        # fixture 變動：改掉 direct prompt 文字（簽章改變）
        write_fixture(tmp_path, direct=[{"prompt": "CHANGED", "expect_trigger": True}])
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        result = CliRunner().invoke(
            cli,
            [
                "eval",
                "--skill",
                "demo",
                "--skills-dir",
                str(tmp_path),
                "--manifest",
                str(manifest),
                "--judgments",
                str(judgments),
            ],
        )
        assert result.exit_code == 1
        assert "manifest 與當前 fixture 不符" in result.output

    def test_seval_cli_009_manifest_match_proceeds(self, tmp_path: Path) -> None:
        """SEVAL-CLI-009: fixture 未變動 -> --manifest 核對通過並正常評測。
        spec: skill-trigger-eval#core-scores-via-interface"""
        write_fixture(tmp_path)
        emit = CliRunner().invoke(
            cli, ["eval", "--skill", "demo", "--skills-dir", str(tmp_path), "--emit-manifest"]
        )
        manifest = tmp_path / "manifest.json"
        manifest.write_text(emit.output, encoding="utf-8")
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        result = CliRunner().invoke(
            cli,
            [
                "eval",
                "--skill",
                "demo",
                "--skills-dir",
                str(tmp_path),
                "--manifest",
                str(manifest),
                "--judgments",
                str(judgments),
            ],
        )
        assert result.exit_code == 0
        assert "[OK]" in result.output


class TestBaseline:
    def test_seval_cli_006_baseline_writes_file(self, tmp_path: Path) -> None:
        """SEVAL-CLI-006: baseline subcommand 以 judgments 寫出 baseline 檔。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
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


class TestOrphanDiscovery:
    def test_seval_eg_004_plugin_only_fixture_flagged_as_orphan(self, tmp_path: Path) -> None:
        """SEVAL-EG-004: plugins/ 未 symlink 的 fixture 被列為 orphan（--all 漏評防護）。
        spec: skill-trigger-eval#eval-baseline-discoverable"""
        skills_dir = tmp_path / "skills"
        plugins_dir = tmp_path / "plugins"
        # skills/ 有一個一般 fixture（非 orphan）
        write_fixture(skills_dir, skill="covered")
        # plugins/pack/skills/hidden/trigger_eval.json：未 symlink 到 skills/ -> orphan
        hidden = plugins_dir / "pack" / "skills" / "hidden"
        hidden.mkdir(parents=True)
        (hidden / "trigger_eval.json").write_text(
            json.dumps({"skill": "hidden", "direct": [], "indirect": [], "negative": []}),
            encoding="utf-8",
        )
        orphans = orphan_plugin_fixtures(skills_dir=skills_dir, plugins_dir=plugins_dir)
        assert len(orphans) == 1
        assert orphans[0].name == "trigger_eval.json"
        assert "hidden" in str(orphans[0])

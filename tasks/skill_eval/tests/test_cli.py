"""skill_eval CLI 測試（CliRunner，fixture 以 tmp 目錄自足）。"""

import json
from pathlib import Path

import pytest
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


def emit_manifest(skills_dir: Path, *sel: str, out: Path | None = None) -> Path:
    """跑 --emit-manifest 並把輸出存檔，回傳該路徑（供 --manifest 綁定用）。

    sel 為 skill 選擇參數（如 "--skill", "demo" 或 "--all"）；預設 --skill demo。
    """
    args = list(sel) or ["--skill", "demo"]
    result = CliRunner().invoke(
        cli, ["eval", *args, "--skills-dir", str(skills_dir), "--emit-manifest"]
    )
    assert result.exit_code == 0, f"emit-manifest 失敗：{result.output}"
    path = out or (skills_dir.parent / "manifest.json")
    path.write_text(result.stdout, encoding="utf-8")
    return path


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
        """SEVAL-CLI-003: eval 帶 manifest + judgments + baseline 跑通，無回歸回 [OK]。
        spec: skill-trigger-eval#within-tolerance-passes"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
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
                "--manifest",
                str(manifest),
                "--judgments",
                str(judgments),
                "--baseline",
                str(baseline),
            ],
        )
        assert result.exit_code == 0
        assert "[OK]" in result.output

    def test_seval_cli_012_judgments_without_manifest_fails(self, tmp_path: Path) -> None:
        """SEVAL-CLI-012: --judgments 未搭 --manifest -> [FAIL] exit 1（不得靜默計分）。
        spec: skill-trigger-eval#manifest-binding-required"""
        write_fixture(tmp_path)
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
                "--judgments",
                str(judgments),
            ],
        )
        assert result.exit_code == 1
        assert "請提供 --manifest" in result.output

    def test_seval_cli_013_no_manifest_check_warns_and_proceeds(self, tmp_path: Path) -> None:
        """SEVAL-CLI-013: --no-manifest-check 顯式跳過核對時印 [WARN] 並續跑。
        spec: skill-trigger-eval#manifest-binding-required"""
        write_fixture(tmp_path)
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
                "--judgments",
                str(judgments),
                "--no-manifest-check",
            ],
        )
        assert result.exit_code == 0
        assert "--no-manifest-check" in result.output
        assert "[WARN]" in result.output
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
        manifest = emit_manifest(tmp_path)
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
                "--manifest",
                str(manifest),
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
        spec: skill-trigger-eval#empty-fixture-fails-loud"""
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
        spec: skill-trigger-eval#manifest-binding-drift-fails"""
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
        spec: skill-trigger-eval#manifest-binding-drift-fails"""
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
        """SEVAL-CLI-006: baseline subcommand 以 manifest + judgments 寫出 baseline 檔。
        spec: skill-trigger-eval#eval-baseline-discoverable"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
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
                "--manifest",
                str(manifest),
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

    def test_seval_cli_014_baseline_manifest_drift_fails(self, tmp_path: Path) -> None:
        """SEVAL-CLI-014: fixture 在 emit-manifest 後變動 -> baseline 核對失敗，不寫出污染基準。

        eval 與 baseline 消費同一份 index 對位的 judgments；baseline 寫入的是往後每次 gate 的
        比較基準，錯位污染是持久的，故此路徑必須同樣被擋。
        spec: skill-trigger-eval#manifest-binding-drift-fails"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        # fixture 變動：同數量、改 prompt 文字（長度檢查抓不到，只有簽章能抓）
        write_fixture(tmp_path, direct=[{"prompt": "CHANGED", "expect_trigger": True}])
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
                "--manifest",
                str(manifest),
                "--judgments",
                str(judgments),
                "--baseline",
                str(out),
            ],
        )
        assert result.exit_code == 1
        assert "manifest 與當前 fixture 不符" in result.output
        assert not out.exists(), "核對失敗時不得寫出 baseline 檔"

    def test_seval_cli_015_baseline_requires_manifest(self, tmp_path: Path) -> None:
        """SEVAL-CLI-015: baseline 未給 --manifest -> 非零退出（不像 eval 有跳過選項）。
        spec: skill-trigger-eval#manifest-binding-required"""
        write_fixture(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
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
            ],
        )
        assert result.exit_code != 0
        assert "--manifest" in result.output


class TestOrphanDiscovery:
    def test_seval_eg_004_plugin_only_fixture_flagged_as_orphan(self, tmp_path: Path) -> None:
        """SEVAL-EG-004: plugins/ 未 symlink 的 fixture 被列為 orphan（--all 漏評防護）。
        spec: skill-trigger-eval#orphan-plugin-fixture-warned"""
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

    def test_seval_eg_008_nested_sub_skill_fixture_flagged_as_orphan(self, tmp_path: Path) -> None:
        """SEVAL-EG-008: plugins/ 巢狀 sub-skill 的 fixture 被列為 orphan（`**` 非 `*`）。

        釘住 config.py 的 `*/skills/**/trigger_eval.json`：rule 02「`*` 不跨 `/`」，改回 `*`
        會讓 <pack>/skills/<name>/<sub>/ 這層靜默漏掉且無測試會失敗（PR #190 同類事故）。
        spec: skill-trigger-eval#orphan-plugin-fixture-warned"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        plugins_dir = tmp_path / "plugins"
        # 真實形狀：plugins/growth/skills/mycelium/recap/ —— 比 <pack>/skills/<name>/ 多一層
        nested = plugins_dir / "growth" / "skills" / "mycelium" / "recap"
        nested.mkdir(parents=True)
        (nested / "trigger_eval.json").write_text(
            json.dumps({"skill": "recap", "direct": [], "indirect": [], "negative": []}),
            encoding="utf-8",
        )
        orphans = orphan_plugin_fixtures(skills_dir=skills_dir, plugins_dir=plugins_dir)
        assert len(orphans) == 1, "巢狀 sub-skill fixture 應被偵測為 orphan"
        assert "recap" in str(orphans[0])

    def test_seval_eg_005_symlinked_plugin_fixture_not_orphan(self, tmp_path: Path) -> None:
        """SEVAL-EG-005: 已 symlink 到 skills/ 的 plugin fixture 不算 orphan（正向路徑）。
        spec: skill-trigger-eval#orphan-plugin-fixture-warned"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        plugins_dir = tmp_path / "plugins"
        real = plugins_dir / "pack" / "skills" / "linked"
        real.mkdir(parents=True)
        (real / "trigger_eval.json").write_text(
            json.dumps({"skill": "linked", "direct": [], "indirect": [], "negative": []}),
            encoding="utf-8",
        )
        (skills_dir / "linked").symlink_to(real)
        assert orphan_plugin_fixtures(skills_dir=skills_dir, plugins_dir=plugins_dir) == []


class TestAllScope:
    def test_seval_cli_016_all_warns_orphan_even_when_skills_empty(self, tmp_path: Path) -> None:
        """SEVAL-CLI-016: skills/ 無 fixture 但 plugins/ 有 orphan -> 仍印 [WARN] 才 [FAIL]。

        [WARN] 必須排在 `if not names` 之前：全部 fixture 都是 plugin-only 時，若先 [FAIL]
        就會告知「找不到任何 fixture」，而實際上有 N 個搆不到——正是此警告存在的理由。
        spec: skill-trigger-eval#orphan-plugin-fixture-warned"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)  # 存在但無任何 fixture
        hidden = tmp_path / "plugins" / "pack" / "skills" / "hidden"
        hidden.mkdir(parents=True)
        (hidden / "trigger_eval.json").write_text(
            json.dumps({"skill": "hidden", "direct": [{"prompt": "x", "expect_trigger": True}]}),
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            cli, ["eval", "--all", "--skills-dir", str(skills_dir), "--emit-manifest"]
        )
        assert result.exit_code == 1, "skills/ 無 fixture 仍應 [FAIL]"
        assert "[WARN]" in result.output, "[FAIL] 前必須先報出搆不到的 plugin fixture"
        assert "hidden" in result.output, "[WARN] 必須指名該 fixture，否則使用者無從得知"

    def test_seval_cli_010_all_warns_orphan_plugin_fixture(self, tmp_path: Path) -> None:
        """SEVAL-CLI-010: eval --all 對 sibling plugins/ 的未涵蓋 fixture 印 [WARN]。
        spec: skill-trigger-eval#orphan-plugin-fixture-warned"""
        skills_dir = tmp_path / "skills"
        write_fixture(skills_dir, skill="covered")
        hidden = tmp_path / "plugins" / "pack" / "skills" / "hidden"
        hidden.mkdir(parents=True)
        (hidden / "trigger_eval.json").write_text(
            json.dumps({"skill": "hidden", "direct": [], "indirect": [], "negative": []}),
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            cli, ["eval", "--all", "--skills-dir", str(skills_dir), "--emit-manifest"]
        )
        assert result.exit_code == 0
        assert "[WARN]" in result.output
        assert "pack/skills/hidden/trigger_eval.json" in result.output
        # 關鍵斷言：絕對路徑「不得」出現。custom skills_dir 下 base=skills_dir.parent，
        # 相對化應該成功。只斷言相對路徑存在是不夠的——絕對路徑本身就含該子字串，
        # 故 base 恆用 PROJECT_ROOT 時（相對化失敗、改印絕對路徑）測試照樣會過。
        assert str(hidden / "trigger_eval.json") not in result.output

    def test_seval_cli_017_default_layout_warns_orphan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEVAL-CLI-017: 不給 --skills-dir 時走預設佈局分支（SKILLS_DIR / PLUGINS_DIR）。

        其餘測試皆顯式傳 --skills-dir，故 `skills_dir is None` 這條——正是 production
        `--all` 實際走的路徑——從未被執行過。此處同時覆蓋 relative_to 的 ValueError
        fallback：base 為真實 PROJECT_ROOT，orphan 卻在 tmp_path 下，相對化必然失敗而
        改印絕對路徑。
        spec: skill-trigger-eval#orphan-plugin-fixture-warned"""
        from tasks.skill_eval import config as config_mod

        skills_dir = tmp_path / "skills"
        write_fixture(skills_dir, skill="covered")
        hidden = tmp_path / "plugins" / "pack" / "skills" / "hidden"
        hidden.mkdir(parents=True)
        (hidden / "trigger_eval.json").write_text(
            json.dumps({"skill": "hidden", "direct": [{"prompt": "x", "expect_trigger": True}]}),
            encoding="utf-8",
        )
        # 只 patch config 的模組級常數：_warn_orphan_fixtures 於函式內才
        # `from tasks._paths import PROJECT_ROOT`，patch cli 的模組屬性不會生效。
        monkeypatch.setattr(config_mod, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(config_mod, "PLUGINS_DIR", tmp_path / "plugins")

        result = CliRunner().invoke(cli, ["eval", "--all", "--emit-manifest"])
        assert result.exit_code == 0
        assert "[WARN]" in result.output
        # base=PROJECT_ROOT 與 tmp_path 無共同前綴 -> ValueError -> 印絕對路徑
        assert str(hidden / "trigger_eval.json") in result.output

    def test_seval_cli_011_all_empty_skill_fails_not_vacuous(self, tmp_path: Path) -> None:
        """SEVAL-CLI-011: --all 夾帶一個空 fixture -> [FAIL] 指名該 skill（非 vacuous [OK]）。
        spec: skill-trigger-eval#empty-fixture-fails-loud"""
        skills_dir = tmp_path / "skills"
        write_fixture(skills_dir, skill="good")
        write_fixture(skills_dir, skill="empty", direct=[], indirect=[], negative=[])
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        result = CliRunner().invoke(
            cli,
            ["eval", "--all", "--skills-dir", str(skills_dir), "--judgments", str(judgments)],
        )
        assert result.exit_code == 1
        # 兩者都要斷言（rule 09 斷言語意精確）：只斷言 "empty" 會被任何含該字串的
        # 失敗路徑滿足（如缺 --manifest 的 [FAIL]），釘不住「指名空 skill」這個契約。
        assert "無可評測項目" in result.output
        assert "empty" in result.output


class TestToleranceValidation:
    def test_seval_vl_009_tolerance_nan_rejected(self, tmp_path: Path) -> None:
        """SEVAL-VL-009: --tolerance nan -> [FAIL]（否則所有比較恆 False，等同關閉 gate）。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([False, False, True]), encoding="utf-8")
        baseline = tmp_path / "b.json"
        baseline.write_text(json.dumps({"demo": {"direct": 1.0}}), encoding="utf-8")
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
                "--baseline",
                str(baseline),
                "--tolerance",
                "nan",
            ],
        )
        assert result.exit_code == 1
        assert "--tolerance 須落在" in result.output

    def test_seval_vl_010_tolerance_ge_one_rejected(self, tmp_path: Path) -> None:
        """SEVAL-VL-010: --tolerance >= 1.0 -> [FAIL]（門檻寬到永不觸發即等同關閉 gate）。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([False, False, True]), encoding="utf-8")
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
                "--tolerance",
                "1.5",
            ],
        )
        assert result.exit_code == 1
        assert "--tolerance 須落在" in result.output


class TestBaselineValidation:
    def test_seval_vl_011_baseline_null_value_rejected(self, tmp_path: Path) -> None:
        """SEVAL-VL-011: baseline 含 null -> [FAIL]，不得與「無此類 baseline」同路徑。

        未驗證時 null 走 `if base is None: continue`，讓 0.00 的 pass rate 靜默回報無回歸。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([False, False, True]), encoding="utf-8")
        baseline = tmp_path / "b.json"
        baseline.write_text(json.dumps({"demo": {"direct": None}}), encoding="utf-8")
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
                "--baseline",
                str(baseline),
            ],
        )
        assert result.exit_code == 1
        assert "baseline 格式錯誤" in result.output

    def test_seval_vl_013_baseline_unknown_class_key_rejected(self, tmp_path: Path) -> None:
        """SEVAL-VL-013: baseline 含未知 class key（錯字）-> [FAIL]，不得靜默關閉該類 gate。

        compare_baseline 以 `skill_base.get(str(score.cls))` 查表，查無即
        `if base is None: continue`——所以 `negatve` 這種一字之差會讓該類靜默離開 gate，
        方向比值域錯誤更危險（靜默放行 vs 報錯）。手改壞的檔案正是錯字的來源。
        spec: skill-trigger-eval#corrupt-baseline-rejected"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        judgments = tmp_path / "j.json"
        # negative 被誤觸發 -> negative pass rate 0.00，對 baseline 1.0 必須判回歸
        judgments.write_text(json.dumps([True, True, True]), encoding="utf-8")
        baseline = tmp_path / "b.json"
        baseline.write_text(json.dumps({"demo": {"negatve": 1.0}}), encoding="utf-8")
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
                "--baseline",
                str(baseline),
            ],
        )
        assert result.exit_code == 1
        assert "baseline 格式錯誤" in result.output, (
            "錯字 key 必須 [FAIL]，不得當成「無此類基準」略過"
        )

    def test_seval_vl_014_baseline_out_of_range_rate_rejected(self, tmp_path: Path) -> None:
        """SEVAL-VL-014: baseline pass rate 值域外（負數）-> [FAIL]，不得靜默關閉 gate。

        負數 baseline 讓 `pass_rate < base - tol` 恆為 False，效果與 nan（VL-009）、
        >= 1.0（VL-010）相同：0% 通過率照樣回報綠燈。此測試釘住 _BaselineFile 的
        ge/le 值域約束——沒有它，拿掉該約束不會有任何測試失敗。
        spec: skill-trigger-eval#corrupt-baseline-rejected"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        judgments = tmp_path / "j.json"
        # 全部答錯 -> direct 0.00，對任何合法 baseline 都該判回歸
        judgments.write_text(json.dumps([False, False, True]), encoding="utf-8")
        baseline = tmp_path / "b.json"
        baseline.write_text(json.dumps({"demo": {"direct": -1.0}}), encoding="utf-8")
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
                "--baseline",
                str(baseline),
            ],
        )
        assert result.exit_code == 1
        assert "baseline 格式錯誤" in result.output

    def test_seval_vl_012_baseline_wrong_shape_fails_loud(self, tmp_path: Path) -> None:
        """SEVAL-VL-012: baseline 為 list -> [FAIL]，不得拋 raw traceback。
        spec: skill-trigger-eval#regression-below-tolerance-exits-nonzero"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        baseline = tmp_path / "b.json"
        baseline.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
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
                "--baseline",
                str(baseline),
            ],
        )
        assert result.exit_code == 1
        assert "baseline 格式錯誤" in result.output


class TestManifestErrorBranches:
    def test_seval_eg_006_manifest_unreadable_fails(self, tmp_path: Path) -> None:
        """SEVAL-EG-006: --manifest 檔非合法 JSON -> [FAIL] 讀取失敗 exit 1。
        spec: skill-trigger-eval#manifest-binding-drift-fails"""
        write_fixture(tmp_path)
        bad = tmp_path / "manifest.json"
        bad.write_text("{not json", encoding="utf-8")
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
                str(bad),
                "--judgments",
                str(judgments),
            ],
        )
        assert result.exit_code == 1
        assert "讀取 manifest 失敗" in result.output

    def test_seval_eg_007_manifest_non_list_fails(self, tmp_path: Path) -> None:
        """SEVAL-EG-007: --manifest 檔非陣列 -> [FAIL] 格式錯誤 exit 1。
        spec: skill-trigger-eval#manifest-binding-drift-fails"""
        write_fixture(tmp_path)
        bad = tmp_path / "manifest.json"
        bad.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
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
                str(bad),
                "--judgments",
                str(judgments),
            ],
        )
        assert result.exit_code == 1
        assert "manifest 檔格式錯誤" in result.output

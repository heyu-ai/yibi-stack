"""skill_eval CLI 測試（CliRunner，fixture 以 tmp 目錄自足）。"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tasks.skill_eval.cli import cli
from tasks.skill_eval.config import resolve_fixture_index


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

    def test_seval_cli_019_baseline_skill_merges_not_clobbers(self, tmp_path: Path) -> None:
        """SEVAL-CLI-019: `baseline --skill` 只更新該 skill，保留其他條目（issue #219）。

        整檔覆寫等於把其他 skill 的基準一次抹掉，之後每個都變成「無基準」而靜默離開
        gate——一次無害的單 skill 重取基準，就把整個回歸防護關掉。
        spec: skill-trigger-eval#baseline-merge-preserves-other-skills"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path)
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        out = tmp_path / "baseline.json"
        out.write_text(json.dumps({"other": {"direct": 1.0, "negative": 1.0}}), encoding="utf-8")

        result = CliRunner().invoke(
            cli,
            # fmt: off
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
            # fmt: on
        )
        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["other"] == {"direct": 1.0, "negative": 1.0}, "其他 skill 的基準不得被抹掉"
        assert data["demo"]["direct"] == 1.0

    def test_seval_cli_020_baseline_all_is_authoritative_rewrite(self, tmp_path: Path) -> None:
        """SEVAL-CLI-020: `baseline --all` 為權威重寫，讓已刪 fixture 的陳舊條目消失。

        與 --skill 的合併語意相對：留著陳舊條目會在 baseline ∪ current 比對下永遠回報
        「該 skill 缺席」，使 gate 無法回到綠燈。
        spec: skill-trigger-eval#baseline-merge-preserves-other-skills"""
        write_fixture(tmp_path)
        manifest = emit_manifest(tmp_path, "--all")
        judgments = tmp_path / "j.json"
        judgments.write_text(json.dumps([True, True, False]), encoding="utf-8")
        out = tmp_path / "baseline.json"
        out.write_text(json.dumps({"deleted": {"direct": 1.0}}), encoding="utf-8")

        result = CliRunner().invoke(
            cli,
            # fmt: off
            [
                "baseline",
                "--all",
                "--skills-dir",
                str(tmp_path),
                "--manifest",
                str(manifest),
                "--judgments",
                str(judgments),
                "--baseline",
                str(out),
            ],
            # fmt: on
        )
        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "deleted" not in data, "--all 應為權威重寫，陳舊條目須消失"
        assert "demo" in data

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


def write_plugin_fixture(plugins_dir: Path, *parts: str, skill: str) -> Path:
    """在 plugins/<pack>/skills/<...> 建立一份 fixture，回傳該 skill 目錄。"""
    d = plugins_dir.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    (d / "trigger_eval.json").write_text(
        json.dumps(
            {
                "skill": skill,
                "direct": [{"prompt": f"run {skill}", "expect_trigger": True}],
                "indirect": [],
                "negative": [],
            }
        ),
        encoding="utf-8",
    )
    return d


class TestFixtureIndex:
    def test_seval_eg_004_plugin_only_fixture_is_indexed(self, tmp_path: Path) -> None:
        """SEVAL-EG-004: plugins/ 未 symlink 的 fixture 仍進入索引（--all 不再漏評）。

        這是讓 gate 從「結構上不可能運作」變成可運作的那一步：repo 唯一一份 fixture
        （pr-cycle-fast）正是 plugin-only，只掃 skills/ 時 --all 掃不到任何東西。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        skills_dir = tmp_path / "skills"
        plugins_dir = tmp_path / "plugins"
        write_fixture(skills_dir, skill="covered")
        write_plugin_fixture(plugins_dir, "pack", "skills", "hidden", skill="hidden")

        index = resolve_fixture_index(skills_dir=skills_dir, plugins_dir=plugins_dir)
        assert sorted(index) == ["covered", "hidden"]
        assert index["hidden"].parent.name == "hidden"

    def test_seval_eg_008_nested_sub_skill_fixture_is_indexed(self, tmp_path: Path) -> None:
        """SEVAL-EG-008: plugins/ 巢狀 sub-skill 的 fixture 進入索引（`**` 非 `*`）。

        釘住 config.py 的 `*/skills/**/trigger_eval.json`：rule 02「`*` 不跨 `/`」，改回 `*`
        會讓 <pack>/skills/<name>/<sub>/ 這層靜默漏掉且無測試會失敗（PR #190 同類事故）。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        plugins_dir = tmp_path / "plugins"
        # 真實形狀：plugins/growth/skills/mycelium/recap/ —— 比 <pack>/skills/<name>/ 多一層
        write_plugin_fixture(plugins_dir, "growth", "skills", "mycelium", "recap", skill="recap")

        index = resolve_fixture_index(skills_dir=skills_dir, plugins_dir=plugins_dir)
        assert list(index) == ["recap"], "巢狀 sub-skill fixture 應被索引"

    def test_seval_eg_005_symlinked_plugin_fixture_indexed_once(self, tmp_path: Path) -> None:
        """SEVAL-EG-005: 已 symlink 到 skills/ 的 plugin fixture 只登記一次（realpath 去重）。

        skills/<name> 與其 plugin target 是同一個實體檔；若未以 realpath 去重，會被當成
        名稱衝突而誤報 RuntimeError——27 個 symlink skill 全都會踩到。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        plugins_dir = tmp_path / "plugins"
        real = write_plugin_fixture(plugins_dir, "pack", "skills", "linked", skill="linked")
        (skills_dir / "linked").symlink_to(real)

        index = resolve_fixture_index(skills_dir=skills_dir, plugins_dir=plugins_dir)
        assert list(index) == ["linked"]
        # 保留 skills/ 這條路徑（先登記者優先），不是 plugin 內的實體路徑
        assert index["linked"].parent.parent == skills_dir

    def test_seval_eg_009_name_collision_fails_loud(self, tmp_path: Path) -> None:
        """SEVAL-EG-009: 兩個不同實體檔同名 -> RuntimeError，不靜默留一個。

        baseline 依 skill 名稱存放，靜默保留其中一個會讓另一個永久離開 gate，且兩者
        會互相覆寫彼此的基準——正是 gate 靜默失效的形狀。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        plugins_dir = tmp_path / "plugins"
        write_plugin_fixture(plugins_dir, "growth", "skills", "mycelium", "recap", skill="recap")
        write_plugin_fixture(plugins_dir, "other", "skills", "recap", skill="recap")

        with pytest.raises(RuntimeError, match="名稱衝突"):
            resolve_fixture_index(skills_dir=skills_dir, plugins_dir=plugins_dir)


class TestAllScope:
    def test_seval_cli_016_all_evaluates_plugin_only_when_skills_empty(
        self, tmp_path: Path
    ) -> None:
        """SEVAL-CLI-016: skills/ 無 fixture 但 plugins/ 有 -> 評測它，不再 [FAIL]。

        這是 repo 的真實形狀（唯一的 fixture 是 plugin-only），也是舊行為下 --all
        什麼都掃不到的原因。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)  # 存在但無任何 fixture
        write_plugin_fixture(tmp_path / "plugins", "pack", "skills", "hidden", skill="hidden")

        result = CliRunner().invoke(
            cli, ["eval", "--all", "--skills-dir", str(skills_dir), "--emit-manifest"]
        )
        assert result.exit_code == 0, f"plugin-only fixture 應被評測：{result.output}"
        assert '"skill": "hidden"' in result.output

    def test_seval_cli_010_all_covers_skills_and_plugins(self, tmp_path: Path) -> None:
        """SEVAL-CLI-010: eval --all 同時涵蓋 skills/ 與 sibling plugins/ 的 fixture。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        skills_dir = tmp_path / "skills"
        write_fixture(skills_dir, skill="covered")
        write_plugin_fixture(tmp_path / "plugins", "pack", "skills", "hidden", skill="hidden")

        result = CliRunner().invoke(
            cli, ["eval", "--all", "--skills-dir", str(skills_dir), "--emit-manifest"]
        )
        assert result.exit_code == 0
        assert '"skill": "covered"' in result.output
        assert '"skill": "hidden"' in result.output

    def test_seval_cli_018_all_fails_when_nothing_found(self, tmp_path: Path) -> None:
        """SEVAL-CLI-018: skills/ 與 plugins/ 皆無 fixture -> [FAIL]，不是 vacuous [OK]。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        result = CliRunner().invoke(
            cli, ["eval", "--all", "--skills-dir", str(skills_dir), "--emit-manifest"]
        )
        assert result.exit_code == 1
        assert "[FAIL]" in result.output
        assert "plugins/" in result.output, "訊息須說明已掃過的兩個位置"

    def test_seval_cli_017_default_layout_indexes_both_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEVAL-CLI-017: 不給 --skills-dir 時走預設佈局分支（SKILLS_DIR / PLUGINS_DIR）。

        其餘測試皆顯式傳 --skills-dir，故 `skills_dir is None` 這條——正是 production
        `--all` 實際走的路徑——從未被執行過。
        spec: skill-trigger-eval#plugin-fixtures-are-evaluated"""
        from tasks.skill_eval import config as config_mod

        skills_dir = tmp_path / "skills"
        write_fixture(skills_dir, skill="covered")
        write_plugin_fixture(tmp_path / "plugins", "pack", "skills", "hidden", skill="hidden")

        # patch config 的模組級常數：解析於函式內才 import config，patch cli 的屬性不會生效。
        monkeypatch.setattr(config_mod, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(config_mod, "PLUGINS_DIR", tmp_path / "plugins")

        result = CliRunner().invoke(cli, ["eval", "--all", "--emit-manifest"])
        assert result.exit_code == 0
        assert '"skill": "covered"' in result.output
        assert '"skill": "hidden"' in result.output

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
        spec: skill-trigger-eval#tolerance-out-of-domain-rejected"""
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
        spec: skill-trigger-eval#tolerance-out-of-domain-rejected"""
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
        spec: skill-trigger-eval#corrupt-baseline-rejected"""
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
        spec: skill-trigger-eval#corrupt-baseline-rejected"""
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

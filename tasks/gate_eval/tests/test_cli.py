"""gate_eval CLI 行為測試（CliRunner）：三命令的退出碼與 fail-loud 邊界。"""

import json
from pathlib import Path

from click.testing import CliRunner

from tasks._paths import PROJECT_ROOT
from tasks.gate_eval.cli import cli
from tasks.gate_eval.config import load_fixtures
from tasks.gate_eval.models import Disposition

SKILL = PROJECT_ROOT / "plugins" / "pr-flow" / "skills" / "pr-cycle-deep" / "SKILL.md"


def _all_fixture_ids_expected() -> dict[str, Disposition]:
    return {fx.id: fx.expected_disposition for fx in load_fixtures().fixtures}


def _wrong(disp: Disposition) -> Disposition:
    return Disposition.DEFERRED if disp == Disposition.BLOCKING else Disposition.BLOCKING


def _write(path: Path, obj: object) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


class TestEvalCommand:
    def test_geval_st_021_all_conformant_exits_zero(self, tmp_path: Path) -> None:
        """GEVAL-ST-021: 全部 CONFORMANT -> exit 0 + [OK]，且守恆印 [SKIP]。"""
        recorded = {fid: [d.value] * 5 for fid, d in _all_fixture_ids_expected().items()}
        f = _write(tmp_path / "d.json", recorded)
        res = CliRunner().invoke(cli, ["eval", "--dispositions", str(f)])
        assert res.exit_code == 0, res.output
        assert "[OK] 全部 CONFORMANT" in res.output
        assert "[SKIP]" in res.output

    def test_geval_st_022_all_nonconformant_exits_one(self, tmp_path: Path) -> None:
        """GEVAL-ST-022: 全部 NONCONFORMANT -> exit 1（gate 不可被反轉）。"""
        recorded = {fid: [_wrong(d).value] * 5 for fid, d in _all_fixture_ids_expected().items()}
        f = _write(tmp_path / "d.json", recorded)
        res = CliRunner().invoke(cli, ["eval", "--dispositions", str(f)])
        assert res.exit_code == 1
        assert "非 CONFORMANT" in res.output

    def test_geval_st_023_invalid_disposition_fails_loud_named(self, tmp_path: Path) -> None:
        """GEVAL-ST-023: 無效 disposition 字串 -> [FAIL] 指名 fixture，非 raw traceback。"""
        recorded = {fid: [d.value] * 5 for fid, d in _all_fixture_ids_expected().items()}
        first = next(iter(recorded))
        recorded[first] = ["blockng"] * 5  # typo
        f = _write(tmp_path / "d.json", recorded)
        res = CliRunner().invoke(cli, ["eval", "--dispositions", str(f)])
        assert res.exit_code == 1
        assert "[FAIL]" in res.output and first in res.output
        assert "Traceback" not in res.output

    def test_geval_st_024_non_dict_recorded_fails_loud(self, tmp_path: Path) -> None:
        """GEVAL-ST-024: dispositions 頂層為陣列 -> [FAIL]，非 AttributeError。"""
        f = _write(tmp_path / "d.json", [])
        res = CliRunner().invoke(cli, ["eval", "--dispositions", str(f)])
        assert res.exit_code == 1
        assert "JSON 物件" in res.output
        assert "Traceback" not in res.output

    def test_geval_st_025_short_sample_fails_loud(self, tmp_path: Path) -> None:
        """GEVAL-ST-025: 某 fixture 判定數 < INITIAL_N -> [FAIL] 指名。"""
        recorded = {fid: [d.value] * 5 for fid, d in _all_fixture_ids_expected().items()}
        first = next(iter(recorded))
        recorded[first] = [_all_fixture_ids_expected()[first].value] * 3  # 只有 3 筆
        f = _write(tmp_path / "d.json", recorded)
        res = CliRunner().invoke(cli, ["eval", "--dispositions", str(f)])
        assert res.exit_code == 1
        assert first in res.output and "至少" in res.output

    def test_geval_st_026_unstable_first_round_reruns_at_15(self, tmp_path: Path) -> None:
        """GEVAL-ST-026: 首輪 3:2（UNSTABLE）+ 提供 15 筆 -> CLI 走 rerun，報告標 reran@15。"""
        expected = _all_fixture_ids_expected()
        recorded = {fid: [d.value] * 5 for fid, d in expected.items()}
        target = next(iter(expected))
        exp = expected[target].value
        wrong = _wrong(expected[target]).value
        # 首輪 3 exp + 2 wrong = UNSTABLE；15 筆 = 13 exp + 2 wrong -> 達門檻 12 -> CONFORMANT
        recorded[target] = [exp, exp, exp, wrong, wrong] + [exp] * 10
        f = _write(tmp_path / "d.json", recorded)
        res = CliRunner().invoke(cli, ["eval", "--dispositions", str(f)])
        assert res.exit_code == 0, res.output
        assert "reran@15" in res.output


class TestMutationVerifyCommand:
    def test_geval_st_027_all_anchors_present_exits_zero(self) -> None:
        """GEVAL-ST-027: 真實 SKILL.md 下 12 個 anchor 皆在場 -> exit 0。"""
        res = CliRunner().invoke(cli, ["mutation-verify"])
        assert res.exit_code == 0, res.output
        assert "皆在場" in res.output

    def test_geval_st_028_absent_anchor_fails_loud(self, tmp_path: Path) -> None:
        """GEVAL-ST-028: anchor 不在目標 SKILL.md -> [FAIL] + exit 1。"""
        empty_skill = tmp_path / "SKILL.md"
        empty_skill.write_text("no matrix rows here", encoding="utf-8")
        res = CliRunner().invoke(cli, ["mutation-verify", "--skill", str(empty_skill)])
        assert res.exit_code == 1
        assert "[FAIL]" in res.output


class TestSunsetReportCommand:
    def test_geval_st_029_valid_window_reports(self, tmp_path: Path) -> None:
        """GEVAL-ST-029: 合法窗口狀態 -> 印 prune 建議與 sunset 求值。"""
        data = {
            "fixtures": [{"fixture_id": "fx", "mutation_kills": True, "alerts": ["true"]}],
            "windows": [{"true_alerts": 2, "false_alarms": 1, "any_fixture_alerted": True}],
            "superseded_by_code": False,
        }
        f = _write(tmp_path / "w.json", data)
        res = CliRunner().invoke(cli, ["sunset-report", "--window", str(f)])
        assert res.exit_code == 0, res.output
        assert "prune 建議" in res.output and "sunset 求值" in res.output

    def test_geval_st_030_non_dict_window_fails_loud(self, tmp_path: Path) -> None:
        """GEVAL-ST-030: 頂層為陣列 -> [FAIL]，非 AttributeError。"""
        f = _write(tmp_path / "w.json", [])
        res = CliRunner().invoke(cli, ["sunset-report", "--window", str(f)])
        assert res.exit_code == 1
        assert "JSON 物件" in res.output
        assert "Traceback" not in res.output

    def test_geval_st_031_bad_schema_window_fails_loud(self, tmp_path: Path) -> None:
        """GEVAL-ST-031: fixtures 筆缺必填欄位 -> [FAIL]（ValidationError 轉命名錯誤）。"""
        data = {"fixtures": [{"fixture_id": "fx"}]}  # 缺 mutation_kills
        f = _write(tmp_path / "w.json", data)
        res = CliRunner().invoke(cli, ["sunset-report", "--window", str(f)])
        assert res.exit_code == 1
        assert "格式錯誤" in res.output
        assert "Traceback" not in res.output

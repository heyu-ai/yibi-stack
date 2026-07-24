"""gate_eval 資料模型與 fixture/oracle 載入的驗證測試。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tasks.gate_eval.config import (
    check_fixture_oracle_consistency,
    load_fixtures,
    load_oracle,
)
from tasks.gate_eval.models import (
    ConformanceFixture,
    ContractMapping,
    Disposition,
    DispositionOracle,
    EvidenceForm,
    Factors,
    FixtureSet,
    MutationDescriptor,
    OracleEntry,
    Round,
    RunOutcome,
    Severity,
)


def make_factors(**kwargs: object) -> Factors:
    defaults = {
        "severity": Severity.CRITICAL,
        "evidence": EvidenceForm.VALID,
        "round": Round.R1,
        "contract_mapping": ContractMapping.VALID,
    }
    return Factors(**{**defaults, **kwargs})


def make_fixture(**kwargs: object) -> ConformanceFixture:
    defaults = {
        "id": "fx1",
        "finding_text": "合成 finding",
        "factors": make_factors(),
        "expected_disposition": Disposition.BLOCKING,
        "mutation": MutationDescriptor(anchors=["| Critical | valid | blocking | blocking |"]),
    }
    return ConformanceFixture(**{**defaults, **kwargs})


def write_fixture(path: Path, **kwargs: object) -> None:
    fx = make_fixture(**kwargs)
    path.write_text(fx.model_dump_json(indent=2), encoding="utf-8")


class TestMutationDescriptor:
    def test_geval_vl_001_single_anchor_accepted(self) -> None:
        """GEVAL-VL-001: 恰好一個 anchor 通過。"""
        m = MutationDescriptor(anchors=["row"])
        assert m.anchor == "row"

    def test_geval_vl_002_compound_anchor_rejected(self) -> None:
        """GEVAL-VL-002: 兩個 anchor 的複合 mutation 被拒。"""
        with pytest.raises(ValidationError, match="恰好綁定一個 anchor"):
            MutationDescriptor(anchors=["a", "b"])

    def test_geval_vl_003_empty_anchor_rejected(self) -> None:
        """GEVAL-VL-003: 空白 anchor 被拒。"""
        with pytest.raises(ValidationError, match="不可為空"):
            MutationDescriptor(anchors=["   "])


class TestConformanceFixture:
    def test_geval_vl_004_missing_finding_text_rejected(self) -> None:
        """GEVAL-VL-004: finding_text 空白被拒。"""
        with pytest.raises(ValidationError, match="finding_text 不可為空"):
            make_fixture(finding_text="  ")

    def test_geval_vl_005_bad_disposition_value_rejected(self) -> None:
        """GEVAL-VL-005: 期望 disposition 不在封閉列舉內被拒。"""
        with pytest.raises(ValidationError):
            make_fixture(expected_disposition="maybe")


class TestOracle:
    def test_geval_vl_006_disputed_requires_note(self) -> None:
        """GEVAL-VL-006: disputed 的 oracle 條目缺 note 被拒。"""
        with pytest.raises(ValidationError, match="disputed"):
            OracleEntry(
                severity=Severity.CRITICAL,
                evidence=EvidenceForm.NONE,
                round=Round.R1,
                contract_mapping=ContractMapping.MISSING,
                disposition="disputed",
            )

    def test_geval_vl_007_duplicate_factor_cell_rejected(self) -> None:
        """GEVAL-VL-007: 同因子組合出現兩次（轉錄錯誤）被拒。"""
        entry = OracleEntry(
            severity=Severity.CRITICAL,
            evidence=EvidenceForm.VALID,
            round=Round.R1,
            contract_mapping=ContractMapping.VALID,
            disposition=Disposition.BLOCKING,
        )
        with pytest.raises(ValidationError, match="重複的因子組合"):
            DispositionOracle(entries=[entry, entry])


class TestFixtureSet:
    def test_geval_vl_008_empty_set_rejected(self) -> None:
        """GEVAL-VL-008: 空 fixture 集合被拒（不得回報全數通過）。"""
        with pytest.raises(ValidationError, match="不可為空"):
            FixtureSet(fixtures=[])

    def test_geval_vl_009_all_deferred_set_rejected(self) -> None:
        """GEVAL-VL-009: 缺 blocking 的退化集合被拒。"""
        fx = make_fixture(
            expected_disposition=Disposition.NON_BLOCKING,
            factors=make_factors(severity=Severity.NIT),
        )
        with pytest.raises(ValidationError, match="blocking"):
            FixtureSet(fixtures=[fx])

    def test_geval_vl_010_missing_nonblocking_rejected(self) -> None:
        """GEVAL-VL-010: 缺 non-blocking 的集合被拒。"""
        fx = make_fixture(expected_disposition=Disposition.BLOCKING)
        with pytest.raises(ValidationError, match="non-blocking"):
            FixtureSet(fixtures=[fx])

    def test_geval_vl_011_duplicate_id_rejected(self) -> None:
        """GEVAL-VL-011: 重複 id 被拒。"""
        a = make_fixture(id="dup", expected_disposition=Disposition.BLOCKING)
        b = make_fixture(
            id="dup",
            expected_disposition=Disposition.NON_BLOCKING,
            factors=make_factors(severity=Severity.NIT),
        )
        with pytest.raises(ValidationError, match="id 重複"):
            FixtureSet(fixtures=[a, b])


class TestRunOutcome:
    def test_geval_vl_012_failure_needs_error(self) -> None:
        """GEVAL-VL-012: 執行失敗（disposition None）必須帶 error。"""
        with pytest.raises(ValidationError, match="error"):
            RunOutcome(disposition=None, error="")

    def test_geval_vl_013_success_has_no_error(self) -> None:
        """GEVAL-VL-013: 成功的 outcome 帶 error 被拒。"""
        with pytest.raises(ValidationError, match="不應同時帶 error"):
            RunOutcome(disposition=Disposition.BLOCKING, error="x")


class TestLoaders:
    def test_geval_eg_001_load_fixture_bad_json(self, tmp_path: Path) -> None:
        """GEVAL-EG-001: 壞掉的 fixture 檔以 RuntimeError 中止並指名路徑。"""
        (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="讀取 fixture 失敗"):
            from tasks.gate_eval.config import load_fixture_file

            load_fixture_file(tmp_path / "bad.json")

    def test_geval_eg_002_empty_findings_dir_fails_loud(self, tmp_path: Path) -> None:
        """GEVAL-EG-002: 空 fixture 目錄 fail loud，不回報全數通過。"""
        with pytest.raises(RuntimeError):
            load_fixtures(tmp_path)

    def test_geval_st_001_real_fixtures_consistent_with_oracle(self) -> None:
        """GEVAL-ST-001: repo 內建 12 個 fixture 與 oracle 一致（每格皆有對應）。"""
        oracle = load_oracle()
        fixtures = load_fixtures()
        check_fixture_oracle_consistency(fixtures, oracle)
        assert len(fixtures.fixtures) == 12
        assert len(oracle.entries) == 12

    def test_geval_st_002_every_oracle_entry_referenced(self) -> None:
        """GEVAL-ST-002: 每個 oracle 條目至少被一個 fixture 引用（無孤兒格）。"""
        oracle = load_oracle()
        fixtures = load_fixtures()
        used = {fx.factors.key() for fx in fixtures.fixtures}
        for entry in oracle.entries:
            assert entry.factors().key() in used, (
                f"oracle 格未被任何 fixture 引用：{entry.factors().key()}"
            )


class TestControlOne:
    """驗收對照組一：刻意標錯期望 disposition 的 fixture 須被指名（deterministic）。"""

    def test_geval_dt_001_mislabeled_fixture_named(self, tmp_path: Path) -> None:
        """GEVAL-DT-001: 期望 disposition 與 oracle 不符的 fixture 被 check 指名。"""
        findings = tmp_path / "findings"
        findings.mkdir()
        # 一個正確、一個刻意標錯（crit/valid/r1 應為 blocking，卻標 deferred）
        write_fixture(findings / "ok.json", id="ok", expected_disposition=Disposition.BLOCKING)
        write_fixture(
            findings / "bad.json",
            id="mislabeled",
            expected_disposition=Disposition.DEFERRED,
        )
        # 補一個 non-blocking 讓集合通過 balance
        write_fixture(
            findings / "nb.json",
            id="nb",
            expected_disposition=Disposition.NON_BLOCKING,
            factors=make_factors(severity=Severity.NIT),
        )
        oracle = load_oracle()
        fixtures = load_fixtures(findings)
        with pytest.raises(RuntimeError, match="mislabeled"):
            check_fixture_oracle_consistency(fixtures, oracle)

    def test_geval_dt_002_absent_factor_combo_halts(self, tmp_path: Path) -> None:
        """GEVAL-DT-002: 因子組合不在 oracle（此處 out_of_scope）時中止並指名。"""
        findings = tmp_path / "findings"
        findings.mkdir()
        write_fixture(
            findings / "oos.json",
            id="oos",
            expected_disposition=Disposition.OUTSIDE_CONTRACT,
            factors=make_factors(contract_mapping=ContractMapping.OUT_OF_SCOPE),
        )
        # blocking + non-blocking 讓集合通過 balance，才到得了 consistency 檢查
        write_fixture(findings / "b.json", id="b", expected_disposition=Disposition.BLOCKING)
        write_fixture(
            findings / "nb.json",
            id="nb",
            expected_disposition=Disposition.NON_BLOCKING,
            factors=make_factors(severity=Severity.NIT),
        )
        oracle = load_oracle()
        fixtures = load_fixtures(findings)
        with pytest.raises(RuntimeError, match="oos"):
            check_fixture_oracle_consistency(fixtures, oracle)

"""LPM CLI 測試：版本旗標、init 冪等性、get 的 exit code 契約。

版本旗標的測試意圖：ADR-0004 把「版本落差」列為 plugin-primary 交付的首要風險。
但 mob review（PR #249）推翻了「用 semver 比較當閘門」的做法——`uv tool install git+`
裝的是 HEAD，metadata 版本卻是「上次 release」的值，兩次 release 之間的所有 commit 都
回報同一個版本，比較不帶資訊。故 `--version` 的定位是**診斷用**，不是閘門；這裡只保證
它如實回報 metadata，不假裝它能擋版本落差。
"""

from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from tasks.local_port_manager.cli import cli
from tasks.local_port_manager.models import Category, PortEntry, PortRegistry

CLI_SVC = "tasks.local_port_manager.service"


def _invoke_version_with_patched_metadata(**patch_kwargs: Any) -> tuple[int, str]:
    """在 patch 過 importlib.metadata.version 的情況下呼叫 --version，回傳 (exit_code, output)。

    **為何需要 importlib.reload**：click 的 version_option callback 用 `nonlocal version`
    把查到的版本**快取進 closure**（見 click/decorators.py 的 `if version is None and
    package_name is not None:`）。decorator 在 import 時只套用一次，所以整個 process 中
    第一次呼叫 --version 之後版本就被鎖死，之後再 patch metadata 一律無效。

    實測後果：不 reload 的話，本測試單獨跑會過、接在 LPM-VL-001 之後跑會失敗——
    order-dependent 的 flaky test，比沒有測試更糟。reload 會重建 closure（version=None），
    讓 patch 真正生效。finally 的 reload 把模組還原，避免汙染其他測試。

    不要「簡化」掉 reload。
    """
    import importlib

    import tasks.local_port_manager.cli as cli_mod

    try:
        with patch("importlib.metadata.version", **patch_kwargs):
            importlib.reload(cli_mod)
            result = CliRunner().invoke(cli_mod.cli, ["--version"])
        return result.exit_code, result.output
    finally:
        importlib.reload(cli_mod)


def _version_output_under_patched_metadata(sentinel: str) -> str:
    """回傳 --version 輸出中的版本字串（metadata 被 patch 成 sentinel 時）。"""
    exit_code, output = _invoke_version_with_patched_metadata(return_value=sentinel)
    assert exit_code == 0, f"--version 應成功退出，實得 {exit_code}：{output}"
    # 輸出格式為 "<prog>, version <ver>"；只取版本部分做精確比對，避免 substring 誤判
    return output.strip().rsplit(" ", 1)[-1]


def _version_exit_code_under_broken_metadata() -> int:
    """回傳 metadata 拋 PackageNotFoundError 時 --version 的 exit code。"""
    exit_code, _ = _invoke_version_with_patched_metadata(
        side_effect=PackageNotFoundError("yibi-stack")
    )
    return exit_code


def _seed_registry(path: Path, entries: list[PortEntry] | None = None) -> None:
    """在 path 寫入一份 registry（供 get / init 冪等測試用）。"""
    from datetime import UTC, datetime

    registry = PortRegistry(
        ranges={"db": [5400, 5499]},
        entries=entries
        if entries is not None
        else [
            PortEntry(
                project="proj",
                service="postgres",
                category=Category.DB,
                port=5433,
                registered_at=datetime.now(tz=UTC),
            )
        ],
    )
    path.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")


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

        registry = PortRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        assert registry.entries == []

    def test_lpm_st_002_init_keeps_generic_ranges(self, tmp_path: Path) -> None:
        """LPM-ST-002: init 仍寫入通用 port range（那不是個人資料）。"""
        registry_path = tmp_path / "ports.json"
        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["init"])

        assert result.exit_code == 0
        registry = PortRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        assert registry.ranges["db"] == [5400, 5499]

    def test_lpm_st_003_init_is_idempotent_and_preserves_entries(self, tmp_path: Path) -> None:
        """LPM-ST-003: registry 已存在時 init 提早返回，不覆寫既有登記。

        這是每個回訪使用者都會走的分支。把守衛反轉成覆寫會靜默摧毀已填充的
        ~/.agents/ports.json（exit 0，無錯誤）。
        """
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["init"])

        assert result.exit_code == 0
        registry = PortRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        assert len(registry.entries) == 1
        assert registry.entries[0].project == "proj"


class TestVersionOption:
    def test_lpm_vl_001_version_flag_reports_package_version(self) -> None:
        """LPM-VL-001: --version 輸出與套件 metadata 一致的版本號。"""
        from importlib.metadata import version

        result = CliRunner().invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert version("yibi-stack") in result.output

    def test_lpm_vl_002_version_comes_from_metadata_not_a_literal(self) -> None:
        """LPM-VL-002: --version 的值來自 metadata 查找，而非寫死的字串。

        以 sentinel 驗證：patch metadata 回傳一個不可能被寫死的值，若 CLI 真的查
        metadata，該值必須出現在輸出。硬編碼的 version_option 會印出寫死的版本而失敗。

        為何不能只比對 `version("yibi-stack")`（LPM-VL-001 的做法）：那是 CLI 讀的
        同一份 live metadata，所以一個**剛好等於當前版本**的硬編碼字串能同時滿足
        兩者。PR #249 的 mob review 以 mutation 證實了這點——`version="1.9.0"` 之下
        原本的兩個測試全部 PASS。
        """
        assert _version_output_under_patched_metadata("9.9.9-sentinel") == "9.9.9-sentinel"

    def test_lpm_vl_003_version_fails_loudly_when_metadata_missing(self) -> None:
        """LPM-VL-003: metadata 查不到時 --version 非零退出，不靜默回報假版本。

        SKILL.md 的 preflight 依賴 `portman --version` 的 exit code 來判斷安裝是否
        健全（見 plugins/util/skills/local-port-manager/SKILL.md Step 1）。若 metadata
        損毀時它仍 exit 0，preflight 會拿一個壞掉的安裝繼續跑。
        """
        exit_code = _version_exit_code_under_broken_metadata()

        assert exit_code != 0


class TestGet:
    def test_lpm_dt_021_get_exits_1_with_no_stdout_when_absent(self, tmp_path: Path) -> None:
        """LPM-DT-021: 查無登記時 exit 1 且 stdout 全空。

        SKILL.md 廣告的整合方式是 `REDIS_PORT := $(shell portman get $(PROJECT) redis)`。
        Makefile 的 $(shell) 只看 stdout：若這裡退化成印訊息 + exit 0，使用者的 Makefile
        會靜默綁到一個空字串或一段人類可讀文字，而非大聲失敗。
        """
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["get", "proj", "nope"])

        assert result.exit_code == 1
        assert result.stdout == ""

    def test_lpm_dt_022_get_prints_bare_port_on_stdout(self, tmp_path: Path) -> None:
        """LPM-DT-022: 查到時 stdout 只有裸 port 數字（Makefile $(shell) 無法容忍裝飾）。"""
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["get", "proj", "postgres"])

        assert result.exit_code == 0
        assert result.stdout.strip() == "5433"


class TestReserve:
    def test_lpm_dt_030_reserve_registers_entry(self, tmp_path: Path) -> None:
        """LPM-DT-030: reserve 寫入登記（正向對照：沒有它，下方的錯誤路徑測試在
        「reserve 整個壞掉」時也會通過）。"""
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["reserve", "proj", "redis", "--port", "6380"])

        assert result.exit_code == 0
        registry = PortRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        assert any(e.service == "redis" and e.port == 6380 for e in registry.entries)

    def test_lpm_dt_031_reserve_conflict_fails_cleanly(self, tmp_path: Path) -> None:
        """LPM-DT-031: port 已被別的 (project, service) 佔用時，乾淨報錯 + exit 1。"""
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(
                cli, ["reserve", "other", "db", "--port", "5433", "-c", "db"]
            )

        assert result.exit_code == 1
        assert "✗" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_lpm_dt_032_reserve_with_unknown_range_name_fails_cleanly(self, tmp_path: Path) -> None:
        """LPM-DT-032: registry 的 ranges 含非 Category 名稱時，乾淨報錯而非噴 traceback。

        PortRegistry 只驗 ranges 的 [low, high] 形狀，不驗 key 是否為合法 Category，
        所以手動編輯過的 ~/.agents/ports.json 可以含任意 range 名。此時 _infer_category
        會對該名稱呼叫 Category(...)——若它落在 reserve_cmd 的 try/except 之外，使用者會
        看到 Python traceback 而非本 CLI 其他錯誤路徑一致的「✗ ...」+ exit 1。

        portman 現在是公開發佈的 CLI，traceback 是不可接受的使用者介面。
        """
        registry_path = tmp_path / "ports.json"
        registry = PortRegistry(
            ranges={"analytics": [9700, 9799]},  # 合法形狀，但不是 Category 成員
            entries=[],
        )
        registry_path.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["reserve", "proj", "metrics", "--port", "9700"])

        assert result.exit_code == 1
        assert "✗" in result.output, f"應輸出乾淨錯誤，實得：{result.output!r}"
        # 不得逸出未處理的例外（SystemExit 是 click 的正常退出路徑）
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"不該逸出 {type(result.exception).__name__}：{result.exception}"
        )


class TestReleaseAndCheck:
    def test_lpm_dt_040_release_removes_entry(self, tmp_path: Path) -> None:
        """LPM-DT-040: release 移除登記。"""
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["release", "proj", "postgres"])

        assert result.exit_code == 0
        registry = PortRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        assert registry.entries == []

    def test_lpm_dt_041_release_is_idempotent(self, tmp_path: Path) -> None:
        """LPM-DT-041: release 不存在的登記時冪等，不報錯。"""
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["release", "proj", "nope"])

        assert result.exit_code == 0

    def test_lpm_dt_042_check_reports_occupant(self, tmp_path: Path) -> None:
        """LPM-DT-042: check 回報佔用該 port 的專案。"""
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["check", "5433"])

        assert result.exit_code == 0
        assert "proj" in result.output

    def test_lpm_dt_043_list_shows_entries(self, tmp_path: Path) -> None:
        """LPM-DT-043: list 列出登記。"""
        registry_path = tmp_path / "ports.json"
        _seed_registry(registry_path)

        with patch(f"{CLI_SVC}.REGISTRY_PATH", registry_path):
            result = CliRunner().invoke(cli, ["list"])

        assert result.exit_code == 0
        assert "postgres" in result.output

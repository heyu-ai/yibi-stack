"""CLICAP-* tests for pr-cycle-fast/scripts/check-cli-capability.sh。

把 issue #333 的雙向對照固化成回歸鎖：探針必須對「缺 --repo-root 的 CLI」失敗、
對「具備 --repo-root 的 CLI」通過。只驗其中一邊沒有資訊量——一個永遠 PASS 的
guard 與不存在的 guard 無法區分。

另含一條防漂移測試：SKILL.md 實際帶 --repo-root 呼叫的子指令，必須被探針的
SUBCOMMANDS 清單涵蓋。本 issue 的病根正是「文件宣告的介面」與「檢查的介面」各走各的。
"""

import re
import subprocess  # nosec B404
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILL_DIR = _REPO_ROOT / "plugins" / "pr-flow" / "skills" / "pr-cycle-fast"
_SCRIPT = _SKILL_DIR / "scripts" / "check-cli-capability.sh"
_SKILL_MD = _SKILL_DIR / "SKILL.md"

# v1.11.0 實測結果：這 5 個子指令缺 --repo-root，detect / auto-fix 有。
_STALE_SUBCOMMANDS = {"resume", "status", "transition", "write-manifest", "log-view"}


def _write_stub(bin_dir: Path, body: str) -> None:
    """在 bin_dir 放一支假的 pr-orchestrator，body 是它的 shell 本體。"""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "pr-orchestrator"
    stub.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)


def _run(bin_dir: Path | None) -> subprocess.CompletedProcess[str]:
    """以 bin_dir 為唯一 PATH 前綴執行探針；bin_dir=None 代表 PATH 中沒有該工具。"""
    path = f"{bin_dir}:/usr/bin:/bin" if bin_dir else "/usr/bin:/bin"
    return subprocess.run(  # nosec B603
        ["/bin/bash", str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": path},
    )


def _script_subcommands() -> set[str]:
    text = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^SUBCOMMANDS=\(([^)]*)\)", text, re.MULTILINE)
    assert match is not None, "找不到 SUBCOMMANDS 宣告——探針結構已變，測試需同步更新"
    return set(match.group(1).split())


class TestCapabilityProbe:
    def test_clicap_dt_001_passes_when_flag_present(self, tmp_path: Path) -> None:
        """CLICAP-DT-001: 每個子指令的 --help 都含 --repo-root 時 exit 0（正向對照）"""
        _write_stub(tmp_path / "bin", 'echo "  --repo-root TEXT  repo 根目錄"')
        result = _run(tmp_path / "bin")
        assert result.returncode == 0, result.stderr
        assert "[OK]" in result.stdout

    def test_clicap_dt_002_fails_when_flag_absent(self, tmp_path: Path) -> None:
        """CLICAP-DT-002: 完全沒有 --repo-root 時 exit 2（負向對照）"""
        _write_stub(tmp_path / "bin", 'echo "  --pr INTEGER  [required]"')
        result = _run(tmp_path / "bin")
        assert result.returncode == 2
        assert "--repo-root" in result.stderr

    def test_clicap_dt_003_fails_on_v1_11_0_shape(self, tmp_path: Path) -> None:
        """CLICAP-DT-003: 重現 v1.11.0 的實際形狀（detect/auto-fix 有、其餘 5 個沒有）→ exit 2

        這是本測試最重要的一條：部分子指令具備該 flag 時，探針不得因為「抽到有的那個」
        而放行。只探一個子指令的實作會在這裡通過而在真實環境失敗。
        """
        _write_stub(
            tmp_path / "bin",
            'case "$1" in\n'
            '  detect|auto-fix) echo "  --repo-root TEXT  repo 根目錄" ;;\n'
            '  *) echo "  --pr INTEGER  [required]" ;;\n'
            "esac",
        )
        result = _run(tmp_path / "bin")
        assert result.returncode == 2
        for sub in _STALE_SUBCOMMANDS:
            assert sub in result.stderr, f"stderr 未點名缺少 flag 的子指令 {sub}"
        assert "detect" not in result.stderr.split("子指令：")[1].split("\n")[0]

    def test_clicap_dt_004_exit_1_when_binary_missing(self) -> None:
        """CLICAP-DT-004: PATH 中沒有 pr-orchestrator → exit 1（與 exit 2 區分）"""
        result = _run(None)
        assert result.returncode == 1
        assert "缺少 pr-orchestrator" in result.stderr

    def test_clicap_dt_005_help_failure_is_not_reported_as_stale(self, tmp_path: Path) -> None:
        """CLICAP-DT-005: --help 執行失敗時，訊息須指向「安裝損毀」而非「版本過舊」

        「跑不起來」與「跑得起來但缺 flag」是兩種病，導向不同修法；混為一談會把使用者
        推去做無效的升級。
        """
        _write_stub(tmp_path / "bin", 'echo "boom" >&2\nexit 3')
        result = _run(tmp_path / "bin")
        assert result.returncode == 2
        assert "安裝可能損毀" in result.stderr
        assert "版本過舊" not in result.stderr


class TestNoDrift:
    def test_clicap_df_001_skill_md_subcommands_are_all_probed(self) -> None:
        """CLICAP-DF-001: SKILL.md 中每個帶 --repo-root 的子指令都在探針清單內

        新增一個帶 --repo-root 的呼叫卻忘了加進探針，會讓探針對該子指令的缺失無感——
        正是 issue #333 的失敗形狀在未來的重演。
        """
        text = _SKILL_MD.read_text(encoding="utf-8")
        used = set(re.findall(r"pr-orchestrator ([a-z-]+)[^\n]*--repo-root", text))
        assert used, "SKILL.md 未偵測到任何 --repo-root 呼叫——正則已失效，非真的沒有"
        missing = used - _script_subcommands()
        assert not missing, f"SKILL.md 用到但探針未涵蓋的子指令：{sorted(missing)}"

    def test_clicap_df_002_probe_list_has_no_dead_entries(self) -> None:
        """CLICAP-DF-002: 探針清單不得含 SKILL.md 已不再使用的子指令（避免探針空轉）"""
        text = _SKILL_MD.read_text(encoding="utf-8")
        used = set(re.findall(r"pr-orchestrator ([a-z-]+)", text))
        dead = _script_subcommands() - used
        assert not dead, f"探針清單中 SKILL.md 已不使用的子指令：{sorted(dead)}"


@pytest.mark.parametrize("stale_sub", sorted(_STALE_SUBCOMMANDS))
def test_clicap_dt_006_each_stale_subcommand_alone_trips_probe(
    tmp_path: Path, stale_sub: str
) -> None:
    """CLICAP-DT-006: 只有單一子指令缺 flag 時仍須 exit 2（逐一形狀的正向 fixture）"""
    _write_stub(
        tmp_path / "bin",
        f'if [ "$1" = "{stale_sub}" ]; then\n'
        '  echo "  --pr INTEGER  [required]"\n'
        "else\n"
        '  echo "  --repo-root TEXT  repo 根目錄"\n'
        "fi",
    )
    result = _run(tmp_path / "bin")
    assert result.returncode == 2
    assert stale_sub in result.stderr

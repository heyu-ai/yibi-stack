"""pre-push-ruff-format-guard.py 黑盒測試。

策略：在 tmp_path 建真實 git repo，用 subprocess 以該 repo 為 cwd 呼叫 hook，
      傳入 Claude Code PreToolUse JSON 格式，驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）

ruff 呼叫走 _RUFF_CMD_ENV seam 注入「PATH 上的真 ruff」直接掃 tmp repo——用真 ruff
而非 mock：mock 只驗證「程式有照我說的呼叫 ruff」，不驗證「我對 ruff 輸出格式的假設
是否成立」（沿用姊妹 hook 的測試哲學）。seam 只覆寫 ruff 指令**前綴**，hook 一律在其後
附上已追蹤 .py 清單。production 不設此 env，走專案 pinned 的 `uv run ruff`（版本與 CI 目前
一致，但兩處 pin 各自維護、無機械 lockstep）。
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "pre-push-ruff-format-guard.py"
RUFF = shutil.which("ruff")
_needs_ruff = pytest.mark.skipif(RUFF is None, reason="ruff 不在 PATH，無法用真 ruff 測行為")

_FORMATTED = "x = [1, 2, 3]\n"
_UNFORMATTED = "x=[1,2,3]\ndef f( a ,b ):\n     return a+b\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """帶一個已 commit、已格式化 .py 的乾淨 git repo。"""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "tracked.py").write_text(_FORMATTED)
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def run_hook(
    cwd: Path,
    command: object,
    tool_name: str = "Bash",
    payload_cwd: Path | None = None,
    ruff_override: str | None = "__real__",
) -> subprocess.CompletedProcess[str]:
    """以給定 cwd 與指令執行 hook。

    ruff_override:
      "__real__"（預設）→ 注入 PATH 上的真 ruff（需 RUFF 存在）
      None                → 不設 seam，讓 hook 走預設 `uv run ruff`
      其他字串            → 原樣當成 _RUFF_CMD_ENV 值（測 fail-open）
    """
    env = os.environ.copy()
    if ruff_override == "__real__":
        # 只給前綴（不含路徑）；hook 會在其後附上已追蹤 .py 清單。
        env["PRE_PUSH_RUFF_GUARD_CMD"] = f"{RUFF} format --check"
    elif ruff_override is None:
        env.pop("PRE_PUSH_RUFF_GUARD_CMD", None)
    else:
        env["PRE_PUSH_RUFF_GUARD_CMD"] = ruff_override
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"command": command},
            **({"cwd": str(payload_cwd)} if payload_cwd is not None else {}),
        }
    )
    return subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def run_hook_raw(cwd: Path, raw_payload: str) -> subprocess.CompletedProcess[str]:
    """以原始（可能格式錯誤）JSON 字串呼叫 hook，用來測外部資料邊界的 fail-open。"""
    return subprocess.run(
        ["python3", str(HOOK)],
        input=raw_payload,
        cwd=cwd,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )


# ── 核心行為：已 commit 但未格式化 → 擋 ──────────────────────────────────


@_needs_ruff
class TestFormatGuard:
    def test_pprf_dt_001_all_formatted_allows_push(self, repo: Path) -> None:
        """PPRF-DT-001: 全部已格式化 → 放行"""
        assert run_hook(repo, "git push origin feature").returncode == 0

    def test_pprf_dt_002_unformatted_blocks_push(self, repo: Path) -> None:
        """PPRF-DT-002: 有已 commit 的未格式化 .py → 攔截並列出檔名"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        result = run_hook(repo, "git push origin feature")
        assert result.returncode == 2
        assert "bad.py" in result.stdout
        assert "ruff format" in result.stdout

    def test_pprf_dt_003_git_c_path_push_blocks(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """PPRF-DT-003: git -C <path> push 形式也要認得"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        clean_cwd = tmp_path_factory.mktemp("clean-cwd")
        _git(clean_cwd, "init", "-q")
        result = run_hook(clean_cwd, f"git -C {repo} push origin feature")
        assert result.returncode == 2
        assert "bad.py" in result.stdout

    def test_pprf_dt_004_payload_cwd_is_authoritative(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """PPRF-DT-004: 以 payload cwd（而非 launch cwd）定位目標 repo"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        launch_cwd = tmp_path_factory.mktemp("launch-cwd")
        assert run_hook(launch_cwd, "git push", payload_cwd=repo).returncode == 2

    def test_pprf_dt_010_multiple_relative_c_accumulates(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """PPRF-DT-010: 多個相對 -C 依 Git 累積語意解析（_resolve_cwd 累積迴圈）。

        中繼點刻意用「不同的 repo」，累積解析才可觀察：base_cwd 設在 decoy repo，正確的兩段
        累積（`-C .. -C target`）會落在含 bad.py 的 target repo（→ block）；壞掉的「只取最後
        一段」會落在 decoy/target（不存在）→ 放行。若像先前那樣在同一 repo 內用 `../..`，
        `git rev-parse --show-toplevel` 會把任何子目錄正規化回同一 root，last-only mutation
        便無法被殺（pr-test-analyzer 於 re-review 抓到的 fake-test）。
        """

        def _init(path: Path, *files: tuple[str, str]) -> None:
            path.mkdir()
            _git(path, "init", "-q")
            _git(path, "config", "user.email", "test@example.com")
            _git(path, "config", "user.name", "test")
            for name, content in files:
                (path / name).write_text(content)
            _git(path, "add", *[name for name, _ in files])
            _git(path, "commit", "-q", "-m", "init")

        container = tmp_path_factory.mktemp("acc")
        target = container / "target"
        _init(target, ("tracked.py", _FORMATTED), ("bad.py", _UNFORMATTED))
        decoy = container / "decoy"
        _init(decoy, ("clean.py", _FORMATTED))
        result = run_hook(decoy, "git -C .. -C target push origin feature", payload_cwd=decoy)
        assert result.returncode == 2
        assert "bad.py" in result.stdout

    def test_pprf_dt_011_multiple_pushes_second_target_blocks(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """PPRF-DT-011: 指令串含多個 push，第一個目標乾淨/非 git、後面的目標仍要被檢查。

        涵蓋 _push_target_cwds 的 finditer 多筆 + main 迴圈「跳過乾淨/None 目標、在後面
        的目標 block」分支；mutation `for target in targets[:1]` 會讓此測試失敗。
        """
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        nongit = tmp_path_factory.mktemp(
            "nongit"
        )  # 第一個 push 目標：非 git 目錄（_repo_root -> None）
        result = run_hook(nongit, f"git push origin a && git -C {repo} push origin b")
        assert result.returncode == 2
        assert "bad.py" in result.stdout


# ── 指令匹配：只認真正執行的 git push ─────────────────────────────────


@_needs_ruff
class TestCommandMatching:
    def test_pprf_dt_005_non_push_command_allows(self, repo: Path) -> None:
        """PPRF-DT-005: 未格式化 + 非 push 指令 → 放行（本 hook 只管 push 時刻）"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "git commit -m wip").returncode == 0

    @pytest.mark.parametrize(
        "command",
        ['git commit -m "add push"', "git show push", "git branch push-x"],
    )
    def test_pprf_dt_006_push_text_after_non_push_subcommand_allows(
        self, repo: Path, command: str
    ) -> None:
        """PPRF-DT-006: 第一個 subcommand 不是 push 時，不可被後續 push 字樣誤攔"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, command).returncode == 0

    def test_pprf_dt_007_push_as_literal_text_allows(self, repo: Path) -> None:
        """PPRF-DT-007: 'git push' 只出現在字串內容中 → 放行"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "echo 'remember to git push later'").returncode == 0

    @pytest.mark.parametrize(
        "command",
        [
            "git --no-pager push",
            "git -p push",
            "git -c http.x=y push",
            "git --exec-path=/bin push",  # inline `=` 帶值全域選項（_GLOBAL_OPTIONS_WITH_VALUE separator 分支）
            "env X=y git push",
            "X=y git push",
            'FOO="a b" git push',  # 帶空白的引號 inline env（atomic-group regex 的引號值分支）
            "sudo git push",
            "(git push)",
        ],
    )
    def test_pprf_dt_008_global_options_and_wrappers_block(self, repo: Path, command: str) -> None:
        """PPRF-DT-008: 全域選項 / wrapper 形狀的 push 仍要認得（且列出檔名，非只驗 exit code）"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        result = run_hook(repo, command)
        assert result.returncode == 2
        assert "bad.py" in result.stdout

    def test_pprf_dt_009_unrecognized_option_fails_open(self, repo: Path) -> None:
        """PPRF-DT-009: push 前出現非白名單 option → 保守放行（fail-open，非本 guard 目的）"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "git --mystery push").returncode == 0


# ── 邊界 / fail-open ───────────────────────────────────────────────────


class TestEdgeCases:
    @_needs_ruff
    def test_pprf_eg_001_non_bash_tool_allows(self, repo: Path) -> None:
        """PPRF-EG-001: 非 Bash 工具 → 放行"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        assert run_hook(repo, "git push", tool_name="Edit").returncode == 0

    def test_pprf_eg_002_non_git_dir_fails_open(self, tmp_path: Path) -> None:
        """PPRF-EG-002: 非 git 目錄 → fail-open 放行（hook 自己壞掉不該擋 push）"""
        assert run_hook(tmp_path, "git push origin feature").returncode == 0

    def test_pprf_eg_003_non_string_command_allows(self, repo: Path) -> None:
        """PPRF-EG-003: command 非字串 → 放行"""
        assert run_hook(repo, ["git", "push"]).returncode == 0

    def test_pprf_eg_004_ruff_unavailable_fails_open(self, repo: Path) -> None:
        """PPRF-EG-004: ruff 執行不出來（指向不存在的 binary）→ fail-open 放行"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        result = run_hook(
            repo, "git push", ruff_override="/definitely/nonexistent/ruff format --check"
        )
        assert result.returncode == 0

    @_needs_ruff
    def test_pprf_eg_005_untracked_unformatted_does_not_block(self, repo: Path) -> None:
        """PPRF-EG-005: 未追蹤（never git add）的未格式化 .py 不該擋 push。

        旗艦回歸：舊版掃 `.` 會把從沒進 push 的暫存檔判紅（mob review 3 家共識 Critical）。
        改掃 `git ls-files` 已追蹤檔後，未追蹤的 scratch.py 不在集合內 → 放行。
        """
        (repo / "scratch.py").write_text(_UNFORMATTED)  # 未 git add
        assert run_hook(repo, "git push origin feature").returncode == 0

    def test_pprf_eg_006_null_tool_input_fails_open(self, repo: Path) -> None:
        """PPRF-EG-006: payload 的 tool_input 為 null → fail-open 放行（rule 02 型別守門）。

        舊版 `data.get("tool_input", {}).get(...)` 在 tool_input=null 時擲 AttributeError，
        落在 try 外 → exit 1 → settings.json `|| exit 2` → 誤擋 push（與 fail-open 契約相反）。
        """
        payload = json.dumps({"tool_name": "Bash", "tool_input": None, "cwd": str(repo)})
        assert run_hook_raw(repo, payload).returncode == 0

    def test_pprf_eg_007_non_object_payload_fails_open(self, repo: Path) -> None:
        """PPRF-EG-007: 頂層非物件的 JSON（如 `[1,2]`）→ fail-open 放行。"""
        assert run_hook_raw(repo, "[1, 2]").returncode == 0

    def test_pprf_eg_008_ruff_rc1_without_parseable_lines_blocks(self, repo: Path) -> None:
        """PPRF-EG-008: ruff rc==1 但 stdout 解析不出檔名 → 仍一律 block（不因解析失敗 fail-open）。

        用 stub 強制 rc==1、無 `Would reformat:` 行，模擬未來 ruff 改輸出格式的情形。
        """
        result = run_hook(repo, "git push", ruff_override="python3 -c 'import sys; sys.exit(1)'")
        assert result.returncode == 2
        assert "ruff format" in result.stdout

    def test_pprf_eg_009_ruff_rc2_fails_open(self, repo: Path) -> None:
        """PPRF-EG-009: ruff rc==2（用法錯誤等，非 {0,1}）無法判定 → fail-open 放行。"""
        (repo / "bad.py").write_text(_UNFORMATTED)
        _git(repo, "add", "bad.py")
        _git(repo, "commit", "-q", "-m", "add unformatted")
        result = run_hook(repo, "git push", ruff_override="python3 -c 'import sys; sys.exit(2)'")
        assert result.returncode == 0

    def test_pprf_eg_010_ansi_escapes_stripped_from_file_list(self, repo: Path) -> None:
        """PPRF-EG-010: ruff 輸出帶 ANSI 色碼時，block 清單需去色（_ANSI_ESCAPE 生效）。

        用 stub 強制輸出含 ANSI 的 `Would reformat:` 行；若 `_ANSI_ESCAPE.sub` 被拿掉，
        清單會夾帶 `\\x1b[...m` 逃逸碼 → 此斷言會失敗。
        """
        stub = repo / "ansi_stub.py"
        stub.write_text(
            "import sys\nsys.stdout.write('Would reformat: \\x1b[1mx.py\\x1b[0m\\n')\nsys.exit(1)\n"
        )
        result = run_hook(repo, "git push", ruff_override=f"python3 {stub}")
        assert result.returncode == 2
        assert "x.py" in result.stdout
        assert "\x1b" not in result.stdout

    @_needs_ruff
    def test_pprf_eg_011_no_tracked_py_allows(self, tmp_path: Path) -> None:
        """PPRF-EG-011: repo 無任何已追蹤 .py（只有未追蹤未格式化 .py）→ 放行。

        涵蓋 `_unformatted_files` 的 `if not tracked: return []` 分支：若拿掉該防護，ruff 會
        以空清單退回掃 `.` → 抓到未追蹤 scratch.py → 誤擋；本測試斷言 exit 0。
        """
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "test")
        (tmp_path / "readme.txt").write_text("hi\n")
        _git(tmp_path, "add", "readme.txt")
        _git(tmp_path, "commit", "-q", "-m", "init")
        (tmp_path / "scratch.py").write_text(_UNFORMATTED)  # 未追蹤
        assert run_hook(tmp_path, "git push origin feature").returncode == 0


# ── ReDoS 回歸（比照姊妹 hook / CodeQL py/redos）───────────────────────


class TestReDoS:
    @pytest.mark.parametrize(
        "attack",
        [
            "&A=" + ("A=x " * 4000),  # ASCII 空白分隔的長重複 assignment
            "&A=" + ("\xa0A=" * 4000),  # CodeQL py/redos 的原始 witness（\xa0 = NBSP，屬 \s）
            "\n" * 8000 + " git status",  # 大量換行邊界（Codex R1 提出、已 withdraw 的 witness）
        ],
    )
    def test_pprf_re_001_git_command_regex_no_exponential_backtracking(self, attack: str) -> None:
        """PPRF-RE-001: _GIT_COMMAND 對長重複攻擊字串不得指數爆炸。

        assignment 重複段以 atomic group `(?>...)` 包住（Python 3.11+），一旦匹配不回溯，
        消除 `\\S+`/引號替換 × 外層 `*` 的指數 backtracking（CodeQL py/redos）。此測試以 timing
        上限守住不回退，並涵蓋 CodeQL 的原始 NBSP witness。
        """
        import importlib.util
        import time

        spec = importlib.util.spec_from_file_location("_rfg_redos", HOOK)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        start = time.perf_counter()
        list(mod._GIT_COMMAND.finditer(attack))
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"疑似 ReDoS 回退：{elapsed:.2f}s"

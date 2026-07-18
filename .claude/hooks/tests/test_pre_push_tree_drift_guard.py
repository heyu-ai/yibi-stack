"""pre-push-tree-drift-guard.py 黑盒測試。

策略：在 tmp_path 建真實 git repo，用 subprocess 以該 repo 為 cwd 呼叫 hook，
      傳入 Claude Code PreToolUse JSON 格式，驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）

用真 git repo 而非 mock：本 hook 的整個價值在於它對 git 狀態的判讀是否正確，
mock 只會驗證「程式有照我說的呼叫 git」，不驗證「我對 git 的假設是否成立」
（見 ~/.claude/CLAUDE.md 的 verify-mock-asserts-assumption-not-reality）。
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "pre-push-tree-drift-guard.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """帶一個已 commit 檔案的乾淨 git repo。"""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "tracked.py").write_text("x = 1\n")
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def run_hook(
    cwd: Path,
    command: object,
    tool_name: str = "Bash",
    env: dict[str, str] | None = None,
    payload_cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """以給定 cwd 與指令執行 hook，回傳完整結果。"""
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
        timeout=10,
    )


# ── 核心判斷：樹是否漂移 ───────────────────────────────────────────────


class TestTreeDrift:
    def test_pptd_dt_001_clean_tree_allows_push(self, repo: Path) -> None:
        """PPTD-DT-001: 工作區乾淨 -> 放行（正常流程：改 -> CI -> commit -> push）"""
        assert run_hook(repo, "git push origin feature").returncode == 0

    def test_pptd_dt_002_unstaged_tracked_blocks_push(self, repo: Path) -> None:
        """PPTD-DT-002: 已追蹤檔有未 stage 改動（formatter 就地改寫的形狀）-> 攔截"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "git push origin feature").returncode == 2

    def test_pptd_dt_003_staged_but_uncommitted_blocks_push(self, repo: Path) -> None:
        """PPTD-DT-003: 已 stage 但未 commit -> 攔截（push 出去的樹同樣不含它）"""
        (repo / "tracked.py").write_text("x = 3\n")
        _git(repo, "add", "tracked.py")
        assert run_hook(repo, "git push origin feature").returncode == 2

    def test_pptd_dt_004_untracked_only_allows_push(self, repo: Path) -> None:
        """PPTD-DT-004: 只有未追蹤檔 -> 放行。

        關鍵誤報守門：未追蹤檔不影響 push 出去的樹，納入會讓 yibi-stack 那種
        滿地 generated 檔的 repo 每次 push 都被擋。
        """
        (repo / "scratch.log").write_text("noise\n")
        assert run_hook(repo, "git push origin feature").returncode == 0


# ── 指令匹配：只認真正執行的 git push ─────────────────────────────────


class TestCommandMatching:
    def test_pptd_dt_005_non_push_command_allows(self, repo: Path) -> None:
        """PPTD-DT-005: 髒工作區 + 非 push 指令 -> 放行（本 hook 只管 push 時刻）"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "git commit -m wip").returncode == 0

    @pytest.mark.parametrize(
        "command",
        ['git commit -m "add push"', "git show push", "git branch push-x"],
    )
    @pytest.mark.parametrize("dirty", [False, True], ids=["clean", "dirty"])
    def test_pptd_dt_005b_push_text_after_non_push_subcommand_allows(
        self, repo: Path, command: str, dirty: bool
    ) -> None:
        """第一個 subcommand 不是 push 時，不可被後續 push 字樣誤攔。"""
        if dirty:
            (repo / "tracked.py").write_text("x = 5\n")

        assert run_hook(repo, command).returncode == 0

    def test_pptd_dt_006_push_as_literal_text_allows(self, repo: Path) -> None:
        """PPTD-DT-006: 'git push' 只出現在字串內容中 -> 放行（不是要執行它）"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "echo 'remember to git push later'").returncode == 0

    def test_pptd_dt_007_git_c_path_push_blocks(self, repo: Path) -> None:
        """PPTD-DT-007: git -C <path> push 形式也要認得 -> 攔截"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, f"git -C {repo} push origin feature").returncode == 2

    def test_pptd_dt_008_git_c_dirty_repo_from_clean_cwd_blocks(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """核心反例：process cwd 乾淨時，仍須檢查 -C 指定的髒 repo。"""
        clean_cwd = tmp_path_factory.mktemp("clean-cwd")
        _git(clean_cwd, "init", "-q")
        (repo / "tracked.py").write_text("x = 8\n")

        result = run_hook(clean_cwd, f"git -C {repo} push origin feature")

        assert result.returncode == 2
        assert "tracked.py" in result.stdout

    def test_pptd_dt_009_multiple_git_c_paths_are_cumulative(self, tmp_path: Path) -> None:
        """重複 -C 依 Git 語意逐段累積，而非只採最後一段。"""
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "target"
        target.mkdir()
        _git(target, "init", "-q")
        _git(target, "config", "user.email", "test@example.com")
        _git(target, "config", "user.name", "test")
        (target / "tracked.py").write_text("x = 1\n")
        _git(target, "add", "tracked.py")
        _git(target, "commit", "-q", "-m", "init")
        (target / "tracked.py").write_text("x = 9\n")

        result = run_hook(tmp_path, "git -C parent -C target push origin feature")

        assert result.returncode == 2
        assert "tracked.py" in result.stdout

    @pytest.mark.parametrize(
        "path_arg",
        ['"$TARGET_REPO"', "'$TARGET_REPO'", "`pwd`", "$(pwd)", "~/repo"],
    )
    def test_pptd_dt_010_unresolvable_git_c_path_blocks(
        self, tmp_path: Path, path_arg: str
    ) -> None:
        """含 shell 展開或引號的 -C 無法靜態確認時，一律 fail-closed。"""
        result = run_hook(tmp_path, f"git -C {path_arg} push origin feature")

        assert result.returncode == 2
        assert "無法確認" in result.stdout

    def test_pptd_dt_011_nonexistent_git_c_path_blocks(self, tmp_path: Path) -> None:
        result = run_hook(tmp_path, "git -C /definitely/nonexistent/yibi-258 push")

        assert result.returncode == 2
        assert "Git 檢查失敗" in result.stdout

    def test_pptd_dt_012_non_git_c_directory_allows(self, tmp_path: Path) -> None:
        non_repo = tmp_path / "ordinary-directory"
        non_repo.mkdir()

        assert run_hook(tmp_path, f"git -C {non_repo} push").returncode == 0

    def test_pptd_dt_013_inherited_git_environment_is_ignored(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """hook 繼承的 Git repo 定位變數不得凌駕 -C 目標。"""
        (repo / "tracked.py").write_text("x = 13\n")
        env = os.environ.copy()
        env.update(
            {
                "GIT_DIR": str(tmp_path / "missing.git"),
                "GIT_WORK_TREE": str(tmp_path),
                "GIT_COMMON_DIR": str(tmp_path / "missing-common.git"),
                "GIT_INDEX_FILE": str(tmp_path / "missing-index"),
            }
        )

        result = run_hook(tmp_path, f"git -C {repo} push", env=env)

        assert result.returncode == 2
        assert "tracked.py" in result.stdout

    @pytest.mark.parametrize(
        "command",
        [
            "git -c http.x=y push",
            "git -c k=v -C {repo} push",
            "git -C {repo} -c k=v push",
            "git --no-pager push",
            "git -p push",
            "env X=y git push",
            "X=y git push",
            "sudo git push",
            "(git push)",
        ],
    )
    def test_pptd_dt_014_global_options_and_wrappers_block_dirty_push(
        self, repo: Path, command: str
    ) -> None:
        (repo / "tracked.py").write_text("x = 14\n")

        result = run_hook(repo, command.format(repo=repo))

        assert result.returncode == 2
        assert "tracked.py" in result.stdout

    @pytest.mark.parametrize(
        "command",
        [
            "git -c http.x=y push",
            "git -c k=v -C {repo} push",
            "git -C {repo} -c k=v push",
            "git --no-pager push",
            "git -p push",
            "env X=y git push",
            'X="a b" git push',
            "sudo git push",
            "(git push)",
        ],
    )
    def test_pptd_dt_014b_global_options_and_wrappers_allow_clean_push(
        self, repo: Path, command: str
    ) -> None:
        assert run_hook(repo, command.format(repo=repo)).returncode == 0

    @pytest.mark.parametrize(
        "command, marker",
        [
            ("GIT_DIR={repo}/.git git push", "GIT_DIR"),
            ('GIT_WORK_TREE="{repo}/tree with space" git push', "GIT_WORK_TREE"),
            ("git -c core.worktree={repo} push", "core.worktree"),
            ("git -c core.gitDir={repo}/.git push", "core.gitdir"),
            ("git -c core.bare=true push", "core.bare"),
            ("git --config-env=core.worktree=TARGET push", "--config-env"),
        ],
    )
    def test_pptd_dt_014c_repository_selectors_fail_closed(
        self, repo: Path, command: str, marker: str
    ) -> None:
        result = run_hook(repo, command.format(repo=repo))

        assert result.returncode == 2
        assert marker in result.stdout

    def test_pptd_dt_015_unrecognized_git_option_fails_closed(self, repo: Path) -> None:
        result = run_hook(repo, "git --mystery-option push")

        assert result.returncode == 2
        assert "無法辨識" in result.stdout

    def test_pptd_dt_015b_repository_selector_fails_closed(self, repo: Path) -> None:
        result = run_hook(repo, "git --git-dir=/r/.git push")

        assert result.returncode == 2
        assert "--git-dir" in result.stdout

    def test_pptd_dt_016_compound_clean_then_dirty_blocks(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        clean = tmp_path_factory.mktemp("compound-clean")
        _git(clean, "init", "-q")
        (repo / "tracked.py").write_text("x = 16\n")

        command = f"git -C {clean} push; git -C {repo} push"
        assert run_hook(clean, command).returncode == 2

    def test_pptd_dt_017_payload_cwd_is_authoritative(
        self, repo: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        launch_cwd = tmp_path_factory.mktemp("hook-launch-cwd")
        (repo / "tracked.py").write_text("x = 17\n")

        assert run_hook(launch_cwd, "git push", payload_cwd=repo).returncode == 2

    def test_pptd_dt_018_symlink_then_parent_uses_stepwise_chdir(self, tmp_path: Path) -> None:
        real_parent = tmp_path / "real-parent"
        dirty_repo = real_parent / "dirty"
        dirty_repo.mkdir(parents=True)
        _git(dirty_repo, "init", "-q")
        _git(dirty_repo, "config", "user.email", "test@example.com")
        _git(dirty_repo, "config", "user.name", "test")
        (dirty_repo / "tracked.py").write_text("x = 1\n")
        _git(dirty_repo, "add", "tracked.py")
        _git(dirty_repo, "commit", "-q", "-m", "init")
        (dirty_repo / "tracked.py").write_text("x = 18\n")
        symlink = tmp_path / "link-to-dirty"
        symlink.symlink_to(dirty_repo, target_is_directory=True)

        result = run_hook(tmp_path, f"git -C {symlink} -C .. -C dirty push")

        assert result.returncode == 2
        assert "tracked.py" in result.stdout


# ── 邊界 ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_pptd_eg_001_non_bash_tool_allows(self, repo: Path) -> None:
        """PPTD-EG-001: 非 Bash 工具 -> 放行"""
        (repo / "tracked.py").write_text("x = 2\n")
        assert run_hook(repo, "git push origin feature", tool_name="Edit").returncode == 0

    def test_pptd_eg_002_non_git_dir_fails_open(self, tmp_path: Path) -> None:
        """PPTD-EG-002: 非 git 目錄 -> fail-open 放行（hook 自己壞掉不該擋 push）"""
        assert run_hook(tmp_path, "git push origin feature").returncode == 0

    def test_pptd_eg_003_non_string_command_allows(self, repo: Path) -> None:
        assert run_hook(repo, ["git", "push"]).returncode == 0


# ── ReDoS 回歸（CodeQL py/redos, PR #273）──────────────────────────────


class TestReDoS:
    def test_pptd_re_001_git_command_regex_no_exponential_backtracking(self) -> None:
        """PPTD-RE-001: _GIT_COMMAND 對 CodeQL 標記的攻擊字串不得指數爆炸。

        CodeQL py/redos：'&A=' 開頭 + 大量重複 '!\\xa0A=' 會在 assignment 重複段
        （`\\S+` 與引號替換 overlap × 外層 `*`）造成指數 backtracking。修法為 atomic
        group `(?>...)`（Python 3.11+）。以 timing 上限守住不回退：線性約數毫秒，
        指數則遠超 1s，門檻乾淨區分兩者。
        """
        import importlib.util
        import time

        spec = importlib.util.spec_from_file_location("_dg_redos", HOOK)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        attack = "&A=" + ("!\xa0A=" * 4000)
        start = time.perf_counter()
        list(mod._GIT_COMMAND.finditer(attack))
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"疑似 ReDoS 回退：{elapsed:.2f}s（atomic group 是否被移除？）"

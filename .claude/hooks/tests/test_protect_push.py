"""protect-push.sh 黑盒測試。

策略：用 subprocess 呼叫 hook，傳入 Claude Code PreToolUse JSON 格式，
      驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）
"""

import functools
import json
import os
import subprocess  # nosec B404
import tempfile
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "protect-push.sh"


def _hook_env() -> dict[str, str]:
    """`run_hook` 用的環境：跳過保護 4，避免這些測試打到真的 gh（issue #562）。

    保護 4 會用 `gh pr list --head <分支>` 查 PR 狀態，結果取決於執行當下所在分支在 GitHub 上的
    PR；分支的 PR 合併後，放行測試會被攔下而假紅。這些測試要驗的是保護 1～3，保護 4 的接線另由
    本檔「保護 4」一節（假 gh、刻意不設這個逃生口）與 test_protect_push_pr_state.py 覆蓋。
    每次呼叫都重新組環境，所以測試用 monkeypatch 改過的 PATH 也會被繼承。
    """
    return {**os.environ, "PROTECT_PUSH_SKIP_PR_STATE": "1"}


@functools.lru_cache(maxsize=1)
def _neutral_repo() -> Path:
    """`run_hook` 的 cwd：一個 branch 沒有 upstream 的拋棄式 repo。

    保護 3 會查「目前 branch」的 tracking。若直接在呼叫端的 checkout 跑，`git push -u origin HEAD`
    這類放行案例的結果就取決於執行者當下所在 branch 是否追蹤 origin/main（從 origin/main 建立的
    worktree branch 正是如此），測試會隨環境變紅。固定在中性 repo 跑，結果才可重現。
    """
    repo = Path(tempfile.mkdtemp(prefix="protect-push-neutral-")) / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    for args in (
        ["init", "-q", "-b", "feat-neutral"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "s"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, env=env)  # nosec B603 B607
    return repo


def run_hook(command: str) -> int:
    """以給定指令字串執行 hook，回傳 exit code。"""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    result = subprocess.run(
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=_hook_env(),
        cwd=str(_neutral_repo()),
        timeout=10,
    )
    return result.returncode


def run_hook_raw(stdin: str) -> int:
    """以原始字串（非 JSON）執行 hook，測試 fail-open 行為。"""
    # 非 JSON／空輸入在保護 4 之前就 fail-open（探針：假 gh 回 MERGED、不帶逃生口仍 exit 0），
    # 所以不需要 _hook_env()。
    result = subprocess.run(
        [str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode


# ── 放行行為（Allowed）────────────────────────────────────────────────


class TestAllowed:
    def test_pp_allow_001_normal_echo(self) -> None:
        """一般指令應放行"""
        assert run_hook("echo hello") == 0

    def test_pp_allow_002_invalid_json_fail_open(self) -> None:
        """無效 JSON → 靜默放行（fail-open 設計）"""
        assert run_hook_raw("not valid json") == 0

    def test_pp_allow_003_empty_stdin_fail_open(self) -> None:
        """空輸入 → 靜默放行"""
        assert run_hook_raw("") == 0

    def test_pp_allow_004_push_feature_branch(self) -> None:
        """推 feature branch → 放行"""
        assert run_hook("git push origin feature-branch") == 0

    def test_pp_allow_005_push_u_origin_head(self) -> None:
        """git push -u origin HEAD，目前 branch 沒有 upstream → 放行（追蹤 main 的情況見 PP-BLOCK-021）"""
        assert run_hook("git push -u origin HEAD") == 0

    def test_pp_allow_006_push_set_upstream(self) -> None:
        """git push --set-upstream origin my-branch → 放行"""
        assert run_hook("git push --set-upstream origin my-branch") == 0

    def test_pp_allow_007_commit_then_push_feature(self) -> None:
        """commit && push feature → 放行"""
        assert run_hook("git commit -m 'test' && git push origin feature-branch") == 0

    # ── Bug Fix：Protection 2 false positive ─────────────────────────

    def test_pp_allow_008_commit_msg_contains_push_main_text(self) -> None:
        """CRITICAL BUG FIX: commit message 含 'git push origin main' 文字不應被攔截。
        目前 Protection 2 對整個 CMD 字串做 regex，誤攔截 commit message。"""
        cmd = 'git commit -m "fix: prevent git push origin main in hook"'
        assert run_hook(cmd) == 0

    def test_pp_allow_009_echo_with_push_main_text(self) -> None:
        """echo 含保護關鍵字字串 → 放行"""
        assert run_hook('echo "git push origin main is blocked"') == 0

    def test_pp_allow_010_commit_then_push_feature_after_push_main_text(self) -> None:
        """commit message 含 push main 文字，再 push feature branch → 放行"""
        cmd = 'git commit -m "docs: do not push origin main" && git push origin docs/update'
        assert run_hook(cmd) == 0


# ── 攔截行為 Protection 1：gh pr merge ───────────────────────────────


class TestBlockGhPrMerge:
    def test_pp_block_001_direct_merge(self) -> None:
        """gh pr merge <num> → 攔截"""
        assert run_hook("gh pr merge 123") == 2

    def test_pp_block_002_merge_with_squash_flag(self) -> None:
        """gh pr merge --squash --auto → 攔截"""
        assert run_hook("gh pr merge 123 --squash --auto --delete-branch") == 2

    def test_pp_block_003_merge_in_subshell(self) -> None:
        """(gh pr merge 123) subshell 形式 → 攔截"""
        assert run_hook("(gh pr merge 123)") == 2

    def test_pp_block_004_merge_after_semicolon(self) -> None:
        """echo foo; gh pr merge 123 → 攔截"""
        assert run_hook("echo foo; gh pr merge 123") == 2

    def test_pp_block_005_merge_after_and_and(self) -> None:
        """git fetch && gh pr merge 123 → 攔截"""
        assert run_hook("git fetch && gh pr merge 123") == 2


# ── 攔截行為 Protection 2：git push origin main/master ───────────────


class TestBlockGitPushMain:
    def test_pp_block_010_push_origin_main(self) -> None:
        """git push origin main → 攔截"""
        assert run_hook("git push origin main") == 2

    def test_pp_block_011_push_origin_master(self) -> None:
        """git push origin master → 攔截"""
        assert run_hook("git push origin master") == 2

    def test_pp_block_012_push_force_origin_main(self) -> None:
        """git push --force origin main → 攔截"""
        assert run_hook("git push --force origin main") == 2

    def test_pp_block_013_push_force_with_lease_origin_main(self) -> None:
        """git push --force-with-lease origin main → 攔截"""
        assert run_hook("git push --force-with-lease origin main") == 2

    # ── Bug Fix：Protection 2 missing coverage ───────────────────────

    def test_pp_block_014_push_short_force_flag(self) -> None:
        """CRITICAL BUG FIX: git push -f origin main → 攔截（目前放行）"""
        assert run_hook("git push -f origin main") == 2

    def test_pp_block_015_push_head_colon_main(self) -> None:
        """CRITICAL BUG FIX: git push origin HEAD:main → 攔截（目前放行）"""
        assert run_hook("git push origin HEAD:main") == 2

    def test_pp_block_016_push_refs_heads_main(self) -> None:
        """CRITICAL BUG FIX: git push origin refs/heads/main → 攔截（目前放行）"""
        assert run_hook("git push origin refs/heads/main") == 2

    def test_pp_block_017_push_head_colon_master(self) -> None:
        """git push origin HEAD:master → 攔截（目前放行）"""
        assert run_hook("git push origin HEAD:master") == 2

    def test_pp_block_018_push_refs_heads_master(self) -> None:
        """git push origin refs/heads/master → 攔截（目前放行）"""
        assert run_hook("git push origin refs/heads/master") == 2


# ── 攔截訊息必須走 stderr ────────────────────────────────────────────
#
# Claude Code 2.1.296 探針：PreToolUse hook exit 2 時，stdout 的訊息不會送達 model（model 只看到
# `PreToolUse:Bash hook error: [...]: No stderr output`），stderr 的訊息才會原文送達。


class TestBlockMessageGoesToStderr:
    def _run(self, command: str) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        return subprocess.run(  # nosec B603
            [str(HOOK)], input=payload, capture_output=True, text=True, timeout=10
        )

    def test_pp_msg_001_gh_pr_merge_reason_on_stderr(self) -> None:
        res = self._run("gh pr merge 1 --squash")
        assert res.returncode == 2
        assert "BLOCKED" in res.stderr
        assert res.stdout == ""

    def test_pp_msg_002_push_main_reason_on_stderr(self) -> None:
        res = self._run("git push origin main")
        assert res.returncode == 2
        assert "BLOCKED" in res.stderr
        assert res.stdout == ""


# ── 保護 4：推到 PR 已 merged/closed 的分支 ──────────────────────────
#
# 這一層的判斷細節由 test_protect_push_pr_state.py 覆蓋；這裡只驗證「hook 有把 helper 接起來」，
# 尤其是 helper 的 exit 2 真的會變成 hook 的 exit 2 —— hook 開頭的 `trap 'exit 0' ERR` 會讓任何
# 未加保護的非零指令靜默變成放行，所以這個接線本身就是一個獨立的失效點。


def run_hook_with_env(
    command: str, cwd: Path, extra_path: Path | None
) -> subprocess.CompletedProcess[str]:
    """在指定 cwd 執行 hook，並可把假 gh 所在目錄放到 PATH 最前面。"""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = dict(os.environ)
    if extra_path is not None:
        env["PATH"] = f"{extra_path}{os.pathsep}{env['PATH']}"
    env.pop("PROTECT_PUSH_SKIP_PR_STATE", None)
    return subprocess.run(  # nosec B603
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=30,
    )


def _write_fake_gh(bin_dir: Path, payload: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/bash\nprintf '%s' '{payload}'\n", encoding="utf-8")
    gh.chmod(0o755)


def _throwaway_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    for args in (
        ["init", "-q", "-b", "feat-a"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, env=env)  # nosec B603 B607
    (repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env)  # nosec B603 B607
    subprocess.run(  # nosec B603 B607
        ["git", "commit", "-qm", "seed"], cwd=repo, check=True, env=env
    )
    return repo


class TestTrackingOriginMainBlock:
    def test_pp_msg_003_tracking_origin_main_reason_on_stderr(self, tmp_path: Path) -> None:
        """保護 3：branch 追蹤 origin/main 時裸 push -> exit 2，原因只在 stderr。

        branch 要有至少一個 commit（unborn branch 讓 `rev-parse --abbrev-ref HEAD` 失敗，hook 會
        提早 exit 0）；用 PROTECT_PUSH_SKIP_PR_STATE=1 跳過保護 4，避免這個測試打到真的 gh。
        """
        repo = _throwaway_repo(tmp_path)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
        for key, value in (
            ("branch.feat-a.remote", "origin"),
            ("branch.feat-a.merge", "refs/heads/main"),
        ):
            subprocess.run(  # nosec B603 B607
                ["git", "config", key, value], cwd=repo, check=True, env=env
            )
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}})
        res = subprocess.run(  # nosec B603
            [str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            env={**os.environ, "PROTECT_PUSH_SKIP_PR_STATE": "1"},
            cwd=str(repo),
            timeout=30,
        )
        assert res.returncode == 2
        assert "追蹤 origin/main" in res.stderr
        assert res.stdout == "", "訊息只能走 stderr：exit 2 時 stdout 不會送達 model"


def _set_upstream_main(repo: Path, branch: str) -> None:
    """把 branch 的 tracking 設成 origin/main（從 origin/main 建立 branch 的預設結果）。"""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    for key, value in (
        (f"branch.{branch}.remote", "origin"),
        (f"branch.{branch}.merge", "refs/heads/main"),
    ):
        subprocess.run(["git", "config", key, value], cwd=repo, check=True, env=env)  # nosec B603 B607


def run_hook_in(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """在指定 repo 執行 hook，跳過保護 4（不打真的 gh）。"""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(  # nosec B603
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=_hook_env(),
        cwd=str(cwd),
        timeout=30,
    )


class TestRefspecWithoutDestination:
    """保護 3：refspec 沒有 `:<dst>` 時，git 依該 branch 的 tracking 決定目的地。

    在 push.default=upstream 下（2026-11-17 以本機 bare remote 實測，git 2.56.1），追蹤
    origin/main 的 branch 執行 `git push origin <branch>` 或 `git push -u origin <branch>`
    都會更新遠端的 main；只有 `<branch>:<branch>` 才會建立同名 branch。舊版 hook 把沒有冒號的
    refspec 一律當成「明確指定 non-main 目的地」放行，正好漏掉這個情況。
    """

    @pytest.mark.parametrize(
        "command",
        [
            "git push origin feat-a",
            "git push -u origin feat-a",
            "git push --set-upstream origin feat-a",
            "git push -u origin HEAD",
            "git push origin refs/heads/feat-a",
            "git push origin feat-a:feat-a && git push origin feat-a",
            "git push origin +feat-a",
            "git push origin heads/feat-a",
            "git push origin @",
            "git push origin 'feat-a'",
            'git push origin "feat-a"',
            "git push origin feat\\-a",
            "git push origin 'unterminated",
        ],
    )
    def test_pp_block_021_tracking_main_without_dst(self, tmp_path: Path, command: str) -> None:
        """PP-BLOCK-021: branch 追蹤 origin/main + refspec 無 :dst → 攔截。"""
        repo = _throwaway_repo(tmp_path)
        _set_upstream_main(repo, "feat-a")
        res = run_hook_in(command, repo)
        assert res.returncode == 2, res.stderr
        assert "追蹤 origin/main" in res.stderr

    def test_pp_block_022_other_branch_tracking_main(self, tmp_path: Path) -> None:
        """PP-BLOCK-022: 推的是另一個 branch，而它追蹤 origin/main → 攔截（查 refspec 的 branch，不是 HEAD）。"""
        repo = _throwaway_repo(tmp_path)
        subprocess.run(["git", "branch", "feat-b"], cwd=repo, check=True)  # nosec B603 B607
        _set_upstream_main(repo, "feat-b")
        res = run_hook_in("git push origin feat-b", repo)
        assert res.returncode == 2, res.stderr

    @pytest.mark.parametrize(
        "command",
        [
            "git push origin $X feat-b",
            "git push origin 'v*' feat-b",
        ],
    )
    def test_pp_block_023_unsafe_refspec_does_not_hide_later_ones(
        self, tmp_path: Path, command: str
    ) -> None:
        """PP-BLOCK-023: 前面的 refspec 觸發 HEAD 檢查，也不能略過後面沒有 :dst 的 branch。

        目前 branch（feat-a）不追蹤 main，feat-b 追蹤 main：舊版遇到第一個可疑 refspec 就
        break，只查 HEAD 而放行。
        """
        repo = _throwaway_repo(tmp_path)
        subprocess.run(["git", "branch", "feat-b"], cwd=repo, check=True)  # nosec B603 B607
        _set_upstream_main(repo, "feat-b")
        res = run_hook_in(command, repo)
        assert res.returncode == 2, res.stderr

    @pytest.mark.parametrize(
        "command",
        [
            "git push -u origin feat-a:feat-a",
            "git push origin HEAD:feat-a",
            "git push origin other-branch",
        ],
    )
    def test_pp_allow_013_explicit_dst_or_untracked_branch(
        self, tmp_path: Path, command: str
    ) -> None:
        """PP-ALLOW-013: 明確的非 main 目的地，或被推的 branch 不追蹤 main → 放行。"""
        repo = _throwaway_repo(tmp_path)
        _set_upstream_main(repo, "feat-a")
        assert run_hook_in(command, repo).returncode == 0

    @pytest.mark.parametrize(
        "command", ["git push -u origin feat-a", "git push -u origin HEAD", "git push"]
    )
    def test_pp_allow_014_no_upstream(self, tmp_path: Path, command: str) -> None:
        """PP-ALLOW-014: 新 branch 還沒有 upstream → 推到同名 branch，放行（負向對照）。"""
        repo = _throwaway_repo(tmp_path)
        assert run_hook_in(command, repo).returncode == 0


class TestMergedPrPush:
    @pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
    def test_pp_block_019_explicit_refspec_to_finished_pr_branch(
        self, tmp_path: Path, state: str
    ) -> None:
        """PR 已 merged / closed 的分支 + explicit refspec → 攔截。

        explicit refspec 是保護 3 直接放行的形式（PR #449 事故用的就是它），所以這個案例證明
        保護 4 掛在早退之前，而不是被早退繞過。
        """
        _write_fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": state}]))
        res = run_hook_with_env(
            "git push origin feat-a:feat-a", _throwaway_repo(tmp_path), tmp_path / "bin"
        )
        assert res.returncode == 2
        assert f"#448 ({state})" in res.stderr
        assert res.stdout == "", "訊息只能走 stderr：exit 2 時 stdout 不會送達 model"

    def test_pp_block_020_bare_push_to_merged_pr_branch(self, tmp_path: Path) -> None:
        """PR 已 merged 的分支 + 裸 push → 攔截。"""
        _write_fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": "MERGED"}]))
        res = run_hook_with_env("git push", _throwaway_repo(tmp_path), tmp_path / "bin")
        assert res.returncode == 2
        assert "448" in res.stderr
        assert res.stdout == "", "訊息只能走 stderr：exit 2 時 stdout 不會送達 model"

    def test_pp_allow_011_open_pr_branch(self, tmp_path: Path) -> None:
        """PR 仍 open → 放行（負向對照：證明上面兩個攔截不是無條件擋 push）。"""
        _write_fake_gh(tmp_path / "bin", json.dumps([{"number": 500, "state": "OPEN"}]))
        res = run_hook_with_env(
            "git push origin feat-a:feat-a", _throwaway_repo(tmp_path), tmp_path / "bin"
        )
        assert res.returncode == 0

    def test_pp_allow_012_gh_missing_fails_open(self, tmp_path: Path) -> None:
        """PATH 上沒有 gh → 放行；離線不該讓所有 push 停擺。"""
        bin_dir = tmp_path / "emptybin"
        bin_dir.mkdir()
        repo = _throwaway_repo(tmp_path)
        payload = json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin feat-a:feat-a"}}
        )
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
        env.pop("PROTECT_PUSH_SKIP_PR_STATE", None)
        result = subprocess.run(  # nosec B603
            [str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo),
            timeout=30,
        )
        assert result.returncode == 0


class TestRunHookIsolatedFromRealGh:
    """issue #562：`run_hook` 系列不可依賴真的 gh。

    以前 `run_hook` 繼承呼叫端的完整環境，所以放行測試會打真的 GitHub，結果取決於執行當下所在分支
    的 PR 狀態：分支的 PR 合併後，在該分支上跑本機 `make ci` 會假紅。這裡用 PATH 注入一個「任何
    分支都回 MERGED」的假 gh；`run_hook` 若沒隔離就會被保護 4 攔下（exit 2）。
    """

    @pytest.mark.parametrize(
        "command",
        [
            "git push origin feature-branch",
            "git push -u origin HEAD",
            "git push --set-upstream origin my-branch",
            "git commit -m 'test' && git push origin feature-branch",
            'git commit -m "docs: do not push origin main" && git push origin docs/update',
        ],
    )
    def test_pp_iso_001_allowed_pushes_ignore_gh_reporting_merged_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        """PP-ISO-001: gh 回報 MERGED 時，run_hook 的放行測試仍放行（保護 4 已被跳過）。

        `git push -u origin HEAD` 的目標是「當前分支」，在 detached HEAD（例如 CI checkout）下
        本來就不會查 gh，所以它只在本機有分支時才有鑑別力；其餘四個指令的目標是字面分支名，
        在任何 checkout 都有鑑別力。
        """
        _write_fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": "MERGED"}]))
        monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.delenv("PROTECT_PUSH_SKIP_PR_STATE", raising=False)

        assert run_hook(command) == 0

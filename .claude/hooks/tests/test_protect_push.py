"""protect-push.sh 黑盒測試。

策略：用 subprocess 呼叫 hook，傳入 Claude Code PreToolUse JSON 格式，
      驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）
"""

import json
import os
import subprocess  # nosec B404
from pathlib import Path

HOOK = Path(__file__).parent.parent / "protect-push.sh"


def run_hook(command: str) -> int:
    """以給定指令字串執行 hook，回傳 exit code。"""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    result = subprocess.run(
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode


def run_hook_raw(stdin: str) -> int:
    """以原始字串（非 JSON）執行 hook，測試 fail-open 行為。"""
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
        """git push -u origin HEAD → 放行"""
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


# ── 保護 4：推到 PR 已 merged/closed 的分支 ──────────────────────────
#
# 這一層的判斷細節由 test_protect_push_pr_state.py 覆蓋；這裡只驗證「hook 有把 helper 接起來」，
# 尤其是 helper 的 exit 2 真的會變成 hook 的 exit 2 —— hook 開頭的 `trap 'exit 0' ERR` 會讓任何
# 未加保護的非零指令靜默變成放行，所以這個接線本身就是一個獨立的失效點。


def run_hook_with_env(command: str, cwd: Path, extra_path: Path | None) -> int:
    """在指定 cwd 執行 hook，並可把假 gh 所在目錄放到 PATH 最前面。"""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = dict(os.environ)
    if extra_path is not None:
        env["PATH"] = f"{extra_path}{os.pathsep}{env['PATH']}"
    env.pop("PROTECT_PUSH_SKIP_PR_STATE", None)
    result = subprocess.run(  # nosec B603
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=30,
    )
    return result.returncode


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


class TestMergedPrPush:
    def test_pp_block_019_explicit_refspec_to_merged_pr_branch(self, tmp_path: Path) -> None:
        """PR 已 merged 的分支 + explicit refspec → 攔截。

        explicit refspec 是保護 3 直接放行的形式（PR #449 事故用的就是它），所以這個案例證明
        保護 4 掛在早退之前，而不是被早退繞過。
        """
        _write_fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": "MERGED"}]))
        assert (
            run_hook_with_env(
                "git push origin feat-a:feat-a", _throwaway_repo(tmp_path), tmp_path / "bin"
            )
            == 2
        )

    def test_pp_block_020_bare_push_to_merged_pr_branch(self, tmp_path: Path) -> None:
        """PR 已 merged 的分支 + 裸 push → 攔截。"""
        _write_fake_gh(tmp_path / "bin", json.dumps([{"number": 448, "state": "MERGED"}]))
        assert run_hook_with_env("git push", _throwaway_repo(tmp_path), tmp_path / "bin") == 2

    def test_pp_allow_020_open_pr_branch(self, tmp_path: Path) -> None:
        """PR 仍 open → 放行（負向對照：證明上面兩個攔截不是無條件擋 push）。"""
        _write_fake_gh(tmp_path / "bin", json.dumps([{"number": 500, "state": "OPEN"}]))
        assert (
            run_hook_with_env(
                "git push origin feat-a:feat-a", _throwaway_repo(tmp_path), tmp_path / "bin"
            )
            == 0
        )

    def test_pp_allow_021_gh_missing_fails_open(self, tmp_path: Path) -> None:
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

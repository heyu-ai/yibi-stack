"""protect-push.sh 黑盒測試。

策略：用 subprocess 呼叫 hook，傳入 Claude Code PreToolUse JSON 格式，
      驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）
"""

import json
import subprocess
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

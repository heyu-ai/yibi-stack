"""bash-ap2-check.py 黑盒測試。

策略：用 subprocess 呼叫 AP2 hook，傳入 Claude Code PreToolUse JSON 格式，
      驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）
"""

import json
import subprocess
from pathlib import Path

HOOK = Path(__file__).parent.parent / "bash-ap2-check.py"


def run_hook(command: str) -> int:
    """以給定指令字串執行 AP2 hook，回傳 exit code。"""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode


# ── 基本放行行為 ───────────────────────────────────────────────────────


class TestAP2Allowed:
    def test_ap2_allow_001_plain_echo(self) -> None:
        """純 ASCII echo -> 放行"""
        assert run_hook("echo hello") == 0

    def test_ap2_allow_002_fail_text(self) -> None:
        """[FAIL] 文字（修復後）-> 放行"""
        assert run_hook("echo '[FAIL] jq 未安裝'") == 0

    def test_ap2_allow_003_warn_text(self) -> None:
        """[WARN] 文字（修復後）-> 放行"""
        assert run_hook("echo '[WARN] DB 不存在'") == 0

    def test_ap2_allow_004_skip_text(self) -> None:
        """[SKIP] 文字 -> 放行"""
        assert run_hook("echo '[SKIP] 無 docker-compose'") == 0

    def test_ap2_allow_005_ok_text(self) -> None:
        """[OK] 文字 -> 放行"""
        assert run_hook("echo '[OK] 修正完成'") == 0

    def test_ap2_allow_006_non_bash_tool(self) -> None:
        """非 Bash tool -> 放行（tool_name 過濾）"""
        payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/a"}})
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_ap2_allow_007_git_commit_with_emoji_in_message(self) -> None:
        """git commit -m 含 emoji -> 豁免（commit message 不限制）"""
        assert run_hook('git commit -m "feat: add ✓ check"') == 0

    def test_ap2_allow_008_git_dash_c_commit_with_emoji_in_message(self) -> None:
        """git -C /path commit -m 含 emoji -> 豁免（git -C 形式的豁免修復）"""
        assert run_hook('git -C /path/to/repo commit -m "feat: add ✓ check"') == 0


# ── 基本攔截行為 ───────────────────────────────────────────────────────


class TestAP2Blocked:
    def test_ap2_block_001_checkmark_unicode(self) -> None:
        """✓ (U+2713, U+2600-U+27BF) in echo -> 攔截"""
        assert run_hook("echo '✓ done'") == 2

    def test_ap2_block_002_warning_emoji(self) -> None:
        """⚠️ emoji in echo -> 攔截"""
        assert run_hook('echo "⚠️ DB 不存在"') == 2

    def test_ap2_block_003_cross_mark_unicode(self) -> None:
        """✗ (U+2717) in echo -> 攔截"""
        assert run_hook('echo "✗ jq 未安裝"') == 2

    def test_ap2_block_004_em_dash(self) -> None:
        """em dash (—) in echo -> 攔截"""
        assert run_hook('echo "error — please fix"') == 2

    def test_ap2_block_005_en_dash(self) -> None:
        """en dash (–) in echo -> 攔截"""
        assert run_hook('echo "range 1–10"') == 2


# ── handover 修復前後對比 ──────────────────────────────────────────────


class TestHandoverAP2Patterns:
    """fix-handover-skill-anti-bash：handover/handover-back.md AP2 修復驗證。"""

    # 舊模式：應被攔截
    def test_handover_ap2_block_001_old_fail_mark(self) -> None:
        """舊模式 echo '✗ jq 未安裝' (AP2) -> 攔截"""
        assert run_hook("echo '✗ jq 未安裝，請執行：brew install jq' >&2") == 2

    def test_handover_ap2_block_002_old_warn_db(self) -> None:
        """舊模式 echo '⚠️  DB 不存在' (AP2) -> 攔截"""
        assert (
            run_hook('echo "⚠️  DB 不存在，請先跑 uv run python -m tasks.session_memory init"') == 2
        )

    # 新模式：應放行
    def test_handover_ap2_allow_001_new_fail_jq(self) -> None:
        """新模式 echo '[FAIL] jq 未安裝' -> 放行（修復後）"""
        assert run_hook("echo '[FAIL] jq 未安裝，請執行：brew install jq' >&2") == 0

    def test_handover_ap2_allow_002_new_warn_db(self) -> None:
        """新模式 echo '[WARN] DB 不存在' -> 放行（修復後）"""
        assert (
            run_hook('echo "[WARN] DB 不存在，請先跑 uv run python -m tasks.session_memory init"')
            == 0
        )

    def test_handover_ap2_allow_003_new_fail_skill_repo(self) -> None:
        """新模式 echo '[FAIL] skill_repo 未設定' -> 放行（修復後）"""
        assert (
            run_hook(
                "echo '[FAIL] skill_repo 未設定，請在 ainization-skill 目錄執行 make install' >&2"
            )
            == 0
        )

    def test_handover_ap2_allow_004_new_fail_path(self) -> None:
        """新模式 echo "[FAIL] skill_repo 路徑不存在或非目錄" $VAR 展開 -> 放行（修復後）"""
        cmd = (
            '[ -d "$SKILL_REPO" ] || '
            '{ echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; }'
        )
        assert run_hook(cmd) == 0

"""bash-smart-fix.py 攔截訊息輸出通道回歸鎖。

smart-fix 只有 shipped 副本（plugins/harness/hooks/），無 .claude/hooks/ dogfood 版。
本測試鎖住：攔截（exit 2）時 _print_fix() 的指引必須走 stderr、stdout 必須空。
把 _print_fix() 的 print 改回 stdout（拿掉 file=sys.stderr）會讓本測試變紅。

Claude Code 的 PreToolUse 協定在 exit 2 時只從 stderr 讀 block 原因；印到 stdout
會讓 stderr 為空，顯示 generic "hook error: No stderr output"。

Probed. Mutation-verified in Source: PR #397 —— 把 _print_fix() 的一個 print 改回
stdout 會讓本測試變紅（stdout 非空），還原後轉綠；隔離突變、git status 乾淨。
"""

import json
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = _REPO_ROOT / "plugins" / "harness" / "hooks" / "bash-smart-fix.py"


def run_hook_full(command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestSmartFixBlockOutputChannel:
    def test_smart_fix_block_guidance_on_stderr_not_stdout(self) -> None:
        # Rule 2：外層雙引號包 $(...) subshell -> 攔截並印修正建議
        result = run_hook_full('echo "$(git rev-parse HEAD)"')
        assert result.returncode == 2
        assert result.stderr.strip() != "", "block 指引必須輸出到 stderr"
        assert result.stdout.strip() == "", "block 路徑不得輸出到 stdout"

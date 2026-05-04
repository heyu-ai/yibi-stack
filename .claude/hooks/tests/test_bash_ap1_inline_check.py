"""bash-ap1-inline-check.sh 黑盒測試。

策略：用 subprocess 呼叫 hook，傳入 Claude Code PreToolUse JSON 格式，
      驗證 exit code：
        0 = 放行
        2 = 攔截（BLOCK）
"""

import json
import subprocess
from pathlib import Path

HOOK = Path(__file__).parent.parent / "bash-ap1-inline-check.sh"


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


# ── 放行行為 ──────────────────────────────────────────────────────────


class TestAllowed:
    def test_ap1_allow_001_plain_echo(self) -> None:
        """一般指令應放行"""
        assert run_hook("echo hello") == 0

    def test_ap1_allow_002_invalid_json_fail_open(self) -> None:
        """無效 JSON -> 靜默放行（fail-open）"""
        assert run_hook_raw("not valid json") == 0

    def test_ap1_allow_003_empty_stdin_fail_open(self) -> None:
        """空輸入 -> 靜默放行"""
        assert run_hook_raw("") == 0

    def test_ap1_allow_004_python_single_line(self) -> None:
        """單行 python3 -c 應放行（不違反 AP1）"""
        assert run_hook("python3 -c \"print('hello')\"") == 0

    def test_ap1_allow_005_python_script_file(self) -> None:
        """呼叫 .py 檔案（非 -c inline）應放行"""
        assert run_hook("python3 scripts/check.py") == 0

    def test_ap1_allow_006_uv_run_script_file(self) -> None:
        """uv run + script 檔案應放行"""
        assert run_hook("uv run python3 scripts/check.py") == 0

    def test_ap1_allow_007_osascript_file(self) -> None:
        """osascript 呼叫 .applescript 檔案（非 heredoc）應放行"""
        assert run_hook("osascript scripts/check_windows.applescript") == 0

    def test_ap1_allow_008_git_multiline_no_python(self) -> None:
        """git commit heredoc（無 python -c，不觸發偵測）應放行"""
        cmd = "git commit -m \"$(cat <<'EOF'\nfeat: add feature\nEOF\n)\""
        assert run_hook(cmd) == 0

    def test_ap1_allow_009_uv_run_with_directory(self) -> None:
        """uv run --directory（正確修法）應放行"""
        assert run_hook("uv run --directory /path/to/project python3 scripts/check.py") == 0

    def test_ap1_allow_010_backslash_n_literal_in_string(self) -> None:
        """Codex P2 fix: python3 -c 字串 literal 含 \\n 兩字元（非換行）-> 放行"""
        cmd = "python3 -c \"print('hello\\nworld')\""
        assert run_hook(cmd) == 0

    def test_ap1_allow_011_single_line_python_then_heredoc(self) -> None:
        """Codex P2 fix: python3 -c 單行後接 heredoc -> 放行（全域掃描誤攔修正）"""
        cmd = "python3 -c \"print(1)\" && cat <<'EOF'\nplain text\nEOF"
        assert run_hook(cmd) == 0


# ── 攔截行為 ──────────────────────────────────────────────────────────


class TestBlocked:
    def test_ap1_block_001_python3_multiline(self) -> None:
        """python3 -c 含換行 -> 攔截"""
        cmd = 'python3 -c "\nimport sys\nprint(sys.version)\n"'
        assert run_hook(cmd) == 2

    def test_ap1_block_002_uv_run_python_multiline(self) -> None:
        """uv run python3 -c 含換行 -> 攔截"""
        cmd = 'uv run python3 -c "\nimport asyncio\nasyncio.run(main())\n"'
        assert run_hook(cmd) == 2

    def test_ap1_block_003_python_async_db_query(self) -> None:
        """Case 17 模式：cd + python3 -c async DB query -> 攔截"""
        cmd = (
            "cd /path/backend && \\\n"
            '  uv run python3 -c "\n'
            "import asyncio\n"
            "from src.config import settings\n"
            "\n"
            "async def main():\n"
            "    # Check stats\n"
            "    result = await session.execute(text('''SELECT COUNT(*) FROM t'''))\n"
            "    print(result.fetchone())\n"
            "\n"
            "asyncio.run(main())\n"
            '" 2>&1'
        )
        assert run_hook(cmd) == 2

    def test_ap1_block_004_osascript_heredoc(self) -> None:
        """osascript heredoc -> 攔截"""
        cmd = (
            "osascript << 'ASCRIPT'\n"
            'tell application "System Events"\n'
            '    tell process "Finder"\n'
            "        return name of every window\n"
            "    end tell\n"
            "end tell\n"
            "ASCRIPT"
        )
        assert run_hook(cmd) == 2

    def test_ap1_block_005_osascript_heredoc_simulator(self) -> None:
        """Case 16 模式：osascript + Simulator 窗口列舉 -> 攔截"""
        cmd = (
            "osascript << 'ASCRIPT'\n"
            'tell application "System Events"\n'
            '    tell process "Simulator"\n'
            "        set winList to {}\n"
            "        repeat with w in every window\n"
            '            set winList to winList & {name of w & " : " & (position of w as string)}\n'
            "        end repeat\n"
            "        return winList\n"
            "    end tell\n"
            "end tell\n"
            "ASCRIPT"
        )
        assert run_hook(cmd) == 2

    def test_ap1_block_006_python_multiline_with_comment(self) -> None:
        """Case 17/18 共同模式：python3 -c 含 # comment + 換行 -> 攔截"""
        cmd = (
            'uv run python3 -c "\n'
            "import asyncio\n"
            "# Check completed jobs\n"
            "async def main():\n"
            "    pass\n"
            "asyncio.run(main())\n"
            '"'
        )
        assert run_hook(cmd) == 2

    def test_ap1_block_007_case18_pythonpath_pipe_grep(self) -> None:
        """Case 18 模式：cd + PYTHONPATH + python3 -c + pipe grep -> 攔截"""
        cmd = (
            'cd /path/backend && PYTHONPATH=src uv run python3 -c "\n'
            "import asyncio\n"
            "from infrastructure.config.database import async_session_factory\n"
            "\n"
            "async def main():\n"
            "    # Check completed jobs\n"
            "    async with async_session_factory() as session:\n"
            "        rows = (await session.execute(text('''SELECT id FROM jobs'''))).fetchall()\n"
            "        for r in rows: print(r)\n"
            "\n"
            "asyncio.run(main())\n"
            '" 2>&1 | grep -v "^2026"'
        )
        assert run_hook(cmd) == 2

    def test_ap1_block_008_ansi_c_quoting(self) -> None:
        """ANSI-C quoting $'...\\n...' -> 攔截"""
        cmd = r"python3 -c $'import sys\nprint(sys.version)'"
        assert run_hook(cmd) == 2

    def test_ap1_block_009_python_unversioned_multiline(self) -> None:
        """python -c（無版本號）含換行 -> 攔截"""
        cmd = 'python -c "\nimport sys\nprint(sys.version)\n"'
        assert run_hook(cmd) == 2

    def test_ap1_block_010_python_dot_version(self) -> None:
        """python3.11 -c（點版本號）含換行 -> 攔截"""
        cmd = 'python3.11 -c "\nimport sys\nprint(sys.version)\n"'
        assert run_hook(cmd) == 2

    def test_ap1_block_011_osascript_heredoc_extra_whitespace(self) -> None:
        """Codex P2 fix: osascript heredoc 多餘空格（原精確匹配會漏掉）-> 攔截"""
        cmd = "osascript  << 'ASCRIPT'\ntell application \"Finder\"\nend tell\nASCRIPT"
        assert run_hook(cmd) == 2

    def test_ap1_block_012_python_interpreter_flag(self) -> None:
        """Codex P1 fix: python3 -I -c 含換行（flag 在 -c 前）-> 攔截"""
        cmd = 'python3 -I -c "\nimport sys\nprint(sys.version)\n"'
        assert run_hook(cmd) == 2

    def test_ap1_block_013_python_extra_whitespace_before_c(self) -> None:
        """Codex P1 fix: python3    -c 多空格（原 regex 只匹配一個空格）-> 攔截"""
        cmd = 'python3    -c "\nimport sys\nprint(sys.version)\n"'
        assert run_hook(cmd) == 2

    def test_ap1_block_014_osascript_javascript_flag(self) -> None:
        """Codex P1 fix: osascript -l JavaScript heredoc -> 攔截"""
        cmd = "osascript -l JavaScript <<'JS'\nconsole.log(1)\nJS"
        assert run_hook(cmd) == 2

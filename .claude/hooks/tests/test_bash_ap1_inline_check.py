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


class TestGrepBRECase25:
    """Case 25：grep 雙引號 BRE alternation \\| 觸發 D 類。"""

    def test_ap1_block_015_grep_dquote_backslash_pipe(self) -> None:
        """grep -i 雙引號 \\| BRE alternation -> 攔截"""
        assert run_hook('grep -i "media\\|cdn" file.txt') == 2

    def test_ap1_block_016_grep_dquote_multi_alternation(self) -> None:
        """grep 雙引號多個 \\| -> 攔截（Case 25a 原型）"""
        assert run_hook('grep -i "media\\|cdn\\|delivery" file.txt') == 2

    def test_ap1_block_017_grep_dquote_status_match(self) -> None:
        """grep 雙引號 \\| status filter -> 攔截（Case 25b 原型）"""
        assert run_hook('git status --short | grep "media-delivery\\|openspec" | head -20') == 2

    def test_ap1_allow_015_grep_squote_backslash_pipe(self) -> None:
        """grep 單引號 \\| BRE -> 放行（正確修法 A）"""
        assert run_hook("grep -i 'media\\|cdn' file.txt") == 0

    def test_ap1_allow_016_grep_E_flag_dquote(self) -> None:
        """grep -E 雙引號 ERE -> 放行（-E 排除）"""
        assert run_hook('grep -E "media|cdn" file.txt') == 0

    def test_ap1_allow_017_grep_Ei_combined_flag(self) -> None:
        """grep -Ei 組合 flag 含 E -> 放行（-E 在組合 flag 中）"""
        assert run_hook('grep -Ei "media\\|cdn" file.txt') == 0

    def test_ap1_allow_018_grep_extended_regexp_long_form(self) -> None:
        """grep --extended-regexp 長格式 -> 放行"""
        assert run_hook('grep --extended-regexp "media|cdn" file.txt') == 0

    def test_ap1_allow_019_rg_not_grep(self) -> None:
        """rg (ripgrep) 不是 grep -> 放行"""
        assert run_hook('rg "media\\|cdn" file.txt') == 0

    def test_ap1_block_018_sed_E_does_not_exempt_later_grep(self) -> None:
        """sed -E && grep BRE: -E 不跨指令豁免後面的 grep -> 攔截（scope fix）"""
        assert run_hook('sed -E "s/x/y/" file && grep "media\\|cdn" log') == 2


class TestNestedSubshellCase26:
    """Case 26：$(outer "$(inner)") 反向巢狀 subshell 觸發 D 類。"""

    def test_ap1_block_018_nested_subshell_dirname_git(self) -> None:
        """$(dirname "$(git rev-parse ...)") -> 攔截（Case 26 原型）"""
        assert run_hook('MAIN=$(dirname "$(git rev-parse --git-common-dir)")') == 2

    def test_ap1_block_019_nested_subshell_generic(self) -> None:
        """$(outer_cmd "$(inner_cmd)") 通用模式 -> 攔截"""
        assert run_hook('RESULT=$(process "$(fetch --url http://example.com)")') == 2

    def test_ap1_allow_018_simple_subshell_no_dquote(self) -> None:
        """$(git rev-parse HEAD) 無巢狀雙引號 -> 放行"""
        assert run_hook("FOO=$(git rev-parse HEAD)") == 0

    def test_ap1_allow_019_subshell_with_dquote_var(self) -> None:
        """$(git -C "$REPO" log) 雙引號變數（非巢狀 subshell）-> 放行"""
        assert run_hook('git -C "$REPO" log --oneline -5') == 0

    def test_ap1_allow_020_awk_subshell(self) -> None:
        """$(git list | awk '{print $1}') 單引號 awk 不觸發 -> 放行"""
        assert run_hook("MAIN=$(git worktree list | head -1 | awk '{print $1}')") == 0

    def test_ap1_block_020_nested_subshell_with_intermediate_quoted_arg(self) -> None:
        """$(outer --opt "value" "$(inner)") 中間有引號引數也應攔截"""
        assert run_hook('RESULT=$(process --opt "value" "$(inner_cmd)")') == 2

    def test_ap1_block_021_literal_paren_in_string_before_nested_subshell(self) -> None:
        """echo ) ( 含 literal ) 後接真正的巢狀 subshell -> 攔截（state machine fix）"""
        assert run_hook('echo ") (" && FOO=$(cmd "$(inner)")') == 2

    def test_ap1_allow_021_echo_date_not_nested(self) -> None:
        """echo \"$(date)\" 無外層 $() -> 放行"""
        assert run_hook('echo "$(date)"') == 0

    def test_ap1_allow_022_two_independent_subshells(self) -> None:
        """FOO=$(cmd) && echo \"$(date)\" 兩個獨立 $() -> 放行"""
        assert run_hook('BRANCH=$(git branch --show-current) && echo "$(date): done"') == 0


class TestGitCommitExemption:
    """git commit -m heredoc 豁免：commit message 內含範例程式碼不應誤攔。"""

    def test_ap1_allow_021_git_commit_heredoc_with_nested_subshell_example(self) -> None:
        """commit message 含 Case 26 範例 -> 豁免（false positive 防護）"""
        cmd = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: add feature\n"
            "\n"
            '- 修法：$(outer "$(inner)")\n'
            "EOF\n"
            ')"'
        )
        assert run_hook(cmd) == 0

    def test_ap1_allow_022_git_commit_heredoc_with_grep_example(self) -> None:
        """commit message 含 Case 25 範例（grep 雙引號 BRE）-> 豁免"""
        cmd = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: add grep hook\n"
            "\n"
            '- rule: grep "pat\\|pat2" -> block\n'
            "EOF\n"
            ')"'
        )
        assert run_hook(cmd) == 0

    def test_ap1_allow_023_git_commit_plain_single_quoted_message(self) -> None:
        """git commit -m 'plain single-quoted msg' -> 放行（非 heredoc，不豁免但也不觸發）"""
        assert run_hook("git commit -m 'add grep rule for pat\\|pat2'") == 0

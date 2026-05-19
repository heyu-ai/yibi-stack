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

# Pattern C canonical: python3 -c 單行讀取 skill_repo（jq 的安全替代方案）
_SKILL_REPO_PY = (
    "import json,pathlib; "
    "print(json.loads("
    "(pathlib.Path.home()/'.agents'/'config.json').read_text()"
    ").get('skill_repo') or '')"
)


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

    def test_ap1_block_019_rg_bre_double_quoted(self) -> None:
        """rg 雙引號 pattern 含 \\| -> Detection 6 攔截（ERE 工具誤用 BRE 語法）"""
        assert run_hook('rg "media\\|cdn" file.txt') == 2

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
        """$(git list | awk '{print $1}') 單引號 awk hook 不觸發 -> 放行
        注意：awk '{print $1}' 在 $() 內仍觸發 CC 內建 parser 確認框（非本 hook 範疇）
        newjob 已替換為 git worktree list --porcelain + #worktree prefix removal"""
        assert run_hook("MAIN=$(git worktree list | head -1 | awk '{print $1}')") == 0

    def test_ap1_allow_023_porcelain_bare_pipeline(self) -> None:
        """WT_LINE=$(git worktree list --porcelain | head -1) 無引號引數 -> 放行（newjob 新模式）"""
        assert run_hook("WT_LINE=$(git worktree list --porcelain | head -1)") == 0

    def test_ap1_allow_024_prefix_removal_expansion(self) -> None:
        """MAIN_REPO=${WT_LINE#worktree } prefix removal -> 放行（newjob 新模式）"""
        assert run_hook("MAIN_REPO=${WT_LINE#worktree }") == 0

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


class TestHandoverAntiBashPatterns:
    """fix-handover-skill-anti-bash：handover/session-memory 指令模式驗證。

    舊模式（修復前）應被 hook 攔截，新模式（修復後）應放行。
    Note：jq '//' trigger 是 Claude Code 內建 checker，非本 hook 範圍——僅驗證 Rule 4。
    """

    # ── 舊模式：應被攔截 ──────────────────────────────────────────────

    def test_handover_block_001_basename_dirname_nested(self) -> None:
        """$(basename "$(dirname ...)") Rule 4 nested subshell -> 攔截"""
        cmd = (
            "_gcd=$(git rev-parse --git-common-dir 2>/dev/null)\n"
            'ORIG=$(basename "$(dirname "$_gcd")")'
        )
        assert run_hook(cmd) == 2

    def test_handover_block_002_basename_git_show_toplevel_nested(self) -> None:
        """$(basename "$(git rev-parse --show-toplevel)") Rule 4 -> 攔截（session-memory 舊模式）"""
        cmd = 'ORIG=$(basename "$(git rev-parse --show-toplevel)")'
        assert run_hook(cmd) == 2

    def test_handover_block_003_basename_pwd_nested(self) -> None:
        """PROJECT=$(basename "$(pwd)") Rule 4 -> 攔截（handover/SKILL.md Step 3 舊模式）"""
        cmd = 'PROJECT=$(basename "$(pwd)")'
        assert run_hook(cmd) == 2

    # ── 新模式：應放行 ────────────────────────────────────────────────

    def test_handover_allow_001_dirname_split_two_calls(self) -> None:
        """拆成兩個 call: _dir=$(dirname ...) + basename "$_dir" -> 放行（修復後）"""
        cmd = '_dir=$(dirname "$_gcd")\nORIG=$(basename "$_dir")'
        assert run_hook(cmd) == 0

    def test_handover_allow_002_git_show_toplevel_split(self) -> None:
        """_top=$(git rev-parse --show-toplevel) + basename "$_top" -> 放行（修復後）"""
        cmd = '_top=$(git rev-parse --show-toplevel)\nORIG=$(basename "$_top")'
        assert run_hook(cmd) == 0

    def test_handover_allow_003_basename_pwd_var(self) -> None:
        """PROJECT=$(basename "$PWD") 用 $PWD 變數，無巢狀 subshell -> 放行（修復後）"""
        cmd = 'PROJECT=$(basename "$PWD")'
        assert run_hook(cmd) == 0

    def test_handover_block_004_jq_single_quoted_filter(self) -> None:
        """SKILL_REPO=$(jq -r '.skill_repo' ...) 單引號 filter -> 攔截（Detector 5）"""
        cmd = (
            "SKILL_REPO=$(jq -r '.skill_repo' ~/.agents/config.json)\n"
            '[ "$SKILL_REPO" = "null" ] && SKILL_REPO=""\n'
            'uv run --directory "$SKILL_REPO" \\\n'
            "  python -m tasks.session_memory handover read --last 1"
        )
        assert run_hook(cmd) == 2

    def test_handover_allow_004_jq_unquoted_filter(self) -> None:
        """$(jq -r .skill_repo) 無引號 -> hook 放行，但 CC 內建 analyzer 仍可能跳確認框"""
        cmd = (
            "SKILL_REPO=$(jq -r .skill_repo ~/.agents/config.json)\n"
            '[ "$SKILL_REPO" = "null" ] && SKILL_REPO=""\n'
            'uv run --directory "$SKILL_REPO" \\\n'
            "  python -m tasks.session_memory handover read --last 1"
        )
        assert run_hook(cmd) == 0

    def test_handover_allow_004_full_handover_read_fixed(self) -> None:
        """完整 handover read 指令（python3 -c canonical，修復後）-> 放行"""
        cmd = (
            f'SKILL_REPO=$(python3 -c "{_SKILL_REPO_PY}")\n'
            "[ -z \"$SKILL_REPO\" ] && { echo '[FAIL] skill_repo 未設定' >&2; exit 1; }\n"
            'uv run --directory "$SKILL_REPO" \\\n'
            "  python -m tasks.session_memory handover read --last 1"
        )
        assert run_hook(cmd) == 0

    def test_handover_allow_008_python3_skill_repo(self) -> None:
        """python3 -c 單行讀 skill_repo（Pattern C canonical）-> 放行"""
        cmd = f'SKILL_REPO=$(python3 -c "{_SKILL_REPO_PY}")'
        assert run_hook(cmd) == 0

    def test_handover_block_005_jq_no_flags(self) -> None:
        """$(jq '.key' file) 無 flag 單引號 filter -> 攔截"""
        assert run_hook("VAL=$(jq '.key' file.json)") == 2

    def test_handover_block_006_jq_multi_flags(self) -> None:
        """$(jq -r -e '.key' file) 多 flag 單引號 filter -> 攔截"""
        assert run_hook("VAL=$(jq -r -e '.key' file.json)") == 2

    def test_handover_block_007_jq_filter_with_pipe(self) -> None:
        """$(jq -r '.a | .b' file) filter 含管線 -> 攔截"""
        assert run_hook("VAL=$(jq -r '.a | .b' file.json)") == 2

    def test_handover_allow_006_jq_unquoted_nested_path(self) -> None:
        """$(jq -r .a.b file) 無引號複合路徑 -> 放行"""
        assert run_hook("VAL=$(jq -r .user.name ~/.agents/config.json)") == 0

    def test_handover_allow_007_jq_dollar_in_filter(self) -> None:
        """$(jq -r '.[\"$var\"]' file) filter 含 $ -> 放行（可能合法 jq 表達式）"""
        assert run_hook("VAL=$(jq -r '.[\"$key\"]' data.json)") == 0

    def test_handover_allow_005_case_statement_fixed(self) -> None:
        """修復後的 case 陳述式（拆成兩行）-> 放行"""
        cmd = (
            "_gcd=$(git rev-parse --git-common-dir 2>/dev/null)\n"
            'case "$_gcd" in\n'
            "    /*)\n"
            '      _dir=$(dirname "$_gcd")\n'
            '      ORIG=$(basename "$_dir")\n'
            "      unset _dir ;;\n"
            "    ?*)\n"
            "      _top=$(git rev-parse --show-toplevel)\n"
            '      ORIG=$(basename "$_top")\n'
            "      unset _top ;;\n"
            "    *)\n"
            '      ORIG=$(basename "$PWD") ;;\n'
            "esac"
        )
        assert run_hook(cmd) == 0


class TestRgBREDetection6:
    """Detection 6：rg '...\\|...' BRE alternation 在 ERE 工具（靜默空結果）。

    rg 使用 Rust ERE-like regex：| 是 alternation，\\| 是 literal pipe。
    含 \\| 的 pattern 靜默搜尋 literal pipe，回傳 0 筆無報錯。
    """

    def test_ap1_block_020_rg_single_quoted_backslash_pipe(self) -> None:
        """rg 單引號 pattern 含 \\| -> 攔截（最常見的誤用情境）"""
        assert run_hook("rg -rl 'foo\\|bar\\|baz' /path") == 2

    def test_ap1_block_021_rg_double_quoted_backslash_pipe(self) -> None:
        """rg 雙引號 pattern 含 \\| -> 攔截（遷移自 grep 時的常見錯誤）"""
        assert run_hook('rg "media\\|cdn\\|delivery" file.txt') == 2

    def test_ap1_block_022_rg_with_flags_backslash_pipe(self) -> None:
        """rg -rl 帶 flag 的 pattern 含 \\| -> 攔截"""
        assert run_hook("rg -rl '五層\\|Event Storm\\|ezSpec' /Users/howie/Workspace") == 2

    def test_ap1_allow_020_rg_ere_alternation(self) -> None:
        """rg 正確 ERE | alternation（無反斜線）-> 放行"""
        assert run_hook("rg -rl 'foo|bar|baz' /path") == 0

    def test_ap1_allow_021_rg_no_alternation(self) -> None:
        """rg 無 alternation pattern -> 放行"""
        assert run_hook("rg -l 'pattern' /path") == 0

    def test_ap1_allow_022_rg_multiple_e_flags(self) -> None:
        """rg 多個 -e flag -> 放行"""
        assert run_hook("rg -l -e 'foo' -e 'bar' /path") == 0

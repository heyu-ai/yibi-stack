"""Retrieval hooks 測試。"""

from __future__ import annotations

import json
from io import StringIO

from tasks.mycelium.retrieval_hooks import run_precompact_hook, run_pretooluse_hook


def _make_precompact_payload(transcript_path: str = "/nonexistent.jsonl") -> str:
    return json.dumps(
        {
            "hook_event_name": "PreCompact",
            "transcript_path": transcript_path,
            "agent_type": "claude",
        }
    )


def _make_pretooluse_payload(command: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


class TestRunPrecompactHook:
    def test_myc_hooks_dt_001_wrong_event(self) -> None:
        """MYC-HOOKS-DT-001: non-PreCompact event -> returns 0 silently"""
        payload = json.dumps({"hook_event_name": "Stop"})
        result = run_precompact_hook(stdin_text=payload)
        assert result == 0

    def test_myc_hooks_dt_002_invalid_json(self) -> None:
        """MYC-HOOKS-DT-002: invalid JSON -> returns 0 silently"""
        result = run_precompact_hook(stdin_text="not json")
        assert result == 0

    def test_myc_hooks_dt_003_never_blocks(self) -> None:
        """MYC-HOOKS-DT-003: always returns 0 (never blocks Claude)"""
        result = run_precompact_hook(stdin_text=_make_precompact_payload())
        assert result == 0


class TestRunPretoolUseHook:
    def test_myc_hooks_dt_004_safe_command_no_warning(self) -> None:
        """MYC-HOOKS-DT-004: safe command -> no pitfall output"""
        out = StringIO()
        payload = _make_pretooluse_payload("echo hello")
        result = run_pretooluse_hook(stdin_text=payload, output_stream=out)
        assert result == 0
        assert out.getvalue() == ""

    def test_myc_hooks_dt_005_git_push_triggers(self) -> None:
        """MYC-HOOKS-DT-005: 'git push' command triggers pitfall check"""
        out = StringIO()
        payload = _make_pretooluse_payload("git push origin main")
        # No DB lessons available, so no output — just confirm it doesn't crash
        result = run_pretooluse_hook(stdin_text=payload, output_stream=out)
        assert result == 0

    def test_myc_hooks_dt_006_fake_git_force_no_longer_matches(self) -> None:
        """MYC-HOOKS-DT-006: 'git force' (old fake pattern) no longer triggers"""
        out = StringIO()
        payload = _make_pretooluse_payload("git force something")
        result = run_pretooluse_hook(stdin_text=payload, output_stream=out)
        assert result == 0
        assert out.getvalue() == ""

    def test_myc_hooks_dt_007_force_flag_triggers(self) -> None:
        """MYC-HOOKS-DT-007: '--force' flag triggers pitfall check"""
        out = StringIO()
        payload = _make_pretooluse_payload("git push --force origin main")
        result = run_pretooluse_hook(stdin_text=payload, output_stream=out)
        assert result == 0

    def test_myc_hooks_dt_008_echo_with_git_push_not_triggered(self) -> None:
        """MYC-HOOKS-DT-008: 'echo git push' (comment context) does not trigger"""
        out = StringIO()
        payload = _make_pretooluse_payload("echo 'do not git push directly'")
        result = run_pretooluse_hook(stdin_text=payload, output_stream=out)
        assert result == 0
        assert out.getvalue() == ""

    def test_myc_hooks_dt_009_wrong_event_type(self) -> None:
        """MYC-HOOKS-DT-009: non-PreToolUse event -> returns 0"""
        payload = json.dumps({"hook_event_name": "Stop", "tool_name": "Bash"})
        out = StringIO()
        result = run_pretooluse_hook(stdin_text=payload, output_stream=out)
        assert result == 0

    def test_myc_hooks_dt_010_non_bash_tool_ignored(self) -> None:
        """MYC-HOOKS-DT-010: non-Bash tool -> returns 0"""
        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "/etc/passwd"},
            }
        )
        out = StringIO()
        result = run_pretooluse_hook(stdin_text=payload, output_stream=out)
        assert result == 0

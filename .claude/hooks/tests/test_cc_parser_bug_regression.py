"""CC bash parser bug regression monitor (ADR-0002).

Strategy A (primary): Call `claude --print --model claude-haiku-4-5-20251001`
with D3/D4/D5 minimal-repro commands and assert the issue is still present.
MUST use Haiku to avoid spending Sonnet/Opus tokens on every CI run.

Strategy B (fallback): When claude CLI is unavailable or does not expose parser
stderr, assert that anthropics/claude-code#56018 is still OPEN via GitHub API
(zero LLM token cost).

When the bug is fixed, these tests will fail — that is the intended signal to
remove D3/D4/D5 detections per ADR-0002 § Removal Condition.

Run with: pytest -m slow .claude/hooks/tests/test_cc_parser_bug_regression.py
Skip in fast loop: pytest -m "not slow"
"""

import json
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest

# ── shared helpers ─────────────────────────────────────────────────────────

ADR_URL = "https://github.com/anthropics/claude-code/issues/56018"
GH_ISSUE_API = (
    "https://api.github.com/repos/anthropics/claude-code/issues/56018"
)

# All three D-class patterns that trigger "Unhandled node type: string"
D3_REPRO = 'grep "foo\\|bar" /dev/null'      # double-quoted BRE alternation
D4_REPRO = 'dirname "$(git rev-parse --git-dir)"'  # reverse-nested subshell
D5_REPRO = 'VAR=$(jq -r \'.key\' /dev/null)'  # single-quoted jq in subshell

HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _claude_binary() -> str | None:
    """Return path to claude CLI, or None if not found."""
    result = subprocess.run(
        ["which", "claude"], capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _run_claude_print(command: str) -> subprocess.CompletedProcess:
    """Run `claude --print --model haiku` with the given command as input.

    Uses Haiku to avoid token waste — this test only needs parser behavior,
    not reasoning capability. The parser fires before model inference.
    """
    env = os.environ.copy()
    return subprocess.run(
        [
            "claude",
            "--print",
            "--model",
            HAIKU_MODEL,
            "--input-format",
            "text",
        ],
        input=command,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _github_issue_state() -> str | None:
    """Return GitHub issue state ('open'/'closed') or None on failure."""
    try:
        req = urllib.request.Request(
            GH_ISSUE_API,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("state")
    except Exception:
        return None


# ── Strategy A: direct parser probe ───────────────────────────────────────


@pytest.mark.slow
class TestCCParserBugDirectProbe:
    """Attempt to trigger the CC parser bug directly via claude --print.

    If claude CLI is unavailable, skip (Strategy B covers the fallback).
    If the bug is fixed (exit 0 with no parser error), FAIL with ADR-0002
    removal instructions.
    """

    @pytest.fixture(autouse=True)
    def require_claude_cli(self):
        if _claude_binary() is None:
            pytest.skip("claude CLI not found in PATH; using Strategy B instead")

    def _assert_parser_error_present(self, command: str, pattern_id: str):
        """Assert the CC parser bug is still present for the given repro command."""
        result = _run_claude_print(command)
        combined = result.stdout + result.stderr

        bug_fixed = (
            result.returncode == 0
            and "Unhandled node type" not in combined
            and "unhandled node type" not in combined.lower()
        )
        if bug_fixed:
            pytest.fail(
                f"\n\nADR-0002 REMOVAL CONDITION MET for {pattern_id}:\n"
                f"  Command: {command!r}\n"
                f"  claude --print exit code: {result.returncode}\n"
                f"  No 'Unhandled node type: string' in output.\n\n"
                f"ACTION REQUIRED:\n"
                f"  1. Verify manually: open a new Claude Code session\n"
                f"     and confirm the pattern runs without parser error.\n"
                f"  2. Remove D3/D4/D5 detections from bash-ap1-inline-check.sh\n"
                f"     (both plugins/bash-hygiene/hooks/ and .claude/hooks/ versions).\n"
                f"  3. Keep D1/D2/D6 — those block anti-patterns, not parser bugs.\n"
                f"  4. Update ADR-0002 status to 'superseded'.\n"
                f"  See: {ADR_URL}\n"
            )

    def test_d3_grep_bre_doublequote(self):
        """D3: grep double-quoted BRE alternation should still trigger parser bug."""
        self._assert_parser_error_present(D3_REPRO, "D3")

    def test_d4_nested_subshell(self):
        """D4: reverse-nested subshell should still trigger parser bug."""
        self._assert_parser_error_present(D4_REPRO, "D4")

    def test_d5_jq_singlequote_filter(self):
        """D5: jq single-quoted filter in subshell should still trigger parser bug."""
        self._assert_parser_error_present(D5_REPRO, "D5")


# ── Strategy B: GitHub issue state monitor ────────────────────────────────


@pytest.mark.slow
class TestCCParserBugIssueMonitor:
    """Monitor anthropics/claude-code#56018 via GitHub API.

    Zero LLM token cost. When the issue closes, manual verification of
    D3/D4/D5 removal is required (see ADR-0002 § Removal Condition).
    """

    def test_issue_56018_still_open(self):
        """Assert CC parser bug issue #56018 is still open.

        If this test fails with 'issue is closed', check whether the fix
        actually resolves D3/D4/D5 and remove those hook detections per ADR-0002.
        """
        state = _github_issue_state()

        if state is None:
            pytest.skip(
                "GitHub API unavailable (network issue or rate limit); "
                "skipping issue state check"
            )

        if state != "open":
            pytest.fail(
                f"\n\nADR-0002 REMOVAL CONDITION MET:\n"
                f"  anthropics/claude-code#56018 state is now: {state!r}\n\n"
                f"ACTION REQUIRED:\n"
                f"  1. Open {ADR_URL} and read the fix description.\n"
                f"  2. Verify that D3/D4/D5 patterns no longer cause 'Unhandled node type'.\n"
                f"  3. Remove D3/D4/D5 detections from bash-ap1-inline-check.sh\n"
                f"     (both plugins/bash-hygiene/hooks/ and .claude/hooks/ versions).\n"
                f"  4. Keep D1/D2/D6 — those block anti-patterns, not parser bugs.\n"
                f"  5. Update ADR-0002 status to 'superseded'.\n"
            )

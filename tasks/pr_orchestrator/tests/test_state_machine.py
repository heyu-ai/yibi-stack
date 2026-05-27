"""PROR-DT-NNN：State machine transition table 測試。"""

from __future__ import annotations

import pytest

from tasks.pr_orchestrator.models import OrchestratorState, PRState
from tasks.pr_orchestrator.service import (
    allowed_next_states,
    is_terminal,
    transition,
)


def make_state(**kwargs: object) -> OrchestratorState:
    defaults = {
        "pr_number": 1,
        "branch": "feat-test",
        "head_sha": "abc123",
    }
    return OrchestratorState(**{**defaults, **kwargs})


class TestTerminalStates:
    def test_pror_dt_001_cleaned_is_terminal(self) -> None:
        """PROR-DT-001: CLEANED 是 terminal state"""
        assert is_terminal(PRState.CLEANED)

    def test_pror_dt_002_blocked_is_terminal(self) -> None:
        """PROR-DT-002: BLOCKED 是 terminal state"""
        assert is_terminal(PRState.BLOCKED)

    def test_pror_dt_003_failed_is_terminal(self) -> None:
        """PROR-DT-003: FAILED 是 terminal state"""
        assert is_terminal(PRState.FAILED)

    def test_pror_dt_004_detected_not_terminal(self) -> None:
        """PROR-DT-004: DETECTED 不是 terminal state"""
        assert not is_terminal(PRState.DETECTED)


class TestAllowedTransitions:
    def test_pror_dt_005_detected_to_reviewing(self) -> None:
        """PROR-DT-005: DETECTED -> REVIEWING 合法"""
        assert PRState.REVIEWING in allowed_next_states(PRState.DETECTED)

    def test_pror_dt_006_detected_to_blocked(self) -> None:
        """PROR-DT-006: DETECTED -> BLOCKED 合法"""
        assert PRState.BLOCKED in allowed_next_states(PRState.DETECTED)

    def test_pror_dt_007_ci_wait_to_auto_fix(self) -> None:
        """PROR-DT-007: CI_WAIT -> AUTO_FIX 合法"""
        assert PRState.AUTO_FIX in allowed_next_states(PRState.CI_WAIT)

    def test_pror_dt_008_auto_fix_to_ci_wait(self) -> None:
        """PROR-DT-008: AUTO_FIX -> CI_WAIT 合法（迴圈）"""
        assert PRState.CI_WAIT in allowed_next_states(PRState.AUTO_FIX)

    def test_pror_dt_009_terminal_has_no_outbound(self) -> None:
        """PROR-DT-009: terminal states 沒有 outbound transition"""
        for s in (PRState.CLEANED, PRState.BLOCKED, PRState.FAILED):
            assert allowed_next_states(s) == frozenset()


class TestTransitionFunction:
    def test_pror_dt_010_valid_transition_updates_state(self) -> None:
        """PROR-DT-010: 合法 transition 更新 current_state 並記錄 Transition"""
        state = make_state(current_state=PRState.DETECTED)
        new_state = transition(state, PRState.REVIEWING, reason="test")
        assert new_state.current_state == PRState.REVIEWING
        assert len(new_state.transitions) == 1
        assert new_state.transitions[0].from_state == PRState.DETECTED
        assert new_state.transitions[0].to_state == PRState.REVIEWING
        assert new_state.transitions[0].reason == "test"

    def test_pror_dt_011_invalid_transition_raises(self) -> None:
        """PROR-DT-011: 非法 transition raise ValueError"""
        state = make_state(current_state=PRState.DETECTED)
        with pytest.raises(ValueError, match="非法 transition"):
            transition(state, PRState.MERGED)

    def test_pror_dt_012_transition_immutable(self) -> None:
        """PROR-DT-012: transition 不改動原始 state"""
        state = make_state(current_state=PRState.DETECTED)
        transition(state, PRState.REVIEWING)
        assert state.current_state == PRState.DETECTED

    def test_pror_dt_013_full_happy_path(self) -> None:
        """PROR-DT-013: 完整 happy-path 狀態鏈"""
        path = [
            PRState.REVIEWING,
            PRState.REVIEW_DONE,
            PRState.CI_WAIT,
            PRState.CI_PASS,
            PRState.MERGEABLE,
            PRState.MERGED,
            PRState.RETRO_DONE,
            PRState.CLEANED,
        ]
        state = make_state(current_state=PRState.DETECTED)
        for next_s in path:
            state = transition(state, next_s)
        assert state.current_state == PRState.CLEANED
        assert len(state.transitions) == len(path)

    def test_pror_dt_014_auto_fix_loop(self) -> None:
        """PROR-DT-014: AUTO_FIX <-> CI_WAIT 迴圈合法"""
        state = make_state(current_state=PRState.CI_WAIT)
        state = transition(state, PRState.AUTO_FIX, reason="markdownlint failure")
        state = transition(state, PRState.CI_WAIT, reason="fix applied")
        state = transition(state, PRState.AUTO_FIX, reason="ruff failure")
        assert state.current_state == PRState.AUTO_FIX

    def test_pror_dt_015_conflict_always_goes_blocked(self) -> None:
        """PROR-DT-015: CONFLICT 只能 -> BLOCKED"""
        state = make_state(current_state=PRState.CONFLICT)
        with pytest.raises(ValueError):
            transition(state, PRState.REVIEWING)
        new_state = transition(state, PRState.BLOCKED)
        assert new_state.current_state == PRState.BLOCKED

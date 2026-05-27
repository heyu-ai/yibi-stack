"""PR Orchestrator state machine 核心邏輯。"""

from __future__ import annotations

from datetime import UTC, datetime

from .models import Blocker, OrchestratorState, PRState, Transition

# Allowed transition table — 任何未列於此的 (from, to) 都屬非法
_TRANSITIONS: dict[PRState, frozenset[PRState]] = {
    PRState.DETECTED: frozenset({PRState.REVIEWING, PRState.CONFLICT, PRState.BLOCKED}),
    PRState.REVIEWING: frozenset({PRState.REVIEW_DONE, PRState.BLOCKED}),
    PRState.REVIEW_DONE: frozenset({PRState.CI_WAIT, PRState.CONFLICT}),
    PRState.CI_WAIT: frozenset(
        {PRState.CI_PASS, PRState.AUTO_FIX, PRState.CONFLICT, PRState.BLOCKED}
    ),
    PRState.AUTO_FIX: frozenset({PRState.CI_WAIT, PRState.BLOCKED, PRState.FAILED}),
    PRState.CI_PASS: frozenset({PRState.MERGEABLE, PRState.CONFLICT}),
    PRState.CONFLICT: frozenset({PRState.BLOCKED}),
    PRState.MERGEABLE: frozenset({PRState.MERGED, PRState.BLOCKED}),
    PRState.MERGED: frozenset({PRState.RETRO_DONE, PRState.FAILED}),
    PRState.RETRO_DONE: frozenset({PRState.CLEANED}),
    # Terminal states have no outbound transitions
    PRState.CLEANED: frozenset(),
    PRState.BLOCKED: frozenset(),
    PRState.FAILED: frozenset(),
}

_TERMINAL_STATES = {PRState.CLEANED, PRState.BLOCKED, PRState.FAILED}


def is_terminal(state: PRState) -> bool:
    return state in _TERMINAL_STATES


def allowed_next_states(state: PRState) -> frozenset[PRState]:
    return _TRANSITIONS.get(state, frozenset())


def transition(
    state: OrchestratorState,
    to: PRState,
    reason: str = "",
    actor: str = "orchestrator",
) -> OrchestratorState:
    """回傳套用 transition 後的新 state（immutable style；呼叫者負責 persist）。

    非法 transition 直接 raise ValueError。
    """
    allowed = _TRANSITIONS.get(state.current_state, frozenset())
    if to not in allowed:
        raise ValueError(
            f"非法 transition：{state.current_state} -> {to}，"
            f"允許：{sorted(allowed)}"
        )

    now = datetime.now(UTC).isoformat()
    t = Transition(
        from_state=state.current_state,
        to_state=to,
        at=now,
        reason=reason,
        actor=actor,
    )
    return state.model_copy(
        update={
            "current_state": to,
            "last_transition_at": now,
            "transitions": [*state.transitions, t],
        }
    )


def add_blocker(
    state: OrchestratorState,
    reason: str,
    suggested_action: str = "",
) -> OrchestratorState:
    """記錄 blocker（不改 current_state，由呼叫者決定是否一起 transition → BLOCKED）。"""
    b = Blocker(reason=reason, suggested_action=suggested_action)
    return state.model_copy(update={"blockers": [*state.blockers, b]})

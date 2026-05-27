"""Auto-fix 迴圈：偵測 CI 失敗 → 執行 fixer → commit + push。"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

from . import log as olog
from .config import OrchestratorConfig, persist_state
from .detector import current_user, fetch_failed_check_logs, pr_by_number, pr_diff_files
from .fixers.base import FixOutcome, FixOutput
from .fixers.registry import fixers_for
from .models import FixAttempt, FixResult, OrchestratorState, PRState
from .service import add_blocker, transition


def _git(args: list[str], cwd: Path) -> str:
    r = subprocess.run(  # nosec B603 B607
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} 失敗：{r.stderr.strip()}")
    return r.stdout.strip()


def _working_tree_clean(repo_root: Path) -> bool:
    out = _git(["status", "--porcelain"], repo_root)
    return out == ""


def _commit_and_push(fixer_name: str, changed_files: list[str], repo_root: Path) -> str:
    _git(["add", *changed_files], repo_root)
    _git(["commit", "-m", f"fix(ci): auto-fix via {fixer_name}"], repo_root)
    # Always push with explicit refspec to avoid accidentally pushing to origin/main
    branch = _git(["branch", "--show-current"], repo_root)
    if not branch:
        raise RuntimeError("無法取得目前分支，拒絕 push")
    _git(["push", "origin", f"{branch}:{branch}"], repo_root)
    return _git(["rev-parse", "--short", "HEAD"], repo_root)


def run(
    state: OrchestratorState,
    cfg: OrchestratorConfig,
    repo_root: Path,
) -> OrchestratorState:
    """執行 auto-fix 迴圈，回傳更新後的 state（含 persist）。

    safety gate 1：WIP 存在時拒絕
    safety gate 2：fork PR 時拒絕（除非 allow_fork_fix=True）
    """
    # Safety gate 1 — WIP check (git failure → BLOCKED, consistent with other gates)
    try:
        tree_clean = _working_tree_clean(repo_root)
    except RuntimeError as e:
        state = add_blocker(state, f"無法執行 git status 檢查：{e}", "確認 git 可用且路徑正確")
        state = transition(state, PRState.BLOCKED, "git status failed")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "git status failed")
        return state

    if not tree_clean:
        state = add_blocker(
            state, "Working tree 有未提交變更，拒絕 auto-fix", "先 stash 或 commit WIP"
        )
        state = transition(state, PRState.BLOCKED, "WIP detected before auto-fix")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "WIP detected")
        return state

    # Safety gate 2 — fork PR check (fail-closed: API failure → BLOCKED)
    if not cfg.allow_fork_fix:
        try:
            me = current_user()
            pr_info = pr_by_number(state.pr_number)
            if pr_info.author_login and pr_info.author_login != me:
                state = add_blocker(
                    state,
                    f"Fork PR（作者：{pr_info.author_login}），auto-fix 預設拒絕",
                    "如需強制修復，設定 allow_fork_fix=true",
                )
                state = transition(state, PRState.BLOCKED, "fork PR, auto-fix refused")
                persist_state(state)
                olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "fork PR")
                return state
        except RuntimeError as e:
            # Cannot verify fork status → fail closed to protect against unintended fork pushes
            state = add_blocker(
                state,
                f"無法確認 PR 作者，拒絕 auto-fix（安全預防）：{e}",
                "確認 gh 認證後重試，或設定 allow_fork_fix=true",
            )
            state = transition(state, PRState.BLOCKED, "fork check failed")
            persist_state(state)
            olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "fork check failed")
            return state

    # Fetch PR diff files (scope limiter — only fix files in this PR)
    try:
        pr_files = pr_diff_files(state.pr_number)
    except RuntimeError as e:
        state = add_blocker(
            state, f"無法取得 PR diff 檔案：{e}", "手動確認 PR 存在並有 write access"
        )
        state = transition(state, PRState.BLOCKED, "pr diff fetch failed")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "pr diff fetch failed")
        return state

    # Fetch CI failure logs
    try:
        failures = fetch_failed_check_logs(state.pr_number)
    except RuntimeError as e:
        state = add_blocker(state, f"無法取得 CI log：{e}", "手動查看 GitHub Actions")
        state = transition(state, PRState.BLOCKED, "ci log fetch failed")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "ci log fetch failed")
        return state

    if not failures:
        state = transition(state, PRState.CI_WAIT, "no CI failures found, re-poll")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.CI_WAIT, "no failures")
        return state

    combined_log = "\n".join(f.log_text for f in failures)
    applicable_fixers = fixers_for(combined_log)
    iteration = state.fix_iteration_count + 1

    # Check iteration limit before attempting fixes (gives clearer diagnostic)
    if iteration > cfg.max_fix_iterations:
        state = add_blocker(
            state,
            f"已達 auto-fix 上限（{cfg.max_fix_iterations} 次），需人工介入",
            "手動修復 CI 失敗後 push",
        )
        state = transition(state, PRState.BLOCKED, "max fix iterations exceeded")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "max iterations")
        return state

    if not applicable_fixers:
        state = add_blocker(
            state, "CI 失敗但無對應 fixer，需人工修復", "查看 CI log 後手動 push fix"
        )
        state = transition(state, PRState.BLOCKED, "no applicable fixer")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "no fixer")
        return state

    # Run each applicable fixer; wrap each call to prevent a single crash from
    # corrupting the state machine loop
    new_attempts: list[FixAttempt] = []
    for fixer in applicable_fixers:
        try:
            fixer_output: FixOutput = fixer.run(repo_root, pr_files)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {fixer.name} 執行異常：{e}", file=sys.stderr)
            new_attempts.append(
                FixAttempt(
                    iteration=iteration,
                    fixer=fixer.name,
                    commit=None,
                    result=FixResult.failed,
                    files_changed=[],
                )
            )
            continue

        commit_sha: str | None = None
        if fixer_output.outcome == FixOutcome.applied:
            try:
                commit_sha = _commit_and_push(fixer.name, fixer_output.files_changed, repo_root)
                print(f"[auto-fix] {fixer.name} applied, commit: {commit_sha}")
            except RuntimeError as e:
                print(f"[WARN] {fixer.name} commit/push 失敗：{e}", file=sys.stderr)

        new_attempts.append(
            FixAttempt(
                iteration=iteration,
                fixer=fixer.name,
                commit=commit_sha,
                result=FixResult(fixer_output.outcome.value),
                files_changed=fixer_output.files_changed,
            )
        )

    state = state.model_copy(update={"fix_attempts": [*state.fix_attempts, *new_attempts]})

    # Only advance to CI_WAIT if at least one fixer actually applied a change;
    # all-crashed → BLOCKED to prevent a silent re-poll spin
    applied_any = any(a.result == FixResult.applied for a in new_attempts)
    if not applied_any:
        state = add_blocker(
            state, "所有 fixer 均執行失敗，請查看 stderr 後手動修復", "手動修復後 push 再 resume"
        )
        state = transition(state, PRState.BLOCKED, "all fixers failed or no-change")
        persist_state(state)
        olog.append(state.pr_number, PRState.AUTO_FIX, PRState.BLOCKED, "all fixers failed")
        return state

    state = transition(state, PRState.CI_WAIT, f"iteration {iteration} applied, re-poll CI")
    persist_state(state)
    olog.append(state.pr_number, PRState.AUTO_FIX, PRState.CI_WAIT, f"iteration {iteration}")
    return state

"""CLI 入口：PR Orchestrator。"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys

import click

from . import log as olog
from .config import (
    archive_state,
    find_latest_state,
    load_config,
    persist_state,
    state_path,
)
from .models import OrchestratorState, PRState


def _load_state(pr_number: int) -> OrchestratorState:
    """state file を讀取並 validate；失敗時 raise RuntimeError。"""
    p = state_path(pr_number)
    if not p.is_file():
        raise RuntimeError(f"找不到 PR #{pr_number} state 檔：{p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"PR #{pr_number} state 檔損壞（{e}），請刪除 {p} 後重新執行 detect"
        ) from e
    return OrchestratorState.model_validate(data)


@click.group()
def cli() -> None:
    """PR Lifecycle Orchestrator — 自動化 PR 審查、CI 修復、retro 與清理。"""


@cli.command()
@click.option("--pr", "pr_number", default=None, type=int, help="PR 號碼（留空時自動偵測）")
@click.option("--branch", default=None, help="分支名稱（留空時從 git 讀取）")
def detect(pr_number: int | None, branch: str | None) -> None:
    """偵測目前分支的 open PR，建立初始 state file。"""
    from .detector import current_branch, pr_by_number, pr_for_branch

    if branch is None:
        try:
            branch = current_branch()
        except RuntimeError as e:
            click.echo(f"[FAIL] {e}", err=True)
            raise SystemExit(1) from None

    if pr_number is not None:
        try:
            pr_info = pr_by_number(pr_number)
        except RuntimeError as e:
            click.echo(f"[FAIL] {e}", err=True)
            raise SystemExit(1) from None
    else:
        try:
            pr_info = pr_for_branch(branch)
        except RuntimeError as e:
            click.echo(f"[FAIL] {e}", err=True)
            raise SystemExit(1) from None

    existing = state_path(pr_info.number)
    if existing.is_file():
        try:
            data = json.loads(existing.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            click.echo(f"[FAIL] 現有 state 檔損壞（{e}），請刪除 {existing} 後重新執行", err=True)
            raise SystemExit(1) from None
        click.echo(f"PR #{pr_info.number} 已有 state：{data.get('current_state')}（跳過初始化）")
        return

    # Resolve repo slug (best-effort — failure is non-fatal)
    repo = ""
    try:
        r = subprocess.run(  # nosec B603 B607
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        repo = r.stdout.strip()
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[WARN] 無法取得 repo slug（將使用 'unknown'）：{e}", file=sys.stderr)

    state = OrchestratorState(
        pr_number=pr_info.number,
        branch=pr_info.head_ref_name,
        head_sha=pr_info.head_ref_oid,
        base_branch=pr_info.base_ref_name,
        repo=repo,
    )
    persist_state(state)
    olog.append(pr_info.number, "INIT", PRState.DETECTED, "initial detection")
    click.echo(f"[ok] PR #{pr_info.number} state 已建立：{state_path(pr_info.number)}")


@cli.command(name="write-manifest")
@click.option("--pr", "pr_number", required=True, type=int)
def write_manifest(pr_number: int) -> None:
    """為 REVIEWING 狀態寫出 spawn-manifest.md，並更新 artifacts.spawn_manifest。"""
    from .dispatcher import write_review_manifest

    try:
        state = _load_state(pr_number)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    manifest_p = write_review_manifest(state)
    state = state.model_copy(
        update={"artifacts": state.artifacts.model_copy(update={"spawn_manifest": str(manifest_p)})}
    )
    persist_state(state)
    click.echo(f"[ok] spawn-manifest 已寫出：{manifest_p}")


@cli.command(name="auto-fix")
@click.option("--pr", "pr_number", required=True, type=int)
@click.option("--repo-root", "repo_root_str", default=None, help="repo 根目錄（留空用 cwd）")
def auto_fix_cmd(pr_number: int, repo_root_str: str | None) -> None:
    """執行 auto-fix 迴圈（CI 失敗偵測 → fixer → commit/push）。"""
    import os
    from pathlib import Path as _Path

    from .auto_fix import run as run_auto_fix

    try:
        state = _load_state(pr_number)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    cfg = load_config()
    repo_root = _Path(repo_root_str) if repo_root_str else _Path(os.getcwd())
    state = run_auto_fix(state, cfg, repo_root)
    click.echo(f"[ok] auto-fix 完成，當前狀態：{state.current_state}")


@cli.command()
@click.option("--pr", "pr_number", required=True, type=int)
@click.option("--to", "to_state", required=True, type=click.Choice([s.value for s in PRState]))
@click.option("--reason", default="", help="transition 原因說明")
def transition(pr_number: int, to_state: str, reason: str) -> None:
    """手動觸發 state transition（供 skill 在動作完成後呼叫）。

    transitioning to CLEANED 同時觸發 state 歸檔至 ~/.claude/pr_orchestrator/<repo>/
    """
    from .service import transition as svc_transition

    try:
        state = _load_state(pr_number)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    to = PRState(to_state)
    try:
        state = svc_transition(state, to, reason=reason)
    except ValueError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    try:
        persist_state(state)
    except RuntimeError as e:
        click.echo(f"[FAIL] State 儲存失敗：{e}", err=True)
        raise SystemExit(1) from None

    t = state.transitions[-1]
    olog.append(pr_number, t.from_state, to_state, reason)
    click.echo(f"[ok] PR #{pr_number}: {t.from_state} -> {to_state}")

    if to == PRState.CLEANED:
        archive_state(state)


@cli.command()
@click.option("--pr", "pr_number", default=None, type=int)
def status(pr_number: int | None) -> None:
    """顯示 PR state 資訊。"""
    if pr_number is None:
        pr_number = find_latest_state()
        if pr_number is None:
            click.echo("找不到任何 active state 檔。")
            raise SystemExit(1)

    try:
        state = _load_state(pr_number)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    click.echo(json.dumps(state.model_dump(), indent=2, ensure_ascii=False))


@cli.command()
@click.option("--pr", "pr_number", default=None, type=int, help="PR 號碼（留空抓最新）")
def resume(pr_number: int | None) -> None:
    """顯示 resume 指引：讀取 state 並告訴 skill 該從哪裡繼續。"""
    if pr_number is None:
        pr_number = find_latest_state()
        if pr_number is None:
            click.echo("[FAIL] 找不到任何 active state 檔，請先執行 detect", err=True)
            raise SystemExit(1)

    try:
        state = _load_state(pr_number)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    click.echo(f"PR #{pr_number} 當前狀態：{state.current_state}")
    click.echo(f"最後 transition：{state.last_transition_at}")
    if state.blockers:
        click.echo("\nBlockers：")
        for b in state.blockers:
            click.echo(f"  - {b.reason}")
            if b.suggested_action:
                click.echo(f"    建議動作：{b.suggested_action}")

    # Routing hint to help the skill know what to do next
    next_cmd = _next_command_hint(state)
    if next_cmd:
        click.echo(f"\n下一步：{next_cmd}")


def _next_command_hint(state: OrchestratorState) -> str:
    """根據 current_state 回傳 skill 應執行的下一個 CLI 指令提示。"""
    pr = state.pr_number
    mapping = {
        PRState.DETECTED: f"transition --pr {pr} --to REVIEWING",
        PRState.REVIEWING: (
            f"write-manifest --pr {pr}  "
            "(然後 dispatch subagents，完成後 transition --to REVIEW_DONE)"
        ),
        PRState.REVIEW_DONE: f"transition --pr {pr} --to CI_WAIT",
        PRState.CI_WAIT: f"(等待 CI) → 失敗時 transition --pr {pr} --to AUTO_FIX",
        PRState.AUTO_FIX: f"auto-fix --pr {pr}",
        PRState.CI_PASS: f"transition --pr {pr} --to MERGEABLE",
        PRState.CONFLICT: f"（手動解 conflict 後）transition --pr {pr} --to BLOCKED",
        PRState.MERGEABLE: (
            f"（user 確認後 gh pr merge --squash）→ transition --pr {pr} --to MERGED"
        ),
        PRState.MERGED: f"transition --pr {pr} --to RETRO_DONE  (完成 /pr-retro 後)",
        PRState.RETRO_DONE: f"transition --pr {pr} --to CLEANED",
        PRState.BLOCKED: f"（排除 blocker 後）transition --pr {pr} --to DETECTED",
        PRState.CLEANED: "（已完成）",
        PRState.FAILED: "（terminal — 需人工調查）",
    }
    return mapping.get(state.current_state, "")


@cli.command()
@click.option("--pr", "pr_number", default=None, type=int)
def log_view(pr_number: int | None) -> None:
    """顯示 transition log。"""
    if pr_number is None:
        pr_number = find_latest_state()
        if pr_number is None:
            click.echo("[FAIL] 找不到任何 active state 檔", err=True)
            raise SystemExit(1)

    entries = olog.read(pr_number)
    if not entries:
        click.echo(f"PR #{pr_number} 尚無 log。")
        return

    for e in entries:
        ts = e["ts"]
        frm = e.get("from", "?")
        to = e.get("to", "?")
        reason = e.get("reason", "")
        click.echo(f"{ts}  {frm:14} -> {to:14}  {reason}")


@cli.command()
@click.option("--pr", "pr_number", required=True, type=int)
@click.option("--dry-run", is_flag=True, help="只列出要刪除的檔案，不實際刪除")
def gc(pr_number: int, dry_run: bool) -> None:
    """清理已完成 PR 的 .runtime 暫存資料。"""
    p = state_path(pr_number)
    if not p.is_file():
        click.echo(f"PR #{pr_number} 無 active state，略過。")
        return

    try:
        state = _load_state(pr_number)
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    if state.current_state not in {PRState.CLEANED, PRState.FAILED}:
        click.echo(f"PR #{pr_number} 狀態為 {state.current_state}，尚未完成，略過。")
        return

    manifest = p.parent / str(pr_number)
    # Collect files under manifest dir, plus the state file and log
    manifest_files = sorted(manifest.rglob("*"), reverse=True) if manifest.is_dir() else []
    targets = [p, olog.log_path(pr_number)] + list(manifest_files)

    for t in targets:
        if t.is_file():
            if dry_run:
                click.echo(f"[dry-run] 刪除：{t}")
            else:
                t.unlink()

    # Remove manifest directory after all files inside are deleted
    if not dry_run and manifest.is_dir():
        import contextlib

        with contextlib.suppress(OSError):
            manifest.rmdir()

    if not dry_run:
        click.echo(f"PR #{pr_number} runtime 資料已清除。")

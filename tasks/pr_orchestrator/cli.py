"""CLI 入口：PR Orchestrator。"""

from __future__ import annotations

import json

import click

from . import log as olog
from .config import (
    archive_state,
    find_latest_state,
    persist_state,
    state_path,
)
from .models import OrchestratorState, PRState


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
        data = json.loads(existing.read_text(encoding="utf-8"))
        click.echo(f"PR #{pr_info.number} 已有 state：{data.get('current_state')}（跳過初始化）")
        return

    # Resolve repo slug (best-effort)
    repo = ""
    try:
        import subprocess  # nosec B404
        r = subprocess.run(  # nosec B603 B607
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True, text=True, timeout=10,
        )
        repo = r.stdout.strip()
    except Exception:
        pass

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


@cli.command()
@click.option("--pr", "pr_number", required=True, type=int)
@click.option("--to", "to_state", required=True, type=click.Choice([s.value for s in PRState]))
@click.option("--reason", default="", help="transition 原因說明")
def transition(pr_number: int, to_state: str, reason: str) -> None:
    """手動觸發 state transition（供 skill 在動作完成後呼叫）。"""
    from .service import transition as svc_transition

    p = state_path(pr_number)
    if not p.is_file():
        click.echo(f"[FAIL] 找不到 PR #{pr_number} state 檔", err=True)
        raise SystemExit(1)

    state = OrchestratorState.model_validate(json.loads(p.read_text(encoding="utf-8")))
    to = PRState(to_state)
    try:
        state = svc_transition(state, to, reason=reason)
    except ValueError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from None

    persist_state(state)
    olog.append(pr_number, state.transitions[-1].from_state, to_state, reason)
    click.echo(f"[ok] PR #{pr_number}: {state.transitions[-1].from_state} -> {to_state}")

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

    p = state_path(pr_number)
    if not p.is_file():
        click.echo(f"[FAIL] 找不到 PR #{pr_number} state 檔", err=True)
        raise SystemExit(1)

    data = json.loads(p.read_text(encoding="utf-8"))
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


@cli.command()
@click.option("--pr", "pr_number", default=None, type=int, help="PR 號碼（留空抓最新）")
def resume(pr_number: int | None) -> None:
    """顯示 resume 指引：讀取 state 並告訴 skill 該從哪裡繼續。"""
    if pr_number is None:
        pr_number = find_latest_state()
        if pr_number is None:
            click.echo("[FAIL] 找不到任何 active state 檔，請先執行 detect", err=True)
            raise SystemExit(1)

    p = state_path(pr_number)
    if not p.is_file():
        click.echo(f"[FAIL] 找不到 PR #{pr_number} state 檔", err=True)
        raise SystemExit(1)

    state = OrchestratorState.model_validate(json.loads(p.read_text(encoding="utf-8")))
    click.echo(f"PR #{pr_number} 當前狀態：{state.current_state}")
    click.echo(f"最後 transition：{state.last_transition_at}")
    if state.blockers:
        click.echo("\nBlockers：")
        for b in state.blockers:
            click.echo(f"  - {b.reason}")
            if b.suggested_action:
                click.echo(f"    建議動作：{b.suggested_action}")


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

    state = OrchestratorState.model_validate(json.loads(p.read_text(encoding="utf-8")))
    if state.current_state not in {PRState.CLEANED, PRState.FAILED}:
        click.echo(f"PR #{pr_number} 狀態為 {state.current_state}，尚未完成，略過。")
        return

    manifest = p.parent / str(pr_number)
    manifest_files = list(manifest.rglob("*")) + [manifest] if manifest.is_dir() else []
    targets = [p, olog.log_path(pr_number)] + manifest_files
    for t in targets:
        if t.is_file():
            if dry_run:
                click.echo(f"[dry-run] 刪除：{t}")
            else:
                t.unlink()
    if not dry_run:
        click.echo(f"PR #{pr_number} runtime 資料已清除。")

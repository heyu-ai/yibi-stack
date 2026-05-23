"""CLI 入口：bash-hygiene audit log 分析工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from .models import AuditConfig

_DISPLAY_COLS = 80


@click.group()
def cli() -> None:
    """bash-hygiene audit log 管理與分析。"""


def _load_or_exit() -> AuditConfig:
    from .config import load_config

    try:
        return load_config()
    except RuntimeError as e:
        click.echo(f"[FAIL] {e}", err=True)
        raise SystemExit(1) from e


@cli.command()
def enable() -> None:
    """啟用 audit log 記錄（設定 audit_enabled=true）。"""
    from .config import save_config

    config = _load_or_exit()
    config.audit_enabled = True
    save_config(config)
    click.echo("[OK] audit log 已啟用。")
    click.echo("Hook 執行結果將記錄至 .runtime/logs/bash-hygiene-audit.jsonl")


@cli.command()
def disable() -> None:
    """停用 audit log 記錄（設定 audit_enabled=false）。"""
    from .config import save_config

    config = _load_or_exit()
    config.audit_enabled = False
    save_config(config)
    click.echo("[OK] audit log 已停用。")


@cli.command()
def status() -> None:
    """顯示 audit log 目前狀態（toggle + log 檔路徑 + 記錄數）。"""
    from .config import config_path
    from .service import count_log_lines, log_path

    config = _load_or_exit()
    state = "[ON]" if config.audit_enabled else "[OFF]"
    click.echo(f"audit log：{state}")
    click.echo(f"config 路徑：{config_path()}")

    path = log_path()
    if path and path.is_file():
        click.echo(f"log 路徑：{path}")
        click.echo(f"記錄筆數：{count_log_lines()}")
    else:
        click.echo("log 路徑：（尚無記錄）")


@cli.command()
@click.option("--last", default=20, help="顯示最近 N 筆（預設 20）")
@click.option("--hook", default=None, help="只顯示指定 hook（ap1 / ap2 / smart-fix）")
@click.option("--verdict", default=None, help="只顯示指定 verdict（allow / block）")
def show(last: int, hook: str | None, verdict: str | None) -> None:
    """顯示最近 N 筆 audit log 記錄。"""
    from .service import read_log

    records = read_log(last=last, hook=hook, verdict=verdict)
    if not records:
        click.echo("（無記錄）")
        return
    for r in records:
        icon = {"block": "[BLOCK]", "allow": "[ALLOW]"}.get(str(r.verdict), "[ERROR]")
        reason = f"  reason={r.block_reason}" if r.block_reason else ""
        dur = f"  {r.duration_ms}ms" if r.duration_ms is not None else ""
        click.echo(f"{r.ts}  {icon}  hook={r.hook}{reason}{dur}")
        if r.cmd_snippet:
            preview = r.cmd_snippet[:_DISPLAY_COLS].replace("\n", " ")
            click.echo(f"  cmd: {preview}")


@cli.command()
def stats() -> None:
    """顯示 audit log 聚合統計（block 比例、最常觸發的 hook 與 reason）。"""
    from .service import compute_stats, read_log

    records = read_log(last=99999)
    if not records:
        click.echo("（無記錄）")
        return
    s = compute_stats(records)
    block_pct = (s.block_count / s.total * 100) if s.total else 0
    click.echo(
        f"總計：{s.total} 筆  block：{s.block_count}（{block_pct:.1f}%）  allow：{s.allow_count}"
    )
    if s.avg_duration_ms is not None:
        click.echo(f"平均耗時：{s.avg_duration_ms:.1f}ms")
    if s.by_hook:
        click.echo("--- by hook ---")
        for hook, cnt in sorted(s.by_hook.items(), key=lambda x: -x[1]):
            click.echo(f"  {hook}: {cnt}")
    if s.by_reason:
        click.echo("--- by block_reason ---")
        for reason, cnt in sorted(s.by_reason.items(), key=lambda x: -x[1]):
            click.echo(f"  {reason}: {cnt}")

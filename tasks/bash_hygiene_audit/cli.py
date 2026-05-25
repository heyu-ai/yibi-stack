"""CLI 入口：bash-hygiene audit log 分析工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from .models import AuditConfig, RepeatStats

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


def _print_repeat_stats(s: RepeatStats) -> None:  # noqa: F821
    """重用的重複攔截報告輸出（audit log 與 transcript 路徑共用）。"""
    if s.total_blocks == 0:
        click.echo("（無 block 記錄）")
        return
    if s.unique_repeat_events == 0:
        click.echo(f"總 block 次數：{s.total_blocks}")
        click.echo("（無重複攔截）")
        return
    repeat_pct = s.repeat_rate * 100
    click.echo(f"總 block 次數：{s.total_blocks}")
    click.echo(f"重複攔截次數：{s.repeated_blocks}（{repeat_pct:.1f}%）")
    click.echo(f"重複事件組數：{s.unique_repeat_events}")
    wasted_sec = s.total_wasted_ms / 1000
    click.echo(f"累積浪費時間：{wasted_sec:.1f} 秒")
    click.echo(f"累積浪費 token：~{s.total_wasted_tokens:,} tokens")
    if s.top_offenders:
        click.echo("--- top 重複攔截熱點 ---")
        for i, e in enumerate(s.top_offenders, 1):
            sec = e.estimated_wasted_ms / 1000
            cmd_preview = e.command_preview.replace("\n", " ")[:60]
            click.echo(
                f"  {i}. [{e.count}x] {e.block_reason or 'unknown'}"
                f"  +{sec:.1f}s  ~{e.estimated_wasted_tokens:,}tk"
            )
            click.echo(f"     cmd: {cmd_preview}")
    if s.by_reason:
        click.echo("--- by block_reason ---")
        for reason, cnt in sorted(s.by_reason.items(), key=lambda x: -x[1]):
            click.echo(f"  {reason}: {cnt}")


@cli.command()
@click.option("--top", "-n", default=5, help="顯示前 N 名重複攔截熱點（預設 5）")
@click.option(
    "--token-estimate",
    default=1500,
    help="每次額外 block 估算的 token 浪費（預設 1500）",
)
def repeats(top: int, token_estimate: int) -> None:
    """分析 hook 重複攔截：同 session 同 hash 被 block >= 2 次的次數與累積浪費。"""
    from .service import compute_repeats, read_log

    records = read_log(last=99999)
    if not records:
        click.echo("（無記錄）")
        return
    s = compute_repeats(records, top_n=top, token_per_repeat_estimate=token_estimate)
    _print_repeat_stats(s)


@cli.command(name="replay-transcripts")
@click.option("--since-days", default=14, help="回溯天數（預設 14）")
@click.option("--top", "-n", default=5, help="顯示前 N 名重複攔截熱點（預設 5）")
@click.option(
    "--token-estimate",
    default=1500,
    help="每次額外 block 估算的 token 浪費（預設 1500）",
)
@click.option("--project-slug", default=None, help="指定 project slug（預設自動偵測）")
def replay_transcripts(
    since_days: int, top: int, token_estimate: int, project_slug: str | None
) -> None:
    """從 Claude Code session transcript 回溯 hook block 事件並分析重複攔截。"""
    import subprocess  # nosec B404

    from .service import compute_repeats
    from .transcript import scan_project_transcripts, transcripts_to_audit_records

    if project_slug is None:
        try:
            import re

            # 用 --git-common-dir 確保在 linked worktree 裡也能找到主 repo 路徑
            result = subprocess.run(  # nosec B603 B607
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                click.echo("[FAIL] 無法偵測 git repo 路徑", err=True)
                raise SystemExit(1)
            from pathlib import Path as _Path

            repo_path = str(_Path(result.stdout.strip()).parent)
            # 把 /Users/howie/Workspace/... 轉成 -Users-howie-Workspace-...
            # leading "/" 轉成 leading "-"，不要 lstrip
            project_slug = re.sub(r"[/\\]", "-", repo_path)
        except Exception as exc:
            click.echo(f"[FAIL] 無法取得 project slug：{exc}", err=True)
            raise SystemExit(1) from exc

    click.echo(f"掃描 project：{project_slug}（最近 {since_days} 天）")
    try:
        events = scan_project_transcripts(project_slug=project_slug, since_days=since_days)
    except RuntimeError as exc:
        click.echo(f"[FAIL] {exc}", err=True)
        raise SystemExit(1) from exc

    if not events:
        click.echo("（找不到 hook block 事件）")
        return

    click.echo(f"找到 hook block 事件：{len(events)} 筆")
    records = transcripts_to_audit_records(events)
    s = compute_repeats(records, top_n=top, token_per_repeat_estimate=token_estimate)
    _print_repeat_stats(s)

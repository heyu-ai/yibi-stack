"""CLI 入口：harness 就緒度評量。"""

from pathlib import Path

import click


@click.group()
def cli() -> None:
    """Claude Code harness 就緒度評量工具。"""


@cli.command()
@click.option("--target-dir", "-t", default=None, help="掃描目標 repo（預設 $PWD）")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "text"]),
    default="json",
    help="輸出格式",
)
def scan(target_dir: str | None, output_format: str) -> None:
    """掃描 repo 的 Claude Code harness 就緒度。"""
    from .service import run_scan

    target = Path(target_dir) if target_dir else Path.cwd()
    if not target.exists():
        click.echo(f"[FAIL] target 路徑不存在：{target}", err=True)
        raise SystemExit(1)

    try:
        result = run_scan(target)
    except Exception as e:
        click.echo(f"[FAIL] 掃描失敗：{e}", err=True)
        raise SystemExit(1) from e

    if output_format == "json":
        click.echo(result.model_dump_json(indent=2))
    else:
        click.echo(f"Harness Eval -- {target}")
        click.echo(f"Mech score: {result.total_mechanical} / {result.total_mechanical_max}")
        click.echo()
        for dim in result.dimensions:
            pct = dim.score / dim.max_score if dim.max_score else 0
            status = "OK" if pct >= 0.8 else "WARN" if pct > 0 else "FAIL"
            click.echo(f"[{status}] {dim.dimension} {dim.label}: {dim.score}/{dim.max_score}")
            for finding in dim.findings:
                click.echo(f"       {finding}")

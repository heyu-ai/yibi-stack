---
paths:
  - "tasks/**/cli.py"
---
# Click CLI Pattern

## Basic Structure

```python
"""CLI 入口：<模組中文描述>。"""

import click


@click.group()
def cli() -> None:
    """<模組中文一行說明>。"""


@cli.command()
@click.option("--profile", "-p", required=True, help="Profile 名稱")
@click.option("--days", default=7, help="掃描天數")
def scan(profile: str, days: int) -> None:
    """執行 Gmail 掃描。"""
    from .service import run_scan  # deferred import
    ...
```

## Output Rules

- Use `click.echo()`, not `print()`
- Use `click.prompt()` and `click.confirm()` for interactive input
- Use `raise SystemExit(1)` for error exit (not `sys.exit(1)`)

```python
click.echo(f"✓ 掃描完成，共 {count} 筆")
click.echo(f"✗ 發生錯誤：{e}", err=True)
raise SystemExit(1)
```

## Deferred Imports

Import service, config, and db modules inside command function bodies:

```python
@cli.command()
def import_data() -> None:
    from .service import run_pipeline  # import here, not at top level
    from .config import load_config
    config = load_config()
    run_pipeline(config)
```

## Help Text Language

All `help=` parameters and group/command docstrings use Traditional Chinese.

## How to Run

```bash
uv run python -m tasks.<module> <command> [options]
```

## Subcommand Dead Code Trap

Writing a service function is not enough — the subcommand must also be registered on the
CLI group with `@cli.command()`. Forgetting the decorator means the subcommand never appears
in `--help` and is silently uncallable.

Always verify after implementation:

```bash
uv run python -m tasks.<module> --help   # confirm new subcommand appears in the list
```

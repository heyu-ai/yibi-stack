---
globs: tasks/**/cli.py
---
# Click CLI 規範

## 基本結構

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
    from .service import run_scan  # 延遲 import
    ...
```

## 輸出規範

- 用 `click.echo()`，不用 `print()`
- 互動輸入用 `click.prompt()` 和 `click.confirm()`
- 錯誤退出用 `raise SystemExit(1)`（不用 `sys.exit(1)`）

```python
click.echo(f"✓ 掃描完成，共 {count} 筆")
click.echo(f"✗ 發生錯誤：{e}", err=True)
raise SystemExit(1)
```

## Import 延遲

Service、config、db 等模組的 import 放在 command function body 內：

```python
@cli.command()
def import_data() -> None:
    from .service import run_pipeline  # 在這裡 import，不在頂層
    from .config import load_config
    config = load_config()
    run_pipeline(config)
```

## Help Text 語言

所有 `help=` 參數、group/command docstring 用中文。

## 執行方式

```bash
uv run python -m tasks.<module> <command> [options]
```

---
name: new-task-module
type: exec
scope: project
description: 根據 04-module-structure.md 規範，自動建立新 task module 的完整骨架（7 個檔案）。觸發關鍵字：新增 task、建立 module、new task module、新增功能模組
---

# 新增 Task Module

## 概要

依照 `tasks/<module_name>/` 標準結構，自動建立 7 個骨架檔案並更新 `skills/README.md` 索引。

## 執行步驟

### Step 1：確認參數

向使用者確認以下參數：

- **module_name**（snake_case）：`{{module_name}}`，例如 `saas_expense`
- **skill_name**（kebab-case）：`{{skill_name}}`，例如 `saas-expense`
- **中文描述**：`{{description}}`，例如 `SaaS 訂閱費用分析`

### Step 2：建立目錄結構

```bash
mkdir -p tasks/{{module_name}}/tests
touch tasks/{{module_name}}/tests/__init__.py
```

### Step 3：建立 7 個骨架檔案

依序建立以下檔案，內容照規範格式：

**`tasks/{{module_name}}/__init__.py`**

```python
"""{{description}}。"""
```

**`tasks/{{module_name}}/__main__.py`**

```python
from .cli import cli

cli()
```

**`tasks/{{module_name}}/models.py`**

```python
"""{{description}} 資料模型。"""

from pydantic import BaseModel, Field


class {{ModuleName}}Config(BaseModel):
    version: str = "1.0"
```

**`tasks/{{module_name}}/config.py`**

```python
"""{{description}} 設定載入。"""

import json
from pathlib import Path

import click

from tasks._paths import RUNTIME_DIR

DEFAULT_CONFIG_PATH = RUNTIME_DIR / "{{module_name}}.json"


def load_config(path: Path | None = None) -> "{{ModuleName}}Config":
    from .models import {{ModuleName}}Config
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        click.echo(f"找不到設定檔：{config_path}")
        click.echo("請先執行：uv run python -m tasks.{{module_name}} setup")
        raise SystemExit(1)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return {{ModuleName}}Config.model_validate(data)
```

**`tasks/{{module_name}}/service.py`**

```python
"""{{description}} 核心業務邏輯。"""
```

**`tasks/{{module_name}}/cli.py`**

```python
"""CLI 入口：{{description}}。"""

import click


@click.group()
def cli() -> None:
    """{{description}}。"""


@cli.command()
def setup() -> None:
    """建立預設設定檔。"""
    click.echo("✓ 設定檔已建立")
```

**`tasks/{{module_name}}/tests/test_models.py`**

```python
"""{{description}} 模型測試。"""

from tasks.{{module_name}}.models import {{ModuleName}}Config


class Test{{ModuleName}}Config:
    def test_default_version(self) -> None:
        config = {{ModuleName}}Config()
        assert config.version == "1.0"
```

### Step 4：建立 skill 介面

```bash
mkdir -p skills/{{skill_name}}
```

建立 `skills/{{skill_name}}/SKILL.md`，使用 `skills/_template/SKILL.md.tpl` 為基礎。

### Step 5：更新索引

在 `skills/README.md`「本 Repo 限定 Skill」表格（欄位：Skill｜類型｜描述｜SKILL.md｜相依工具）新增一行：

```markdown
| `{{skill_name}}` | exec | {{description}} | [{{skill_name}}/SKILL.md]({{skill_name}}/SKILL.md) | `uv` |
```

## 常見問題

| 問題 | 解法 |
|------|------|
| 忘記 `__main__.py` 格式 | 只允許 2 行：`from .cli import cli` + `cli()` |
| model 欄位用 `Optional` | 改用 `str \| None = None`（Python 3.10+ 語法） |
| list 欄位直接賦值 `[]` | 改用 `Field(default_factory=list)` |

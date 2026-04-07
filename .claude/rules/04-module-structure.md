---
globs: tasks/**
---
# Task Module 結構規範

## 必備檔案

每個 task module（`tasks/<module_name>/`）必須包含：

```text
tasks/<module_name>/
├── __init__.py      # 只有一行中文 docstring
├── __main__.py      # 只有 2 行：import cli + 呼叫
├── cli.py           # Click CLI entry point
├── config.py        # 設定載入/儲存
├── models.py        # Pydantic 資料模型
├── service.py       # 核心業務邏輯
└── tests/
    ├── __init__.py
    └── test_*.py
```

選用檔案（視需求加入）：

- `db.py` — SQLite 資料庫層
- `parsers/` — 可擴充解析器（abstract base + registry）

## `__init__.py` 格式

```python
"""<模組中文一行說明>。"""
```

## `__main__.py` 格式

```python
from .cli import cli

cli()
```

只允許這 2 行，不得加入任何業務邏輯。

## 命名規範

| 層級 | 格式 | 範例 |
|------|------|------|
| `tasks/` 子目錄 | snake_case | `gmail_billing` |
| `skills/` 子目錄 | kebab-case | `gmail-billing` |
| `__main__.py` 執行 | `uv run python -m tasks.<module>` | `tasks.gmail_billing` |

## 共用路徑工具

從 `tasks._paths` import，不要自行計算路徑：

```python
from tasks._paths import PROJECT_ROOT, RUNTIME_DIR
```

## 開發者文件

`tasks/<module>/skill.md`（小寫）是開發者參考文件。
`skills/<name>/SKILL.md`（大寫）是 agent 執行介面。
兩者目的不同，不要混淆。

---
globs: tasks/**
---
# Task Module Structure

## Required Files

Each task module (`tasks/<module_name>/`) must contain:

```text
tasks/<module_name>/
├── __init__.py      # one-line docstring only
├── __main__.py      # exactly 2 lines: import cli + call
├── cli.py           # Click CLI entry point
├── config.py        # config load/save
├── models.py        # Pydantic data models
├── service.py       # core business logic
└── tests/
    ├── __init__.py
    └── test_*.py
```

Optional files (add as needed):

- `db.py` — SQLite database layer
- `parsers/` — extensible parsers (abstract base + registry)

## `__init__.py` Format

```python
"""One-line module description in Traditional Chinese."""
```

## `__main__.py` Format

```python
from .cli import cli

cli()
```

Only these 2 lines are allowed; do not add any business logic.

## Naming Conventions

| Layer | Format | Example |
|-------|--------|---------|
| `tasks/` subdirectory | snake_case | `gmail_billing` |
| `skills/` subdirectory | kebab-case | `gmail-billing` |
| `__main__.py` invocation | `uv run python -m tasks.<module>` | `tasks.gmail_billing` |

## Shared Path Utilities

Import from `tasks._paths`; do not compute paths manually:

```python
from tasks._paths import PROJECT_ROOT, RUNTIME_DIR
```

## Developer Documentation

`tasks/<module>/skill.md` (lowercase) is the developer reference.
`skills/<name>/SKILL.md` (uppercase) is the agent execution interface.
They serve different purposes; do not confuse them.

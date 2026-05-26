---
globs: tasks/**/models.py
---
# Pydantic Models

## Core Principles

- Use Pydantic v2 `BaseModel` for data models
- Parser internal data (`ParsedRow`, `ParseResult`) use `@dataclass` (lightweight, not serialized to JSON)
- Config root models (e.g. `BillingConfig`) include a `version: str = "1.0"` field

## Enum Types

Always use `StrEnum`; serializes as a string:

```python
from enum import StrEnum

class JobType(StrEnum):
    COMMAND = "command"
    CLAUDE = "claude"
    SKILL = "skill"
```

Do not use `Enum` (requires manual `.value`) or `IntEnum` (not JSON-friendly).

## Type Hint Syntax

Use Python 3.10+ union syntax:

```python
# Correct
profile_id: str | None = None
tags: list[str] = Field(default_factory=list)

# Wrong
profile_id: Optional[str] = None
```

## Mutable Defaults

All list/dict fields use `Field(default_factory=...)`:

```python
class ScanProfile(BaseModel):
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
```

## Validators

- Use `@field_validator` for field validation
- Use `@model_validator(mode="after")` for cross-field validation
- Error messages in validators use Traditional Chinese

```python
@field_validator("scan_days")
@classmethod
def check_positive(cls, v: int) -> int:
    if v <= 0:
        raise ValueError("scan_days 必須為正整數")
    return v
```

## Serialization

Use `model_dump_json(indent=2)` for JSON output; do not use `json.dumps(model.dict())` (v1 syntax).

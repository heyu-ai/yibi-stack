---
globs: tasks/**/models.py
---
# Pydantic Models 規範

## 基本原則

- 資料模型用 Pydantic v2 `BaseModel`
- Parser 內部資料（`ParsedRow`、`ParseResult`）用 `dataclass`（輕量、不序列化到 JSON）
- Config root model（如 `BillingConfig`）加入 `version: str = "1.0"` 欄位

## Enum 類型

一律使用 `StrEnum`，序列化後為字串：

```python
from enum import StrEnum

class JobType(StrEnum):
    COMMAND = "command"
    CLAUDE = "claude"
    SKILL = "skill"
```

不使用 `Enum`（需手動 `.value`）或 `IntEnum`（JSON 不友善）。

## Type Hint 語法

用 Python 3.10+ 的 union 語法：

```python
# 正確
profile_id: str | None = None
tags: list[str] = Field(default_factory=list)

# 錯誤
profile_id: Optional[str] = None
```

## Mutable Defaults

所有 list/dict 欄位使用 `Field(default_factory=...)`：

```python
class ScanProfile(BaseModel):
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
```

## Validators

- 欄位驗證用 `@field_validator`
- 跨欄位驗證用 `@model_validator(mode="after")`
- validator 中的錯誤訊息用中文

```python
@field_validator("scan_days")
@classmethod
def check_positive(cls, v: int) -> int:
    if v <= 0:
        raise ValueError("scan_days 必須為正整數")
    return v
```

## 序列化

輸出 JSON 用 `model_dump_json(indent=2)`，不用 `json.dumps(model.dict())`（v1 語法）。

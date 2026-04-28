"""本地 Port 分配登錄系統的資料模型。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Category(StrEnum):
    """服務類別。"""

    DB = "db"
    CACHE = "cache"
    BACKEND = "backend"
    FRONTEND = "frontend"
    QUEUE = "queue"
    OTHER = "other"


class PortEntry(BaseModel):
    """單一服務的 port 登記記錄。"""

    project: str
    service: str
    category: Category
    port: int
    note: str = ""
    registered_at: datetime


class PortRegistry(BaseModel):
    """機器層 port 分配登錄表。"""

    version: str = "1.0"
    ranges: dict[str, list[int]]
    entries: list[PortEntry] = Field(default_factory=list)

    @field_validator("ranges")
    @classmethod
    def check_range_shape(cls, v: dict[str, list[int]]) -> dict[str, list[int]]:
        for name, bounds in v.items():
            if len(bounds) != 2 or bounds[0] > bounds[1]:
                raise ValueError(f"range '{name}' 必須為 [low, high] 兩個遞增整數")
        return v

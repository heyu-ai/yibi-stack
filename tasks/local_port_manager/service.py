"""本地 Port 分配登錄系統的核心邏輯。"""

from dataclasses import dataclass
from pathlib import Path

from .models import Category, PortEntry, PortRegistry

REGISTRY_PATH = Path.home() / ".agents" / "ports.json"

DEFAULT_RANGES: dict[str, list[int]] = {
    "db": [5400, 5499],
    "cache": [6300, 6399],
    "backend": [3000, 3099],
    "frontend": [4000, 4099],
    "queue": [5600, 5699],
    "other": [9000, 9099],
}

SEEDED_DEFAULTS: dict[str, tuple[int, Category]] = {
    "postgres": (5432, Category.DB),
    "mysql": (3306, Category.DB),
    "mongodb": (27017, Category.DB),
    "redis": (6379, Category.CACHE),
    "rabbitmq": (5672, Category.QUEUE),
    "backend": (8000, Category.BACKEND),
    "frontend": (4000, Category.FRONTEND),
}

BootstrapEntry = tuple[str, str, int, Category]  # (project, service, port, category)

BOOTSTRAP_ENTRIES: list[BootstrapEntry] = [
    ("yibi-mvp", "postgres", 5432, Category.DB),
    ("yibi-mvp", "redis", 6379, Category.CACHE),
    ("yibi-mvp", "backend", 8000, Category.BACKEND),
    ("yibi-mvp", "frontend", 5173, Category.FRONTEND),
    ("yibi-mvp", "admin", 5174, Category.FRONTEND),
    ("voice-lab", "postgres", 5433, Category.DB),
    ("voice-lab", "redis", 6380, Category.CACHE),
    ("coachly", "postgres", 5434, Category.DB),
    ("coachly", "redis", 6381, Category.CACHE),
    ("coachly", "api", 8001, Category.BACKEND),
    ("coachly", "pgadmin", 5050, Category.OTHER),
    ("coachly", "flower", 5555, Category.OTHER),
    ("coaching365", "frontend", 4000, Category.FRONTEND),
    ("coaching365", "api", 8002, Category.BACKEND),
]


def load_registry(path: Path | None = None) -> PortRegistry:
    """載入 registry；檔案不存在或格式錯誤時 raise RuntimeError。"""
    registry_path = path or REGISTRY_PATH
    if not registry_path.exists():
        raise RuntimeError(f"Registry 不存在：{registry_path}，請先執行 init 指令")
    try:
        content = registry_path.read_text(encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"無法讀取 registry 檔案：{registry_path}（{e}）") from e
    try:
        return PortRegistry.model_validate_json(content)
    except Exception as e:
        raise RuntimeError(
            f"Registry 檔案格式錯誤：{registry_path}，請確認 JSON 是否合法（{e}）"
        ) from e


def save_registry(registry: PortRegistry, path: Path | None = None) -> None:
    """儲存 registry 至 JSON 檔；I/O 失敗時 raise RuntimeError。"""
    registry_path = path or REGISTRY_PATH
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"無法儲存 registry：{registry_path}（{e}）") from e


def is_port_taken(registry: PortRegistry, port: int) -> PortEntry | None:
    """回傳佔用該 port 的 entry；未佔用回傳 None。"""
    for entry in registry.entries:
        if entry.port == port:
            return entry
    return None


def find_next_available(registry: PortRegistry, category: Category) -> int:
    """在 category range 內找第一個空閒 port；全滿時 raise RuntimeError。"""
    range_bounds = registry.ranges.get(str(category))
    if not range_bounds:
        raise RuntimeError(f"未定義的 category range：{category}")
    taken_ports = {e.port for e in registry.entries}
    for port in range(range_bounds[0], range_bounds[1] + 1):
        if port not in taken_ports:
            return port
    raise RuntimeError(
        f"category '{category}' 的 port range {range_bounds[0]}-{range_bounds[1]} 已全滿"
    )


@dataclass
class SuggestResult:
    """suggest() 的回傳結果。"""

    suggested_port: int
    conflict: PortEntry | None
    is_default: bool


def get_entry(registry: PortRegistry, project: str, service: str) -> PortEntry | None:
    """依 (project, service) 查詢 entry；找不到回傳 None。"""
    for entry in registry.entries:
        if (entry.project, entry.service) == (project, service):
            return entry
    return None


def suggest(
    registry: PortRegistry,
    project: str,
    service: str,
    category: Category | None = None,
) -> SuggestResult:
    """查詢建議 port，不寫入 registry。"""
    if service in SEEDED_DEFAULTS:
        default_port, default_category = SEEDED_DEFAULTS[service]
        effective_category = category or default_category
        conflict = is_port_taken(registry, default_port)
        if conflict is None:
            return SuggestResult(
                suggested_port=default_port,
                conflict=None,
                is_default=True,
            )
        fallback = find_next_available(registry, effective_category)
        return SuggestResult(
            suggested_port=fallback,
            conflict=conflict,
            is_default=False,
        )

    if category is None:
        raise ValueError(f"服務 '{service}' 無慣例 port，請透過 --category 指定服務類別")

    fallback = find_next_available(registry, category)
    return SuggestResult(suggested_port=fallback, conflict=None, is_default=False)


def reserve(registry: PortRegistry, entry: PortEntry) -> PortRegistry:
    """寫入登記。port 被不同 (project, service) 佔用時 raise ValueError；相同則覆寫。"""
    conflict = is_port_taken(registry, entry.port)
    if conflict is not None and (conflict.project, conflict.service) != (
        entry.project,
        entry.service,
    ):
        raise ValueError(
            f"Port {entry.port} 已被 {conflict.project}/{conflict.service} 佔用，"
            f"無法登記給 {entry.project}/{entry.service}"
        )
    new_entries = [
        e for e in registry.entries if (e.project, e.service) != (entry.project, entry.service)
    ]
    new_entries.append(entry)
    return PortRegistry(version=registry.version, ranges=registry.ranges, entries=new_entries)


def release(registry: PortRegistry, project: str, service: str) -> PortRegistry:
    """移除 (project, service) 的登記；找不到時冪等回傳原 registry。"""
    new_entries = [e for e in registry.entries if (e.project, e.service) != (project, service)]
    return PortRegistry(version=registry.version, ranges=registry.ranges, entries=new_entries)

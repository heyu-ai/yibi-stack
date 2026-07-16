"""CLI 入口：本地 Port 分配管理。"""

from datetime import UTC, datetime

import click

from .models import Category, PortEntry, PortRegistry


@click.group()
@click.version_option(package_name="yibi-stack")
def cli() -> None:
    """本地開發 Port 分配管理工具。"""


@cli.command()
def init() -> None:
    """初始化空 registry 與預設 port range（已存在則跳過）。"""
    from . import service

    if service.REGISTRY_PATH.exists():
        click.echo(f"✓ Registry 已存在：{service.REGISTRY_PATH}")
        return

    registry = PortRegistry(ranges=service.DEFAULT_RANGES, entries=[])
    try:
        service.save_registry(registry, service.REGISTRY_PATH)
    except RuntimeError as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1) from e
    click.echo(f"✓ 已初始化空 registry：{service.REGISTRY_PATH}")
    click.echo("  用 reserve 指令登記 port，或用 suggest 取得建議值。")


@cli.command("list")
@click.option("--project", "-p", default=None, help="過濾專案名稱")
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice(["db", "cache", "backend", "frontend", "queue", "other"]),
    help="過濾類別",
)
def list_entries(project: str | None, category: str | None) -> None:
    """列出已登記的 port。"""
    registry = _require_registry()
    entries = registry.entries
    if project:
        entries = [e for e in entries if e.project == project]
    if category:
        entries = [e for e in entries if e.category == category]

    if not entries:
        click.echo("（無符合的 port 登記）")
        return

    header = f"{'project':<16} {'service':<12} {'category':<10} {'port':<8} note"
    click.echo(header)
    click.echo("-" * len(header))
    for e in sorted(entries, key=lambda x: (x.project, x.service)):
        click.echo(f"{e.project:<16} {e.service:<12} {e.category:<10} {e.port:<8} {e.note}")


@cli.command()
@click.argument("project")
@click.argument("service")
def get(project: str, service: str) -> None:
    """取得 (PROJECT, SERVICE) 的 port 號碼。找不到時 exit 1（適合 Makefile 捕捉）。"""
    from .service import get_entry

    registry = _require_registry()
    entry = get_entry(registry, project, service)
    if entry is None:
        raise SystemExit(1)
    click.echo(entry.port)


@cli.command("suggest")
@click.argument("project")
@click.argument("service")
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice(["db", "cache", "backend", "frontend", "queue", "other"]),
    help="服務類別（無慣例 port 時必填）",
)
def suggest_cmd(project: str, service: str, category: str | None) -> None:
    """查詢建議 port（不寫入 registry）。"""
    from .service import SuggestResult, suggest

    registry = _require_registry()
    cat = Category(category) if category else None
    try:
        result: SuggestResult = suggest(registry, project, service, category=cat)
    except (ValueError, RuntimeError) as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1) from e

    if result.conflict:
        c = result.conflict
        click.echo(f"⚠️  {c.port} 已被 {c.project}/{c.service} 佔用")
    range_info = _range_info(registry, result.suggested_port)
    click.echo(f"💡 建議 port：{result.suggested_port}{range_info}")


@cli.command("reserve")
@click.argument("project")
@click.argument("service")
@click.option("--port", "-n", required=True, type=int, help="指定 port 號碼")
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice(["db", "cache", "backend", "frontend", "queue", "other"]),
    help="服務類別（無慣例 port 時建議填寫）",
)
@click.option("--note", default="", help="備註")
def reserve_cmd(project: str, service: str, port: int, category: str | None, note: str) -> None:
    """登記 (PROJECT, SERVICE) 使用指定 port。"""
    from .service import reserve, save_registry

    registry = _require_registry()
    cat = _infer_category(registry, service, category, port)
    entry = PortEntry(
        project=project,
        service=service,
        category=cat,
        port=port,
        note=note,
        registered_at=datetime.now(tz=UTC),
    )
    try:
        updated = reserve(registry, entry)
    except ValueError as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1) from e
    try:
        save_registry(updated)
    except RuntimeError as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1) from e
    click.echo(f"✓ 已登記 {project}/{service} → {port}")


@cli.command("release")
@click.argument("project")
@click.argument("service")
def release_cmd(project: str, service: str) -> None:
    """移除 (PROJECT, SERVICE) 的 port 登記。"""
    from .service import get_entry, release, save_registry

    registry = _require_registry()
    if get_entry(registry, project, service) is None:
        click.echo(f"（{project}/{service} 本來就不存在，略過）")
        return
    updated = release(registry, project, service)
    try:
        save_registry(updated)
    except RuntimeError as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1) from e
    click.echo(f"✓ 已移除 {project}/{service} 的登記")


@cli.command()
@click.argument("port", type=int)
def check(port: int) -> None:
    """查詢某 PORT 被哪個專案佔用。"""
    from .service import is_port_taken

    registry = _require_registry()
    entry = is_port_taken(registry, port)
    if entry is None:
        click.echo(f"✓ {port} 未被使用")
    else:
        click.echo(f"{port} → {entry.project}/{entry.service} ({entry.category})")


def _require_registry() -> PortRegistry:
    from .service import load_registry

    try:
        return load_registry()
    except RuntimeError as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1) from e


def _category_name_for_port(registry: PortRegistry, port: int) -> str | None:
    """回傳 port 所屬的 category 名稱；不在任何 range 內時回傳 None。"""
    for cat_name, bounds in registry.ranges.items():
        if bounds[0] <= port <= bounds[1]:
            return cat_name
    return None


def _range_info(registry: PortRegistry, port: int) -> str:
    cat_name = _category_name_for_port(registry, port)
    if cat_name is None:
        return ""
    bounds = registry.ranges[cat_name]
    return f"（{cat_name} 範圍 {bounds[0]}-{bounds[1]}）"


def _infer_category(
    registry: PortRegistry,
    service: str,
    category: str | None,
    port: int,
) -> Category:
    from .service import SEEDED_DEFAULTS

    if category:
        return Category(category)
    if service in SEEDED_DEFAULTS:
        return SEEDED_DEFAULTS[service][1]
    cat_name = _category_name_for_port(registry, port)
    return Category(cat_name) if cat_name else Category.OTHER

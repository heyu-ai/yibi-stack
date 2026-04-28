"""Agents CLI：init / migrate / account / handover / insight / debug 子命令。"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import click

from .config import (
    AGENTS_CONFIG_PATH,
    DEBUG_REPORTS_JSONL_PATH,
    INSIGHTS_JSONL_PATH,
    RECAP_JSONL_PATH,
    REGISTRY_DIR,
    STIGNORE_PATH,
    ensure_dirs,
    generate_default_config,
    load_agents_config,
    save_agents_config,
)
from .models import AgentsConfig, EventType, SessionType


@click.group()
def cli() -> None:
    """Multi-Agent 工作協作中樞：跨 Agent / 跨帳號 / 跨機器的 handover、insight 整合層。"""


# ─── init ────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--device-id", default=None, help="裝置 ID，預設為 hostname")
@click.option("--default-account", default=None, help="預設帳號（可用 AGENT_ACCOUNT 環境變數覆蓋）")
@click.option("--force", is_flag=True, help="config.json 已存在時強制覆蓋")
def init(device_id: str | None, default_account: str | None, force: bool) -> None:
    """初始化 ~/.agents/ 目錄結構與 config.json。"""
    ensure_dirs()

    if AGENTS_CONFIG_PATH.exists() and not force:
        click.echo(f"設定檔已存在：{AGENTS_CONFIG_PATH}（使用 --force 覆蓋）")
    else:
        config = generate_default_config()
        overrides: dict[str, object] = {}
        if device_id:
            overrides["device_id"] = device_id
        if default_account:
            overrides["default_account"] = default_account
        if overrides:
            config = AgentsConfig.model_validate({**config.model_dump(), **overrides})
        save_agents_config(config)
        click.echo(f"✓ 已建立 config.json：{AGENTS_CONFIG_PATH}")
        click.echo(f"  device_id = {config.device_id}")
        click.echo(f"  default_account = {config.default_account or '(未設定)'}")

    # 寫 .stignore（給 Syncthing 用，避免 SQLite journal 被同步）
    if not STIGNORE_PATH.exists():
        STIGNORE_PATH.write_text(
            textwrap.dedent(
                """\
                // Syncthing ignore patterns for ~/.agents/
                handover.db-journal
                handover.db-wal
                handover.db-shm
                *.sync-conflict-*
                config.json
                """
            ),
            encoding="utf-8",
        )
        click.echo(f"✓ 已建立 .stignore：{STIGNORE_PATH}")

    # 建 _registry/ 下的空 JSON（若不存在）
    for name in ("devices.json", "accounts.json", "projects.json"):
        p = REGISTRY_DIR / name
        if not p.exists():
            p.write_text("[]\n", encoding="utf-8")

    click.echo("")
    click.echo("下一步：")
    click.echo("  1. uv run python -m tasks.session_memory insight install-hook")
    click.echo("  2. uv run python -m tasks.session_memory migrate")
    click.echo("  3. uv run python -m tasks.session_memory handover write ...")


# ─── migrate ─────────────────────────────────────────────────────────────


@cli.command()
def migrate() -> None:
    """把 ~/.handover/ 與 ~/.claude/insight/ 的舊資料搬到 ~/.agents/。"""
    from .migrate import migrate_all

    report = migrate_all()

    click.echo("=== Handover ===")
    if report.handover_source:
        click.echo(f"  來源：{report.handover_source}")
        click.echo(
            f"  搬遷 {report.handover_migrated} 筆，跳過 {report.handover_skipped} 筆（已存在）"
        )
    else:
        click.echo("  無舊 handover.db，跳過")

    click.echo("")
    click.echo("=== Insight ===")
    if report.insight_source:
        click.echo(f"  來源：{report.insight_source}")
        click.echo(
            f"  搬遷 {report.insight_migrated} 筆，跳過 {report.insight_skipped} 筆（已存在）"
        )
    else:
        click.echo("  無舊 insights.jsonl，跳過")

    if report.handover_source or report.insight_source:
        click.echo("")
        click.echo("搬遷完成。確認新資料無誤後可手動刪除舊路徑：")
        click.echo("  rm -rf ~/.handover/")
        click.echo("  rm -rf ~/.claude/insight/")
        click.echo("  （並執行：uv run python -m tasks.session_memory insight install-hook）")


# ─── account ─────────────────────────────────────────────────────────────


@cli.group()
def account() -> None:
    """帳號偵測與管理。"""


@account.command("detect")
def account_detect() -> None:
    """印出當下偵測到的帳號 / 裝置 / 專案 / branch / agent_type。"""
    from .account import (
        detect_account,
        detect_agent_type,
        detect_branch,
        detect_device,
        detect_project,
    )

    click.echo(f"account    = {detect_account(warn=True)}")
    click.echo(f"agent_type = {detect_agent_type()}")
    click.echo(f"device     = {detect_device()}")
    click.echo(f"project    = {detect_project()}")
    click.echo(f"branch     = {detect_branch() or '(無)'}")


@account.command("set-default")
@click.argument("account_name")
def account_set_default(account_name: str) -> None:
    """寫入 config.json 的 default_account。"""
    config = load_agents_config()
    if config is None:
        msg = "找不到 config.json，請先執行：uv run python -m tasks.session_memory init"
        click.echo(msg, err=True)
        raise SystemExit(1)
    config = AgentsConfig.model_validate({**config.model_dump(), "default_account": account_name})
    save_agents_config(config)
    click.echo(f"✓ default_account = {account_name}")


@account.command("link-claude")
@click.pass_context
def link_claude(ctx: click.Context) -> None:
    """建立 Claude Code userID hash → email 對照（首次設定必做）。"""
    from .registry import AccountRegistry

    # 支援測試時透過 obj 注入路徑
    obj = ctx.obj or {}
    claude_json_path: Path = obj.get("claude_json_path") or Path.home() / ".claude" / ".claude.json"
    accounts_path: Path | None = obj.get("accounts_path")

    if not claude_json_path.exists():
        click.echo(f"✗ 找不到 {claude_json_path}", err=True)
        click.echo("  請確認 Claude Code 已安裝並登入過。", err=True)
        raise SystemExit(1)

    try:
        data = json.loads(claude_json_path.read_text(encoding="utf-8"))
        user_id = data.get("userID", "").strip()
    except Exception as e:
        click.echo(f"✗ 無法讀取 {claude_json_path}：{e}", err=True)
        raise SystemExit(1) from e

    if not user_id:
        click.echo("✗ .claude.json 沒有 userID 欄位", err=True)
        raise SystemExit(1)

    email = click.prompt("請輸入此 Claude 帳號的 email")
    if "@" not in email:
        click.echo("✗ email 格式不正確（必須包含 @）", err=True)
        raise SystemExit(1)

    reg = AccountRegistry(accounts_path=accounts_path)
    is_new = reg.auto_register(email.strip(), "claude", extra={"hash": user_id})
    if is_new:
        click.echo(f"✓ 已建立對照：{user_id[:8]}... → {email}")
    else:
        click.echo(f"✓ 已存在：{email}（未重複寫入）")


# ─── handover ────────────────────────────────────────────────────────────


@cli.group()
def handover() -> None:
    """Handover 交班記錄：寫入 / 讀取 / 搜尋。"""


def _parse_json_list(value: str | None, field: str) -> list[str]:
    """把 --completed '[a, b]' 這類 JSON string 解析成 list。"""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"{field} 必須為合法 JSON array，收到：{value}") from e
    if not isinstance(parsed, list):
        raise click.BadParameter(f"{field} 必須為 JSON array，收到型別：{type(parsed).__name__}")
    return [str(x) for x in parsed]


@handover.command("write")
@click.option(
    "--session-type",
    "-t",
    required=True,
    type=click.Choice([e.value for e in SessionType]),
)
@click.option("--topic", required=True, help="這次工作的主題")
@click.option("--summary", required=True, help="對話重點摘要")
@click.option("--operator", default="howie", help="操作者")
@click.option("--completed", default=None, help="完成的事項（JSON array）")
@click.option("--decisions", default=None, help="決策（JSON array）")
@click.option("--blocked", default=None, help="卡住的事項（JSON array）")
@click.option("--next", "next_priorities", default=None, help="下一步（JSON array）")
@click.option("--lessons", default=None, help="學到的事（JSON array）")
@click.option("--approaches", default=None, help="試過的方案（JSON array）")
@click.option("--tags", default=None, help="自由標籤（JSON array）")
@click.option("--files", default=None, help="最後處理的檔案（JSON array）")
@click.option("--test-status", default=None, help="測試狀態摘要")
@click.option("--tokens", default=None, help="token 使用量估計")
@click.option("--device", default=None, help="覆蓋自動偵測的 device")
@click.option("--agent", default=None, help="覆蓋自動偵測的 agent_type")
@click.option("--account", "account_opt", default=None, help="覆蓋自動偵測的 account")
@click.option("--branch", default=None, help="覆蓋自動偵測的 git branch")
@click.option("--project", default=None, help="覆蓋自動偵測的 project")
@click.option("--workdir", default=None, help="覆蓋自動偵測的 working_dir")
def handover_write(  # pylint: disable=too-many-arguments,too-many-locals
    session_type: str,
    topic: str,
    summary: str,
    operator: str,
    completed: str | None,
    decisions: str | None,
    blocked: str | None,
    next_priorities: str | None,
    lessons: str | None,
    approaches: str | None,
    tags: str | None,
    files: str | None,
    test_status: str | None,
    tokens: str | None,
    device: str | None,
    agent: str | None,
    account_opt: str | None,
    branch: str | None,
    project: str | None,
    workdir: str | None,
) -> None:
    """寫入一筆 handover。"""
    from .handover_service import write_handover

    record = write_handover(
        session_type=SessionType(session_type),
        topic=topic,
        summary=summary,
        operator=operator,
        completed=_parse_json_list(completed, "--completed"),
        decisions=_parse_json_list(decisions, "--decisions"),
        blocked=_parse_json_list(blocked, "--blocked"),
        next_priorities=_parse_json_list(next_priorities, "--next"),
        lessons_learned=_parse_json_list(lessons, "--lessons"),
        attempted_approaches=_parse_json_list(approaches, "--approaches"),
        tags=_parse_json_list(tags, "--tags"),
        last_files=_parse_json_list(files, "--files"),
        test_status=test_status,
        token_usage_estimate=tokens,
        device=device,
        agent_type=agent,
        account=account_opt,
        branch=branch,
        project=project,
        working_dir=workdir,
    )

    click.echo(f"✓ handover 已寫入：{record.id}")
    click.echo(f"  topic   = {record.topic}")
    click.echo(f"  type    = {record.session_type.value}")
    click.echo(f"  device  = {record.device}")
    click.echo(f"  account = {record.subscription_account}")
    click.echo(f"  project = {record.project}")


@handover.command("read")
@click.option("--last", default=4, type=int, help="讀取最近 N 筆")
@click.option("--project", default=None, help="只顯示指定 project 的記錄（預設顯示全部）")
@click.option("--json", "as_json", is_flag=True, help="輸出 JSON")
def handover_read(last: int, project: str | None, as_json: bool) -> None:
    """讀取最近 N 筆 handover，可依 project 過濾。"""
    from .handover_service import read_recent

    rows = read_recent(last=last, project=project)
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        click.echo("(尚無 handover 記錄)")
        return

    for r in rows:
        click.echo("─" * 60)
        click.echo(f"[{r['timestamp']}] {r['session_type']} — {r['topic']}")
        click.echo(
            f"  account={r.get('subscription_account')}  "
            f"device={r.get('device')}  project={r.get('project')}"
        )
        click.echo(f"  {r['conversation_summary'][:120]}")


@handover.command("install-hooks")
def handover_install_hooks() -> None:
    """註冊 PreCompact + SessionStart auto-handover hooks 到 ~/.claude/settings.json。"""
    from .auto_handover_hooks import install_hooks

    precompact_new, session_new, msg = install_hooks()
    prefix = "✓" if (precompact_new or session_new) else "↻"
    click.echo(f"{prefix} {msg}")


@handover.command("uninstall-hooks")
def handover_uninstall_hooks() -> None:
    """從 ~/.claude/settings.json 移除 auto-handover hooks。"""
    from .auto_handover_hooks import uninstall_hooks

    removed, msg = uninstall_hooks()
    prefix = "✓" if removed else "↻"
    click.echo(f"{prefix} {msg}")


@handover.command("search")
@click.option(
    "--query",
    default=None,
    help="在 topic / summary / tags / lessons / approaches 內 LIKE 搜尋",
)
@click.option(
    "--type",
    "session_type",
    default=None,
    type=click.Choice([e.value for e in SessionType]),
)
@click.option("--project", default=None)
@click.option("--account", "account_opt", default=None)
@click.option("--limit", default=10, type=int)
@click.option("--json", "as_json", is_flag=True)
def handover_search(
    query: str | None,
    session_type: str | None,
    project: str | None,
    account_opt: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """搜尋 handover 記錄。"""
    from .handover_service import search_handovers

    rows = search_handovers(
        query=query,
        session_type=SessionType(session_type) if session_type else None,
        project=project,
        account=account_opt,
        limit=limit,
    )

    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        click.echo("(無符合記錄)")
        return

    for r in rows:
        click.echo("─" * 60)
        click.echo(f"[{r['timestamp']}] {r['session_type']} — {r['topic']}")
        click.echo(f"  {r['conversation_summary'][:120]}")


# ─── insight ─────────────────────────────────────────────────────────────


@cli.group()
def insight() -> None:
    """Insight 自動收集：Stop hook 安裝 / 移除 / 觸發。"""


@insight.command("install-hook")
def insight_install_hook() -> None:
    """註冊 Stop hook 到 ~/.claude/settings.json。"""
    from .insight_hook import install_hook

    is_new, msg = install_hook()
    prefix = "✓" if is_new else "↻"
    click.echo(f"{prefix} {msg}")
    click.echo(f"  輸出：{INSIGHTS_JSONL_PATH}")


@insight.command("uninstall-hook")
def insight_uninstall_hook() -> None:
    """從 ~/.claude/settings.json 移除 Stop hook。"""
    from .insight_hook import uninstall_hook

    removed, msg = uninstall_hook()
    prefix = "✓" if removed else "↻"
    click.echo(f"{prefix} {msg}")


@insight.command("collect")
def insight_collect() -> None:
    """Stop hook entry point — 從 stdin 讀 hook payload 並擷取 Insight。"""
    from .insight_hook import run_hook

    run_hook()


@insight.command("list")
@click.option("--last", default=10, type=int)
@click.option("--project", default=None)
def insight_list(last: int, project: str | None) -> None:
    """列出最近 N 筆 insights（可選 project filter）。"""
    if not INSIGHTS_JSONL_PATH.exists():
        click.echo("(尚無 insights.jsonl)")
        return

    rows: list[dict[str, object]] = []
    with INSIGHTS_JSONL_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if project and entry.get("project") != project:
                continue
            rows.append(entry)

    for r in rows[-last:]:
        click.echo("─" * 60)
        click.echo(f"[{r.get('timestamp')}] {r.get('project')} ({r.get('account')})")
        text = str(r.get("insight_text", ""))
        click.echo(text[:240])


# ─── recap ───────────────────────────────────────────────────────────────


@cli.group()
def recap() -> None:
    """Recap 自動收集：擷取 Claude Code away_summary（Stop hook）。"""


@recap.command("install-hook")
def recap_install_hook() -> None:
    """註冊 Stop hook 到 ~/.claude/settings.json。"""
    from .recap_hook import install_hook

    is_new, msg = install_hook()
    prefix = "✓" if is_new else "↻"
    click.echo(f"{prefix} {msg}")
    click.echo(f"  輸出：{RECAP_JSONL_PATH}")


@recap.command("uninstall-hook")
def recap_uninstall_hook() -> None:
    """從 ~/.claude/settings.json 移除 Stop hook。"""
    from .recap_hook import uninstall_hook

    removed, msg = uninstall_hook()
    prefix = "✓" if removed else "↻"
    click.echo(f"{prefix} {msg}")


@recap.command("collect")
def recap_collect() -> None:
    """Stop hook entry point — 從 stdin 讀 hook payload 並擷取 away_summary。"""
    import sys

    from .recap_hook import run_hook

    raise SystemExit(run_hook(sys.stdin.read(), RECAP_JSONL_PATH))


@recap.command("list")
@click.option("--last", default=10, type=int, help="最多顯示 N 筆")
@click.option("--project", default=None, help="只顯示指定 project")
@click.option("--session", default=None, help="只顯示指定 session_id")
def recap_list(last: int, project: str | None, session: str | None) -> None:
    """列出最近 N 筆 recap（可依 project / session filter）。"""
    if not RECAP_JSONL_PATH.exists():
        click.echo("(尚無 session-recap.jsonl)")
        return

    rows: list[dict[str, object]] = []
    with RECAP_JSONL_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if project and entry.get("project") != project:
                continue
            if session and entry.get("session_id") != session:
                continue
            rows.append(entry)

    for r in rows[-last:]:
        click.echo("─" * 60)
        click.echo(
            f"[{r.get('timestamp')}] {r.get('project')} "
            f"branch={r.get('branch')} session={str(r.get('session_id', ''))[:8]}"
        )
        text = str(r.get("recap_text", ""))
        click.echo(text[:300])


# ─── lessons ─────────────────────────────────────────────────────────────


@cli.group()
def lessons() -> None:
    """教訓聯合查詢：show 顯示，search 搜尋。整合 handover 教訓、試過的方案與 insight 洞察。"""


@lessons.command("show")
@click.option("--project", default=None, help="只顯示指定 project 的教訓（預設顯示全部）")
@click.option("--last", default=20, type=int, help="每個來源最多顯示 N 筆")
@click.option("--insights", "include_insights", is_flag=True, help="同時顯示 insight 洞察")
@click.option("--json", "as_json", is_flag=True, help="輸出 JSON")
def lessons_show(project: str | None, last: int, include_insights: bool, as_json: bool) -> None:
    """顯示 handover 教訓與試過的方案（可選合併 insight）。"""
    from .lessons_service import show_lessons

    rows = show_lessons(project=project, limit=last, include_insights=include_insights)

    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        click.echo("(尚無教訓記錄)")
        return

    for r in rows:
        src = r["source"]
        label = {"handover": "交班教訓", "handover-approach": "試過的方案", "insight": "洞察"}.get(
            src, src
        )
        click.echo("─" * 60)
        click.echo(f"[{r['timestamp'][:10]}] [{label}] {r.get('context', '')}")
        if r.get("project"):
            click.echo(f"  project = {r['project']}")
        click.echo(f"  {r['text']}")


@lessons.command("search")
@click.argument("query")
@click.option("--project", default=None, help="只搜尋指定 project")
@click.option("--last", default=20, type=int, help="最多回傳 N 筆")
@click.option("--insights", "include_insights", is_flag=True, help="同時搜尋 insight 洞察")
@click.option("--json", "as_json", is_flag=True, help="輸出 JSON")
def lessons_search(
    query: str, project: str | None, last: int, include_insights: bool, as_json: bool
) -> None:
    """在 handover 教訓、試過的方案（與可選 insight）中搜尋關鍵字。"""
    from .lessons_service import search_lessons

    rows = search_lessons(
        query=query, project=project, limit=last, include_insights=include_insights
    )

    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        click.echo(f"(無符合「{query}」的教訓記錄)")
        return

    for r in rows:
        src = r["source"]
        label = {"handover": "交班教訓", "handover-approach": "試過的方案", "insight": "洞察"}.get(
            src, src
        )
        click.echo("─" * 60)
        click.echo(f"[{r['timestamp'][:10]}] [{label}] {r.get('context', '')}")
        if r.get("project"):
            click.echo(f"  project = {r['project']}")
        click.echo(f"  {r['text']}")


# ─── metrics ─────────────────────────────────────────────────────────────


@cli.group()
def metrics() -> None:
    """Auto-handover 成功率量測：事件流、統計、rule-based 建議。"""


@metrics.command("stats")
@click.option("--since-days", default=30, type=int, help="統計起始點（N 天前），預設 30")
@click.option("--project", default=None, help="只統計指定 project")
@click.option("--json", "as_json", is_flag=True, help="輸出 JSON")
def metrics_stats(since_days: int, project: str | None, as_json: bool) -> None:
    """計算並顯示 auto-handover 成功率。"""
    from datetime import UTC, datetime, timedelta

    from .metrics_service import compute_stats

    since = datetime.now(UTC) - timedelta(days=since_days)
    report = compute_stats(since=since, project=project)

    if as_json:
        click.echo(report.model_dump_json(indent=2))
        return

    click.echo(f"── Auto-Handover 成功率報告（近 {since_days} 天）──")
    if project:
        click.echo(f"  project         = {project}")
    click.echo(f"  sessions_observed    = {report.sessions_observed}")
    click.echo(f"  total_intercepts     = {report.total_intercepts}")
    click.echo(f"  wrote_after_intercept= {report.wrote_after_intercept}")
    click.echo(f"  silent_fail          = {report.silent_fail}")
    click.echo(f"  hard_fail            = {report.hard_fail}")
    click.echo(f"  layer1_win           = {report.layer1_win}")
    click.echo(f"  stale_reset          = {report.stale_resets}")
    click.echo("")
    click.echo(f"  success_rate         = {report.success_rate:.1%}")
    click.echo(f"  silent_fail_rate     = {report.silent_fail_rate:.1%}")
    click.echo(f"  hard_fail_rate       = {report.hard_fail_rate:.1%}")
    click.echo(f"  layer1_win_rate      = {report.layer1_win_rate:.1%}")


@metrics.command("events")
@click.option("--last", default=50, type=int, help="讀取最近 N 筆")
@click.option("--session-id", default=None, help="只顯示指定 session_id")
@click.option(
    "--type",
    "event_type",
    default=None,
    type=click.Choice([e.value for e in EventType]),
    help="只顯示指定事件類型",
)
@click.option("--json", "as_json", is_flag=True, help="輸出 JSON")
def metrics_events(
    last: int, session_id: str | None, event_type: str | None, as_json: bool
) -> None:
    """列出最近 N 筆 handover 事件流。"""
    from .metrics_service import list_events

    rows = list_events(
        last=last,
        session_id=session_id,
        event_type=EventType(event_type) if event_type else None,
    )

    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        click.echo("(尚無事件紀錄)")
        return

    for r in rows:
        click.echo(
            f"[{r['timestamp']}] {r['event_type']:22s} "
            f"session={(r.get('session_id') or '-')[:12]:12s} "
            f"matcher={r.get('matcher') or '-':7s} "
            f"project={r.get('project') or '-'}"
        )


@metrics.command("advice")
@click.option("--since-days", default=30, type=int, help="統計窗口（N 天前），預設 30")
@click.option("--project", default=None, help="只評估指定 project")
@click.option("--json", "as_json", is_flag=True, help="輸出 JSON")
def metrics_advice(since_days: int, project: str | None, as_json: bool) -> None:
    """基於統計數據產生 rule-based 改善建議。"""
    from datetime import UTC, datetime, timedelta

    from .metrics_service import compute_stats, generate_advice

    since = datetime.now(UTC) - timedelta(days=since_days)
    report = compute_stats(since=since, project=project)
    suggestions = generate_advice(report)

    if as_json:
        click.echo(
            json.dumps(
                {"report": report.model_dump(mode="json"), "advice": suggestions},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    click.echo(f"── Auto-Handover 改善建議（近 {since_days} 天）──")
    click.echo(f"  success_rate={report.success_rate:.1%}  sessions={report.sessions_observed}")
    click.echo("")
    for idx, msg in enumerate(suggestions, 1):
        click.echo(f"[{idx}] {msg}")


# ─── debug ───────────────────────────────────────────────────────────────


@cli.group()
def debug() -> None:
    """Debug report 管理：save 歸檔摘要 / list 查詢歷史。"""


@debug.command("save")
@click.option("--keyword", required=True, help="關鍵字（kebab-case 或 snake_case）")
@click.option("--report-path", required=True, help="本地報告檔案路徑（相對 project root）")
@click.option("--symptom", required=True, help="症狀一行摘要")
@click.option("--root-cause", required=True, help="根因一行摘要")
@click.option("--prevention-tags", default="", help="逗號分隔預防標籤（如 test,mypy,ci）")
def debug_save(
    keyword: str,
    report_path: str,
    symptom: str,
    root_cause: str,
    prevention_tags: str,
) -> None:
    """將 debug report 摘要寫入 ~/.agents/debugs/debug-reports.jsonl。"""
    from pydantic import ValidationError

    from .debug_report_service import save_debug_report

    tags = [t.strip() for t in prevention_tags.split(",") if t.strip()]
    try:
        record = save_debug_report(
            keyword=keyword,
            report_path=report_path,
            symptom_summary=symptom,
            root_cause=root_cause,
            prevention_tags=tags,
        )
    except (RuntimeError, ValidationError) as e:
        click.echo(f"✗ 無法儲存 debug report：{e}", err=True)
        raise SystemExit(1) from e
    click.echo("✓ Debug report 摘要已歸檔")
    click.echo(f"  id       = {record.id}")
    click.echo(f"  keyword  = {record.keyword}")
    click.echo(f"  project  = {record.project}")
    click.echo(f"  路徑     = {DEBUG_REPORTS_JSONL_PATH}")


@debug.command("list")
@click.option("--last", default=10, type=int, help="最多顯示 N 筆")
@click.option("--project", default=None, help="只顯示指定 project")
def debug_list(last: int, project: str | None) -> None:
    """列出最近 N 筆 debug report 摘要（可依 project filter）。"""
    from .debug_report_service import list_debug_reports

    try:
        rows = list_debug_reports(last=last, project=project)
    except RuntimeError as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1) from e

    if not rows:
        if not DEBUG_REPORTS_JSONL_PATH.exists():
            click.echo("(尚未有任何 debug report，請先執行 debug save)")
        else:
            click.echo("(無符合條件的記錄)")
        return

    for r in rows:
        click.echo("─" * 60)
        click.echo(f"[{r.timestamp[:10]}] [{r.keyword}] {r.project}")
        click.echo(f"  症狀：{r.symptom_summary}")
        click.echo(f"  根因：{r.root_cause}")
        if r.prevention_tags:
            click.echo(f"  標籤：{', '.join(r.prevention_tags)}")


if __name__ == "__main__":
    cli()

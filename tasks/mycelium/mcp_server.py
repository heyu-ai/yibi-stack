"""MCP stdio server：mycelium serve 入口。

實作 MCP JSON-RPC over stdio 協議，暴露 4 個 tool：
  - mycelium_search
  - mycelium_get_lesson
  - mycelium_save_preference
  - mycelium_subscribe

遵循 MCP spec（tool name、inputSchema、output type）。
任何例外都回傳符合 MCP 格式的 error response，不 crash server。
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

# MCP tool definitions
_TOOLS: list[dict[str, Any]] = [
    {
        "name": "mycelium_search",
        "description": "Search lessons by keyword or semantic query",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
                "mode": {
                    "type": "string",
                    "enum": ["keyword", "vector", "hybrid"],
                    "default": "hybrid",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "mycelium_get_lesson",
        "description": "Get a single lesson by ID",
        "inputSchema": {
            "type": "object",
            "properties": {"lesson_id": {"type": "string"}},
            "required": ["lesson_id"],
        },
    },
    {
        "name": "mycelium_save_preference",
        "description": "Save a preference-type lesson",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["content"],
        },
    },
    {
        "name": "mycelium_subscribe",
        "description": "Subscribe to new lesson notifications",
        "inputSchema": {
            "type": "object",
            "properties": {"event_type": {"type": "string"}},
            "required": ["event_type"],
        },
    },
]


def run_server(
    input_stream: Any = None,
    output_stream: Any = None,
    db_path: str | None = None,
) -> None:
    """MCP stdio server main loop。

    讀取 stdin 的 JSON-RPC 請求，dispatch 到對應 handler，回應到 stdout。
    參數用於測試注入；正式執行時使用 sys.stdin/stdout。
    """
    _in = input_stream if input_stream is not None else sys.stdin
    _out = output_stream if output_stream is not None else sys.stdout

    for line in _in:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            _write(_out, _error_response(None, -32700, f"Parse error: {e}"))
            continue

        response = _handle_request(request, db_path=db_path)
        _write(_out, response)


def _write(stream: Any, obj: dict[str, Any]) -> None:
    stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
    if hasattr(stream, "flush"):
        stream.flush()


def _handle_request(request: dict[str, Any], db_path: str | None) -> dict[str, Any]:
    """Dispatch MCP request to the appropriate handler."""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "tools/list":
        return _ok(req_id, {"tools": _TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_input = params.get("arguments", {})
        return _dispatch_tool(req_id, tool_name, tool_input, db_path=db_path)

    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mycelium", "version": "1.0"},
            },
        )

    return _error_response(req_id, -32601, f"Method not found: {method}")


def _dispatch_tool(
    req_id: Any,
    tool_name: str,
    tool_input: dict[str, Any],
    db_path: str | None,
) -> dict[str, Any]:
    """Route tool call to the appropriate handler."""
    try:
        if tool_name == "mycelium_search":
            return _ok(req_id, _tool_search(tool_input, db_path))
        if tool_name == "mycelium_get_lesson":
            return _ok(req_id, _tool_get_lesson(tool_input, db_path))
        if tool_name == "mycelium_save_preference":
            return _ok(req_id, _tool_save_preference(tool_input, db_path))
        if tool_name == "mycelium_subscribe":
            return _ok(req_id, _tool_subscribe(tool_input, db_path))
        return _error_response(req_id, -32602, f"Unknown tool: {tool_name}")
    except Exception as e:
        print(f"[mycelium-mcp] tool={tool_name} 內部錯誤：{type(e).__name__}: {e}", file=sys.stderr)
        return _error_response(req_id, -32603, f"Internal error: {type(e).__name__}")


def _tool_search(
    args: dict[str, Any], db_path: str | None
) -> dict[str, Any]:
    """mycelium_search handler."""
    from .lessons_service import get_lessons

    query = str(args.get("query", ""))
    limit = int(args.get("limit", 10))

    rows = get_lessons(limit=limit, db_path=db_path)

    # TODO: Pass mode/query to get_lessons for FTS5/vector search once Phase 4 lands.
    # Currently fetches all lessons and applies client-side substring filter.
    # mode parameter is accepted by the schema but ignored here.
    if query:
        q = query.lower()
        rows = [r for r in rows if q in r.get("insight", "").lower() or q in r.get("key", "").lower()]

    summaries = [
        {
            "id": r.get("id"),
            "content_preview": r.get("insight", "")[:200],
            "effective_weight": r.get("effective_weight", 0.0),
            "tier": r.get("tier", "working"),
            "tags": r.get("tags", []),
        }
        for r in rows
    ]
    return {"content": [{"type": "text", "text": json.dumps(summaries, ensure_ascii=False)}]}


def _tool_get_lesson(
    args: dict[str, Any], db_path: str | None
) -> dict[str, Any]:
    """mycelium_get_lesson handler — returns null if not found."""
    from .db import AgentsDB

    lesson_id = str(args.get("lesson_id", ""))

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        row = db.conn.execute(
            "SELECT * FROM lessons WHERE id = ?", (lesson_id,)
        ).fetchone()
    finally:
        db.close()

    result = dict(row) if row else None
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}


def _tool_save_preference(
    args: dict[str, Any], db_path: str | None
) -> dict[str, Any]:
    """mycelium_save_preference handler."""
    from .lessons_service import save_lesson

    content = str(args.get("content", ""))
    tags = args.get("tags", [])

    result = save_lesson(
        content=content,
        tier="working",
        tags=list(tags),
        lesson_type="preference",
        db_path=db_path,
    )
    return {"content": [{"type": "text", "text": json.dumps({"lesson_id": result["id"]}, ensure_ascii=False)}]}


def _tool_subscribe(
    args: dict[str, Any], db_path: str | None
) -> dict[str, Any]:
    """mycelium_subscribe handler — stores subscription and returns token."""
    from .db import AgentsDB

    event_type = str(args.get("event_type", ""))
    token = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        _ensure_subscriptions_table(db)
        db.conn.execute(
            "INSERT INTO subscriptions (token, subscriber_bot, event_type, created_at) VALUES (?, ?, ?, ?)",
            (token, "unknown", event_type, now),
        )
        db.conn.commit()
    finally:
        db.close()

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"token": token, "event_type": event_type}, ensure_ascii=False),
            }
        ]
    }


def _ensure_subscriptions_table(db: Any) -> None:
    """建立 subscriptions table（冪等）。"""
    db.conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
          token          TEXT PRIMARY KEY,
          subscriber_bot TEXT NOT NULL,
          event_type     TEXT NOT NULL,
          created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
        """
    )
    db.conn.commit()


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error_response(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }

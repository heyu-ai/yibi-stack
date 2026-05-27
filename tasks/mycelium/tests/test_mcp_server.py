"""MCP server JSON-RPC 測試。"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

from tasks.mycelium.mcp_server import run_server


def _call(
    method: str, params: dict[str, Any], tmp_path: Path, *, req_id: int = 1
) -> dict[str, Any]:
    request = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
    in_stream = StringIO(request + "\n")
    out_stream = StringIO()
    run_server(input_stream=in_stream, output_stream=out_stream, db_path=str(tmp_path / "mcp.db"))
    result: dict[str, Any] = json.loads(out_stream.getvalue().strip())
    return result


class TestMcpServerProtocol:
    def test_myc_mcp_dt_001_initialize(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-001: initialize returns serverInfo"""
        resp = _call("initialize", {}, tmp_path)
        assert "result" in resp
        assert resp["result"]["serverInfo"]["name"] == "mycelium"

    def test_myc_mcp_dt_002_tools_list(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-002: tools/list returns 4 tools"""
        resp = _call("tools/list", {}, tmp_path)
        tools = resp["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert tool_names == {
            "mycelium_search",
            "mycelium_get_lesson",
            "mycelium_save_preference",
            "mycelium_subscribe",
        }

    def test_myc_mcp_dt_003_unknown_method(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-003: unknown method returns error -32601"""
        resp = _call("nonexistent", {}, tmp_path)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_myc_mcp_dt_004_save_preference(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-004: mycelium_save_preference returns lesson_id"""
        resp = _call(
            "tools/call",
            {
                "name": "mycelium_save_preference",
                "arguments": {"content": "Prefer dark mode in all UIs."},
            },
            tmp_path,
        )
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "lesson_id" in content
        assert len(content["lesson_id"]) > 0

    def test_myc_mcp_dt_005_search_returns_list(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-005: mycelium_search returns content list"""
        resp = _call(
            "tools/call",
            {"name": "mycelium_search", "arguments": {"query": "dark mode"}},
            tmp_path,
        )
        assert "result" in resp

    def test_myc_mcp_dt_006_subscribe_returns_token(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-006: mycelium_subscribe returns token"""
        resp = _call(
            "tools/call",
            {"name": "mycelium_subscribe", "arguments": {"event_type": "new_lesson"}},
            tmp_path,
        )
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "token" in content
        assert len(content["token"]) > 0

    def test_myc_mcp_dt_007_get_nonexistent_lesson(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-007: get_lesson with unknown id returns null"""
        resp = _call(
            "tools/call",
            {"name": "mycelium_get_lesson", "arguments": {"lesson_id": "nonexistent-id"}},
            tmp_path,
        )
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content is None

    def test_myc_mcp_dt_008_unknown_tool_error(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-008: unknown tool returns error -32602"""
        resp = _call(
            "tools/call",
            {"name": "nonexistent_tool", "arguments": {}},
            tmp_path,
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    def test_myc_mcp_dt_009_parse_error(self, tmp_path: Path) -> None:
        """MYC-MCP-DT-009: invalid JSON input returns parse error -32700"""
        in_stream = StringIO("not json\n")
        out_stream = StringIO()
        run_server(
            input_stream=in_stream,
            output_stream=out_stream,
            db_path=str(tmp_path / "mcp.db"),
        )
        resp = json.loads(out_stream.getvalue().strip())
        assert "error" in resp
        assert resp["error"]["code"] == -32700

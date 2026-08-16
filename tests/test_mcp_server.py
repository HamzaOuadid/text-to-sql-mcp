"""End-to-end MCP server tests, driven through a real `mcp.ClientSession`
(in-memory transport) rather than calling the underlying Python functions
directly -- this is what the spec means by "tested end-to-end via an MCP
client" (milestone M4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from text_to_sql_mcp import mcp_server


@pytest.fixture()
def mcp_env(monkeypatch: pytest.MonkeyPatch, civic_db_path: Path, app_db_path: Path):
    """Point the MCP server's settings lookup at the test databases."""
    monkeypatch.setenv("CIVIC_DB_PATH", str(civic_db_path))
    monkeypatch.setenv("APP_DB_PATH", str(app_db_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


def _text_content(result) -> str:
    """Extract the text payload from an MCP CallToolResult."""
    parts = []
    for block in result.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


async def test_list_schema_tool_end_to_end(mcp_env) -> None:
    async with create_connected_server_and_client_session(mcp_server.mcp._mcp_server) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools.tools}
        assert "list_schema" in tool_names
        assert "ask" in tool_names

        result = await client.call_tool("list_schema", {})
        assert result.isError is not True
        payload = json.loads(_text_content(result))
        table_names = {t["name"] for t in payload["tables"]}
        assert "permits" in table_names
        assert "complaints" in table_names


async def test_ask_tool_end_to_end_answers_known_question(mcp_env) -> None:
    async with create_connected_server_and_client_session(mcp_server.mcp._mcp_server) as client:
        result = await client.call_tool(
            "ask", {"question": "How many permits are there in total?"}
        )
        payload = json.loads(_text_content(result))
        assert payload["rejected"] is False
        assert payload["rows"] == [{"count": 2600}]


async def test_ask_tool_end_to_end_rejects_ambiguous_question(mcp_env) -> None:
    async with create_connected_server_and_client_session(mcp_server.mcp._mcp_server) as client:
        result = await client.call_tool("ask", {"question": "Show me the recent activity."})
        payload = json.loads(_text_content(result))
        assert payload["rejected"] is True
        assert "ambiguous" in payload["rejection_reason"].lower() or "clarification" in payload["rejection_reason"].lower()

"""Smoke-тест MCP-сервера: поднимаем stdio-сервер и вызываем инструменты.

Требует установленный CLI (``pip install -e .``), сеть и Chromium — поэтому
маркируется как browser и в основном CI-джобе не гоняется.
Запуск вручную: pytest tests/test_mcp_smoke.py -m browser
"""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

pytestmark = pytest.mark.browser


def test_mcp_tools_smoke() -> None:
    if shutil.which("webscope") is None:
        pytest.skip("CLI webscope не установлен")
    asyncio.run(_scenario())


async def _scenario() -> None:
    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(command="webscope", args=["mcp"])
    async with Client(params) as client:
        tools = await client.list_tools()
        tool_list = tools[0] if isinstance(tools, tuple) else tools.tools
        names = [tool.name for tool in tool_list]
        assert "scan_page" in names
        assert "list_findings" in names
        assert "get_fix_prompt" in names

        result = await client.call_tool("scan_page", {"url": "https://example.com"})
        payload = json.loads(result.content[0].text)
        assert payload["summary"]["total"] >= 0
        assert payload["archetype"] is not None

        listed = await client.call_tool("list_findings", {"url": "https://example.com", "min_severity": "moderate"})
        structured = getattr(listed, "structured_content", None) or {}
        assert isinstance(structured.get("result", []), list)

        prompt = await client.call_tool("get_fix_prompt", {"url": "https://example.com"})
        assert prompt.content[0].text.strip()

"""Smoke-тест MCP-сервера: поднимаем stdio-сервер и вызываем инструменты.

Запуск: python tests/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import json

from mcp import Client, StdioServerParameters


async def main() -> None:
    params = StdioServerParameters(command="webscope", args=["mcp"])
    async with Client(params) as client:
        tools = await client.list_tools()
        tool_list = tools[0] if isinstance(tools, tuple) else tools.tools
        print("инструменты:", [tool.name for tool in tool_list])

        result = await client.call_tool("scan_page", {"url": "https://example.com"})
        payload = json.loads(result.content[0].text)
        print("summary:", payload["summary"])
        print("archetype:", payload["archetype"])

        listed = await client.call_tool("list_findings", {"url": "https://example.com", "min_severity": "moderate"})
        structured = getattr(listed, "structured_content", None) or {}
        findings = structured.get("result", [])
        print("moderate+:", len(findings))

        prompt = await client.call_tool("get_fix_prompt", {"url": "https://example.com"})
        print("fix-prompt, первые строки:")
        print("\n".join(prompt.content[0].text.splitlines()[:8]))


if __name__ == "__main__":
    asyncio.run(main())

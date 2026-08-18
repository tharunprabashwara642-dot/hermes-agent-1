"""Connects to any number of MCP (Model Context Protocol) servers declared in
config.yaml, and exposes their tools as one flat, agent-loop-friendly list.

Supports:
  - transport: stdio  -> local MCP servers launched as a subprocess
  - transport: http    -> remote MCP servers reachable over streamable-HTTP,
                           authenticated with a bearer token (config `token`)

A server that fails to connect is skipped with a warning, not a crash — the
rest of the agent (and any other MCP servers) keep working.
"""
from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass

logger = logging.getLogger("tharun.mcp")


@dataclass
class MCPTool:
    server: str
    name: str
    description: str
    input_schema: dict

    @property
    def qualified_name(self) -> str:
        # Namespaced so tools with the same name on different servers don't collide
        return f"{self.server}::{self.name}"


class MCPManager:
    def __init__(self, server_configs: list[dict]):
        self.server_configs = [c for c in server_configs if c.get("enabled", True)]
        self._stack = AsyncExitStack()
        self._sessions: dict[str, object] = {}
        self.tools: dict[str, MCPTool] = {}

    async def connect_all(self):
        for cfg in self.server_configs:
            name = cfg.get("name", "unnamed")
            try:
                session = await self._connect_one(cfg)
                self._sessions[name] = session
                resp = await session.list_tools()
                for t in resp.tools:
                    mcp_tool = MCPTool(
                        server=name,
                        name=t.name,
                        description=t.description or "",
                        input_schema=t.inputSchema or {"type": "object", "properties": {}},
                    )
                    self.tools[mcp_tool.qualified_name] = mcp_tool
                logger.info("MCP server '%s' connected with %d tool(s)", name, len(resp.tools))
            except Exception as e:
                # Never let one bad MCP server take the whole agent down.
                logger.warning("MCP server '%s' failed to connect, skipping: %s", name, e)

    async def _connect_one(self, cfg: dict):
        transport = cfg.get("transport", "stdio")

        if transport == "stdio":
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=cfg["command"],
                args=cfg.get("args", []),
                env=cfg.get("env") or None,
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return session

        if transport == "http":
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            headers = {}
            token = cfg.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"

            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(cfg["url"], headers=headers)
            )
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return session

        raise ValueError(f"Unsupported MCP transport '{transport}'")

    def as_llm_tools(self) -> list[dict]:
        """Tool definitions in the {name, description, input_schema} shape the
        LLM client expects, with server-qualified names."""
        return [
            {"name": t.qualified_name, "description": f"[{t.server}] {t.description}", "input_schema": t.input_schema}
            for t in self.tools.values()
        ]

    async def call_tool(self, qualified_name: str, arguments: dict):
        tool = self.tools.get(qualified_name)
        if not tool:
            raise KeyError(f"No such MCP tool: {qualified_name}")
        session = self._sessions[tool.server]
        result = await session.call_tool(tool.name, arguments)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)

    async def close(self):
        await self._stack.aclose()

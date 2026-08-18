"""Built-in tools that exist regardless of which MCP servers are configured."""
from __future__ import annotations

BUILTIN_TOOL_DEFS = [
    {
        "name": "finish_task",
        "description": "Call this once the user's task is fully complete. "
                        "Ends the agent loop and returns `summary` to the user.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "Short summary of what was done."}},
            "required": ["summary"],
        },
    },
    {
        "name": "give_up",
        "description": "Call this only if the task is truly impossible with the tools available, "
                        "after you have already tried alternative approaches. Explain why in `reason`.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]

BUILTIN_TOOL_NAMES = {t["name"] for t in BUILTIN_TOOL_DEFS}

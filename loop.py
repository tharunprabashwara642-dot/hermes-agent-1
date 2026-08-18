"""The actual agent loop.

Give it a task string. It will:
  1. Ask the LLM what to do, offering it every MCP tool + the built-ins.
  2. Execute whichever tool(s) the LLM asks for.
  3. Feed the results back in and ask again.
  4. Repeat until the model calls `finish_task`, calls `give_up`, or the
     configured `max_iterations` is hit.

Any error raised while executing a tool is caught and turned into an
observation for the model (see errors.py) instead of crashing the process,
so a single bad tool call never ends the run.
"""
from __future__ import annotations

import json
import logging
import time

from .config import Config
from .errors import run_step_with_recovery
from .llm import ChatResult, LLMClient, LLMError, ToolCall
from .mcp_manager import MCPManager
from .tools import BUILTIN_TOOL_DEFS, BUILTIN_TOOL_NAMES

logger = logging.getLogger("tharun.loop")

SYSTEM_PROMPT_TEMPLATE = """You are {name}, an autonomous task-completion agent.

Work the given task step by step using the tools available to you. Rules:
- Break the task into small verifiable steps.
- After each tool result, check whether it actually moved you closer to the goal.
- If a step fails or a tool returns an error, do NOT repeat the identical action.
  Diagnose the error, and try a different approach, different arguments, or a different tool.
- Keep going through setbacks. Only stop early by calling `give_up` if the task is
  genuinely impossible with the tools you have, and explain why.
- When (and only when) the task is fully done, call `finish_task` with a short summary.
- Be concise in your reasoning; take action rather than narrating at length.
"""


class AgentLoopResult:
    def __init__(self, success: bool, summary: str, iterations: int):
        self.success = success
        self.summary = summary
        self.iterations = iterations


class AgentLoop:
    def __init__(self, config: Config):
        self.config = config
        self.llm = LLMClient(
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
        )
        self.mcp = MCPManager(config.mcp_servers)

    async def __aenter__(self):
        await self.mcp.connect_all()
        return self

    async def __aexit__(self, *exc):
        await self.mcp.close()

    # ------------------------------------------------------------------
    async def run(self, task: str) -> AgentLoopResult:
        cfg = self.config.agent
        tools = BUILTIN_TOOL_DEFS + self.mcp.as_llm_tools()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(name=self.config.name)},
            {"role": "user", "content": task},
        ]

        for iteration in range(1, cfg.max_iterations + 1):
            logger.info("=== iteration %d/%d ===", iteration, cfg.max_iterations)

            ok, chat_or_err = await run_step_with_recovery(
                lambda: self._call_llm(messages, tools),
                context="asking the model for the next step",
                max_retries=cfg.max_retries_per_step,
                backoff_seconds=cfg.retry_backoff_seconds,
            )
            if not ok:
                # The model itself is unreachable after retries — this is the
                # one case we truly cannot route around, so we stop cleanly.
                logger.error("LLM unreachable after retries: %s", chat_or_err)
                return AgentLoopResult(False, f"Stopped: could not reach the model. {chat_or_err}", iteration)

            chat: ChatResult = chat_or_err
            messages.append({"role": "assistant", "content": chat.text or ""})

            if not chat.tool_calls:
                # Model just talked without calling a tool — nudge it to act or finish.
                messages.append({
                    "role": "user",
                    "content": "Continue the task: call a tool to make progress, or call "
                                "finish_task if it's already complete.",
                })
                continue

            finished = False
            result_summary = ""
            for call in chat.tool_calls:
                if call.name == "finish_task":
                    result_summary = call.arguments.get("summary", "Task completed.")
                    finished = True
                    break
                if call.name == "give_up":
                    reason = call.arguments.get("reason", "Unknown reason.")
                    return AgentLoopResult(False, f"Agent gave up: {reason}", iteration)

                tool_ok, tool_result = await run_step_with_recovery(
                    lambda c=call: self._execute_tool(c),
                    context=f"executing tool '{call.name}'",
                    max_retries=cfg.max_retries_per_step,
                    backoff_seconds=cfg.retry_backoff_seconds,
                )
                text_result = tool_result if tool_ok else tool_result  # error text already formatted
                messages.append({
                    "role": "user",
                    "content": f"[tool result for {call.name}]\n{text_result}",
                })

            if finished:
                return AgentLoopResult(True, result_summary, iteration)

        return AgentLoopResult(
            False,
            f"Stopped: reached max_iterations ({cfg.max_iterations}) without the model calling finish_task.",
            cfg.max_iterations,
        )

    # ------------------------------------------------------------------
    async def _call_llm(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        return self.llm.chat(messages, tools)

    async def _execute_tool(self, call: ToolCall) -> str:
        if call.name in BUILTIN_TOOL_NAMES:
            # finish_task / give_up are handled by the caller before reaching here
            return "(handled by loop)"
        return await self.mcp.call_tool(call.name, call.arguments)

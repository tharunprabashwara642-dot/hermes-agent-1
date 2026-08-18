"""Turns exceptions into recoverable conversation turns instead of crashes.

Philosophy: the agent loop should almost never die from an exception raised
while executing a step. Instead we:
  1. Catch it.
  2. Log it.
  3. Turn it into a plain-language "tool result" that explains what failed.
  4. Hand that back to the model so it can pick a different approach.
  5. Only truly give up after `max_retries_per_step` consecutive failures
     *of the same step*, and even then we surface a clear explanation
     rather than dying with a stack trace.
"""
from __future__ import annotations

import asyncio
import logging
import traceback

logger = logging.getLogger("tharun.errors")


class RecoverableError(Exception):
    """Wraps any exception encountered while running a step, with enough
    context for the model to try something else."""

    def __init__(self, original: Exception, context: str):
        self.original = original
        self.context = context
        super().__init__(str(original))

    def as_tool_result(self) -> str:
        return (
            f"ERROR while {self.context}: {type(self.original).__name__}: {self.original}\n"
            "This step failed. Do not repeat the exact same action — analyze the error above, "
            "adjust your approach (different arguments, a different tool, or an alternate strategy), "
            "and continue working toward the goal."
        )


async def run_step_with_recovery(coro_factory, context: str, max_retries: int, backoff_seconds: float):
    """Runs an async step. On failure, retries with backoff up to max_retries.
    Returns (success: bool, result_or_error_text: str)."""
    last_err_text = ""
    for attempt in range(1, max_retries + 1):
        try:
            result = await coro_factory()
            return True, result
        except Exception as e:  # noqa: BLE001 - intentionally broad: nothing should escape the loop
            logger.warning("Step failed (attempt %d/%d) while %s: %s", attempt, max_retries, context, e)
            logger.debug(traceback.format_exc())
            wrapped = RecoverableError(e, context)
            last_err_text = wrapped.as_tool_result()
            if attempt < max_retries:
                await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
    return False, last_err_text

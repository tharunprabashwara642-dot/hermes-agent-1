#!/usr/bin/env python3
"""Entry point for Tharun AI Assistant.

Usage:
    python main.py "your task here"
    TASK="your task here" python main.py
    python main.py --serve            # keep the process alive, waiting for tasks

Config is read from CONFIG_PATH (default /opt/data/config.yaml).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from agent.config import Config
from agent.loop import AgentLoop

DEFAULT_CONFIG_PATH = os.environ.get("CONFIG_PATH", "/opt/data/config.yaml")


def setup_logging(log_file: str):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)],
    )


async def run_once(config: Config, task: str) -> int:
    async with AgentLoop(config) as loop:
        result = await loop.run(task)
        status = "DONE" if result.success else "STOPPED"
        print(f"\n[{status} after {result.iterations} iteration(s)]\n{result.summary}")
        return 0 if result.success else 1


async def serve(config: Config):
    """Simple stdin-driven task queue: each line typed in is run as a task,
    the process itself never exits on task failure — it just waits for the next one."""
    print(f"{config.name} is ready. Type a task and press Enter (Ctrl+D to quit).")
    async with AgentLoop(config) as loop:
        while True:
            try:
                task = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            except (EOFError, KeyboardInterrupt):
                break
            task = (task or "").strip()
            if not task:
                if task == "":
                    continue
                break
            try:
                result = await loop.run(task)
                status = "DONE" if result.success else "STOPPED"
                print(f"[{status}] {result.summary}")
            except Exception as e:  # belt-and-braces: serve mode must never die
                logging.getLogger("tharun.main").error("Unhandled error running task: %s", e)
                print(f"[ERROR] task failed unexpectedly, ready for next task: {e}")


def main():
    parser = argparse.ArgumentParser(description="Tharun AI Assistant")
    parser.add_argument("task", nargs="?", default=None, help="Task to run once, then exit")
    parser.add_argument("--serve", action="store_true", help="Stay running, accept tasks from stdin")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config.yaml")
    args = parser.parse_args()

    config = Config.load(args.config)
    setup_logging(config.agent.log_file)

    task = args.task or os.environ.get("TASK")

    if args.serve or not task:
        asyncio.run(serve(config))
        return

    sys.exit(asyncio.run(run_once(config, task)))


if __name__ == "__main__":
    main()

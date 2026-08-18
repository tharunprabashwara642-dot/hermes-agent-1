# Tharun AI Assistant (තරුන්ගෙ AI Assistant)

A self-hosted AI agent that runs tasks in a loop until they're actually done —
and if a step fails, it tries a different approach instead of stopping.

## What's different from the old template

- **Real agent loop.** Give it a task; it keeps calling tools and checking
  progress across multiple iterations until it calls `finish_task`
  (or hits a safety-net `max_iterations` cap).
- **Self-healing errors.** Any exception from a tool call or a flaky API
  request is caught, logged, and turned into feedback for the model
  ("this failed, try something else") instead of crashing the process.
  It retries with backoff a few times before giving up on *that step only*.
- **MCP support with tokens.** Configure any number of MCP servers
  (local `stdio` processes or remote `http` servers with a bearer token)
  in `config.yaml`, and every tool they expose becomes available to the
  agent automatically.
- **Multi-provider LLM client.** Works with OpenAI, Anthropic, Gemini,
  OpenRouter, or any OpenAI-compatible endpoint — just change `provider`
  and `model` in the config.

## Configure

1. Copy `config.example.yaml` to `/opt/data/config.yaml` (the container does
   this automatically on first boot).
2. Set your model provider's API key as an environment variable
   (e.g. `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
3. Add/enable MCP servers under `mcp_servers:`. For a remote server that
   needs auth, set `token: ${YOUR_ENV_VAR}` and export that variable —
   tokens are never hard-coded into the config file.

## Run

```bash
docker build -t tharun-ai-assistant .
docker run -it --rm \
  -v ~/.tharun:/opt/data \
  -e GEMINI_API_KEY=your-key-here \
  tharun-ai-assistant
```

This starts the agent in `--serve` mode: type a task at the prompt and press
Enter. It will keep working the task in a loop and print `[DONE]` or
`[STOPPED]` with a summary when it finishes (or safely gives up).

You can also run a single task and exit:

```bash
python main.py "Summarize the latest 3 files in /opt/data/notes"
```

## Deploy on Railway

`railway.toml` points at the included `Dockerfile`. Set your provider's API
key and any MCP tokens as environment variables in the Railway service
settings, attach a persistent volume at `/opt/data`, and deploy.

## Project layout

```
main.py                 entry point (CLI / --serve loop)
agent/config.py         loads config.yaml, expands ${ENV_VARS}
agent/llm.py             provider-agnostic chat + tool-calling client
agent/mcp_manager.py     connects to MCP servers, exposes their tools
agent/tools.py           built-in tools (finish_task, give_up)
agent/loop.py            the actual agent loop + error recovery
agent/errors.py          turns exceptions into retryable model feedback
```

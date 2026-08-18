"""A thin, provider-agnostic chat + tool-calling client.

Normalizes every provider around one internal message/tool shape so the
agent loop never has to care which backend it's talking to:

    messages = [{"role": "user"|"assistant"|"tool", "content": str, ...}]
    tools    = [{"name": str, "description": str, "input_schema": {...}}]

Returns a ChatResult with .text and .tool_calls (list of {id, name, arguments}).
"""
from __future__ import annotations

import json
import requests
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    """Raised for any transport/parsing failure talking to the model provider."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str | None,
                 base_url: str | None = None, temperature: float = 0.4,
                 timeout: int = 120):
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.timeout = timeout

        if not self.api_key and self.provider != "custom":
            raise LLMError(
                f"No API key configured for provider '{self.provider}'. "
                "Set it in config.yaml (via an ${ENV_VAR}) or as an environment variable."
            )

    # ------------------------------------------------------------------
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        tools = tools or []
        try:
            if self.provider in ("openai", "openrouter", "custom"):
                return self._chat_openai_style(messages, tools)
            if self.provider == "anthropic":
                return self._chat_anthropic(messages, tools)
            if self.provider == "gemini":
                return self._chat_gemini(messages, tools)
            raise LLMError(f"Unknown provider '{self.provider}'")
        except requests.RequestException as e:
            raise LLMError(f"Network error talking to {self.provider}: {e}") from e

    # ------------------------------------------------------------------
    def _chat_openai_style(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        url = self.base_url or PROVIDER_ENDPOINTS.get(self.provider)
        if not url:
            raise LLMError("provider 'custom' requires base_url in config.yaml")

        oa_tools = [
            {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                               "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
            for t in tools
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if oa_tools:
            payload["tools"] = oa_tools

        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise LLMError(f"{self.provider} API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected {self.provider} response shape: {data}") from e

        result = ChatResult(text=choice.get("content") or "", raw=data)
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result.tool_calls.append(ToolCall(id=tc.get("id", ""), name=tc["function"]["name"], arguments=args))
        return result

    # ------------------------------------------------------------------
    def _chat_anthropic(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        system = ""
        conv = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            else:
                conv.append(m)

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": self.temperature,
            "messages": conv,
        }
        if system:
            payload["system"] = system.strip()
        if tools:
            payload["tools"] = [
                {"name": t["name"], "description": t.get("description", ""),
                 "input_schema": t.get("input_schema", {"type": "object", "properties": {}})}
                for t in tools
            ]

        resp = requests.post(
            PROVIDER_ENDPOINTS["anthropic"],
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise LLMError(f"anthropic API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()

        result = ChatResult(raw=data)
        for block in data.get("content", []):
            if block["type"] == "text":
                result.text += block["text"]
            elif block["type"] == "tool_use":
                result.tool_calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input", {})))
        return result

    # ------------------------------------------------------------------
    def _chat_gemini(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        url = PROVIDER_ENDPOINTS["gemini"].format(model=self.model) + f"?key={self.api_key}"

        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [
                {"name": t["name"], "description": t.get("description", ""),
                 "parameters": t.get("input_schema", {"type": "object", "properties": {}})}
                for t in tools
            ]}]

        resp = requests.post(url, json=payload, timeout=self.timeout)
        if resp.status_code >= 400:
            raise LLMError(f"gemini API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()

        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected gemini response shape: {data}") from e

        result = ChatResult(raw=data)
        call_id = 0
        for part in parts:
            if "text" in part:
                result.text += part["text"]
            elif "functionCall" in part:
                call_id += 1
                fc = part["functionCall"]
                result.tool_calls.append(ToolCall(id=f"call_{call_id}", name=fc["name"], arguments=fc.get("args", {})))
        return result

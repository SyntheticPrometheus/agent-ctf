"""One model call, two providers, one shape.

`harness/agent.py` was written against the Anthropic Messages API; this host has no Anthropic key
(it has an OpenRouter one), so the loop could not make a real match. Everything provider-specific
lives here: the request, the tool-schema translation, and the response translated BACK into the
Anthropic block shape the loop already consumes — so agent.py keeps one code path.

    CTF_PROVIDER=auto|anthropic|openrouter     (auto: anthropic key -> anthropic, else openrouter)
    CTF_MODEL=...                              (default: claude-haiku-4.5 on openrouter)

Measured 2026-11-24: one OpenRouter call with the agent's own shell schema returned a tool call
(`shell {"command": "whoami"}`), cost $0.000852, 640 tokens.
"""
from __future__ import annotations

import json
import os
import types
import urllib.error
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def provider() -> str:
    want = os.environ.get("CTF_PROVIDER", "auto").strip().lower()
    if want in ("anthropic", "openrouter"):
        return want
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "openrouter"


def openrouter_key() -> str:
    """The key from pi's auth store, never from a file this package owns."""
    path = os.environ.get("PI_AUTH", os.path.expanduser("~/.pi/agent/auth.json"))
    with open(path) as f:
        return json.load(f)["openrouter"]["key"]


def to_openai_tools(tool_schema: list) -> list:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}}
            for t in tool_schema]


def _f(block, key, default=None):
    """Blocks arrive as dicts (seed messages) and as the SimpleNamespace objects to_anthropic makes
    (everything the loop appends back). Reading one shape crashed the first live match."""
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def to_openai_messages(system: str, messages: list) -> list:
    """Anthropic blocks -> OpenAI messages. Tool results become role=tool messages."""
    out = [{"role": "system", "content": system}]
    for m in messages:
        role = _f(m, "role")
        content = _f(m, "content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "".join(_f(b, "text", "") or "" for b in content
                           if _f(b, "type") == "text")
            calls = [{"id": _f(b, "id"), "type": "function",
                      "function": {"name": _f(b, "name"),
                                   "arguments": json.dumps(_f(b, "input") or {})}}
                     for b in content if _f(b, "type") == "tool_use"]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:                                   # user turn carrying tool_results
            for b in content:
                if _f(b, "type") == "tool_result":
                    body = _f(b, "content")
                    out.append({"role": "tool", "tool_call_id": _f(b, "tool_use_id"),
                                "content": body if isinstance(body, str) else json.dumps(body)})
                elif _f(b, "type") == "text":
                    out.append({"role": "user", "content": _f(b, "text")})
    return out


def to_anthropic(resp: dict) -> types.SimpleNamespace:
    """OpenAI completion -> the shape agent._act/_text_of already read."""
    choice = resp["choices"][0]["message"]
    blocks = []
    if choice.get("content"):
        blocks.append(types.SimpleNamespace(type="text", text=choice["content"]))
    for call in choice.get("tool_calls") or []:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        blocks.append(types.SimpleNamespace(type="tool_use", id=call.get("id") or "call_0",
                                            name=fn.get("name"), input=args))
    if not blocks:                              # never hand the loop an empty response
        blocks.append(types.SimpleNamespace(type="text", text=""))
    return types.SimpleNamespace(content=blocks, stop_reason=resp["choices"][0].get("finish_reason"),
                                 model=resp.get("model"), usage=resp.get("usage"))


def openrouter_turn(system: str, messages: list, tool_schema: list,
                    model: str | None = None, max_tokens: int = 2048, timeout: int = 120):
    model = model or os.environ.get("CTF_MODEL", "anthropic/claude-haiku-4.5")
    body = {"model": model, "max_tokens": max_tokens,
            "messages": to_openai_messages(system, messages),
            "tools": to_openai_tools(tool_schema)}
    req = urllib.request.Request(OPENROUTER_URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {openrouter_key()}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"openrouter {e.code}: {e.read()[:300]!r}") from e
    return to_anthropic(resp)

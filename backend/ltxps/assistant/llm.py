"""Chat-model client. Talks to any OpenAI-compatible server or Anthropic-style server and streams the reply."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

PRESETS: dict[str, dict[str, Any]] = {
    "ollama": {"name": "Ollama (on this PC)", "style": "openai", "base_url": "http://127.0.0.1:11434/v1", "needs_key": False, "model": "llama3.2",
               "help": "Free and private. Install Ollama, then run “ollama pull llama3.2”."},
    "lmstudio": {"name": "LM Studio (on this PC)", "style": "openai", "base_url": "http://127.0.0.1:1234/v1", "needs_key": False, "model": "",
                 "help": "Free and private. Start the local server in LM Studio."},
    "pollinations": {"name": "Free online AI (no sign-up)", "style": "openai", "base_url": "https://text.pollinations.ai/openai", "needs_key": False, "model": "openai",
                     "help": "Nothing to install and no key. Needs internet; can be slow or busy at times. What you type is sent to a public service."},
    "openrouter": {"name": "OpenRouter", "style": "openai", "base_url": "https://openrouter.ai/api/v1", "needs_key": True, "model": "meta-llama/llama-3.3-70b-instruct:free",
                   "help": "Has free models. Get a key at openrouter.ai/keys."},
    "nvidia": {"name": "NVIDIA NIM", "style": "openai", "base_url": "https://integrate.api.nvidia.com/v1", "needs_key": True, "model": "meta/llama-3.3-70b-instruct",
               "help": "Free credits. Get a key at build.nvidia.com."},
    "groq": {"name": "Groq", "style": "openai", "base_url": "https://api.groq.com/openai/v1", "needs_key": True, "model": "llama-3.3-70b-versatile",
             "help": "Fast, with a free tier. Get a key at console.groq.com."},
    "gemini": {"name": "Google Gemini", "style": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "needs_key": True,
               "model": "gemini-2.5-flash", "help": "Free tier. Get a key at aistudio.google.com/apikey. Can also read pictures."},
    "openai": {"name": "OpenAI", "style": "openai", "base_url": "https://api.openai.com/v1", "needs_key": True, "model": "gpt-4o-mini", "help": "Paid. platform.openai.com."},
    "anthropic": {"name": "Anthropic Claude", "style": "anthropic", "base_url": "https://api.anthropic.com", "needs_key": True, "model": "claude-sonnet-5-5",
                  "help": "Paid, pay per use. Create a key at console.anthropic.com → API keys. The model name can be changed (for example claude-opus-5-5 for the strongest, claude-haiku-5-5 for the cheapest)."},
    "fcc": {"name": "free-claude-code proxy", "style": "anthropic", "base_url": "http://127.0.0.1:8082", "needs_key": False, "model": "claude-sonnet-5-5",
            "help": "Run the free-claude-code proxy yourself (default port 8082); it routes Claude-style requests to free providers. Enter its auth token if you set one."},
    "custom": {"name": "Other (OpenAI-compatible)", "style": "openai", "base_url": "", "needs_key": False, "model": "", "help": "Any server that speaks the OpenAI chat API."},
}


class LLMError(RuntimeError):
    """A problem the person can understand and fix."""


@dataclass
class LLMConfig:
    provider: str = "ollama"
    style: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.6
    max_tokens: int = 4096
    timeout: float = 120.0
    json_mode: bool = False  # ask OpenAI-style servers for a JSON-only answer


def config_from(provider: str, saved: dict[str, Any]) -> LLMConfig:
    p = PRESETS.get(provider, PRESETS["custom"])
    mine = saved.get(provider, {}) if isinstance(saved.get(provider), dict) else {}
    return LLMConfig(provider=provider, style=mine.get("style") or p["style"], base_url=(mine.get("base_url") or p["base_url"]).rstrip("/"),
                     api_key=mine.get("api_key", ""), model=mine.get("model") or p["model"])


def _headers(cfg: LLMConfig) -> dict[str, str]:
    if cfg.style == "anthropic":
        h = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
        if cfg.api_key:
            h["x-api-key"] = cfg.api_key
            h["authorization"] = f"Bearer {cfg.api_key}"
        return h
    h = {"content-type": "application/json"}
    if cfg.api_key:
        h["authorization"] = f"Bearer {cfg.api_key}"
    return h


def explain(cfg: LLMConfig, exc: Exception | None = None, resp: httpx.Response | None = None, body: str = "") -> LLMError:
    name = PRESETS.get(cfg.provider, {}).get("name", cfg.provider)
    local = cfg.base_url.startswith(("http://127.", "http://localhost"))
    if resp is not None:
        code = resp.status_code
        detail = ""
        try:
            j = json.loads(body or resp.text)
            e = j.get("error", j) if isinstance(j, dict) else {}
            detail = (e.get("message") if isinstance(e, dict) else str(e)) or ""
        except (ValueError, AttributeError):
            detail = (body or "")[:200]
        if code in (401, 403):
            return LLMError(f"{name} did not accept the API key. Open Settings, check the key for {name} and try again.")
        if code == 404:
            return LLMError(f"{name} does not know the model “{cfg.model}”. " + ("Run “ollama pull " + cfg.model + "” or pick another model in Settings." if cfg.provider == "ollama" else "Pick another model in Settings."))
        if code == 429:
            return LLMError(f"{name} says you are sending too many requests or are out of free quota. Wait a minute or switch provider in Settings.")
        if code == 402:
            return LLMError(f"{name} needs credit on the account.")
        if code >= 500:
            return LLMError(f"{name} had a server problem ({code}). Try again shortly. {detail[:160]}".strip())
        return LLMError(f"{name} refused the request ({code}). {detail[:200]}".strip())
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        if local:
            hint = {"ollama": "Start Ollama and try again.", "lmstudio": "Start the local server in LM Studio.", "fcc": "Start the free-claude-code proxy."}.get(cfg.provider, "Start that program and try again.")
            return LLMError(f"Cannot reach {name} at {cfg.base_url}. {hint}")
        return LLMError(f"Cannot reach {name}. Check your internet connection.")
    if isinstance(exc, httpx.ReadTimeout):
        return LLMError(f"{name} took too long to answer. Try a smaller/faster model or a shorter request.")
    if isinstance(exc, (httpx.InvalidURL, httpx.UnsupportedProtocol)):
        return LLMError(f"The address “{cfg.base_url}” for {name} is not valid. Fix it in Settings.")
    return LLMError(f"Could not talk to {name}: {exc}")


def _content(cfg: LLMConfig, m: dict[str, Any]) -> Any:
    """Plain text, or text plus pictures (a message may carry "images": [{"media_type", "data"}])."""
    imgs = m.get("images") or []
    if not imgs:
        return m["content"]
    if cfg.style == "anthropic":
        return [{"type": "image", "source": {"type": "base64", "media_type": i["media_type"], "data": i["data"]}} for i in imgs] + [{"type": "text", "text": m["content"]}]
    return [{"type": "text", "text": m["content"]}] + [{"type": "image_url", "image_url": {"url": f"data:{i['media_type']};base64,{i['data']}"}} for i in imgs]


def _prepare(cfg: LLMConfig, messages: list[dict[str, Any]], system: str) -> tuple[str, dict[str, Any]]:
    msgs = [{"role": m["role"], "content": _content(cfg, m)} for m in messages if m.get("content") and m["role"] in ("user", "assistant")]
    if cfg.style == "anthropic":
        merged: list[dict[str, str]] = []
        for m in msgs:  # the API requires strictly alternating turns that start with the user
            if merged and merged[-1]["role"] == m["role"] and isinstance(merged[-1]["content"], str) and isinstance(m["content"], str):
                merged[-1]["content"] += "\n\n" + m["content"]
            else:
                merged.append(dict(m))
        while merged and merged[0]["role"] != "user":
            merged.pop(0)
        body: dict[str, Any] = {"model": cfg.model, "max_tokens": cfg.max_tokens, "temperature": cfg.temperature, "messages": merged, "stream": True}
        if system:
            body["system"] = system
        return cfg.base_url + "/v1/messages", body
    full = ([{"role": "system", "content": system}] if system else []) + msgs
    out: dict[str, Any] = {"model": cfg.model, "messages": full, "temperature": cfg.temperature, "max_tokens": cfg.max_tokens, "stream": True}
    if cfg.json_mode:
        out["response_format"] = {"type": "json_object"}
    return cfg.base_url + "/chat/completions", out


def parse_event(style: str, data: dict[str, Any]) -> str:
    """The text carried by one streamed event (empty for events that carry none)."""
    if style == "anthropic":
        if data.get("type") == "content_block_delta":
            d = data.get("delta") or {}
            return d.get("text", "") if d.get("type", "text_delta") == "text_delta" else ""
        if data.get("type") == "error":
            raise LLMError("The model reported an error: " + str((data.get("error") or {}).get("message", data)))
        return ""
    for ch in data.get("choices") or []:
        d = ch.get("delta") or ch.get("message") or {}
        c = d.get("content")
        if isinstance(c, str):
            return c
    if isinstance(data.get("error"), dict):
        raise LLMError("The model reported an error: " + str(data["error"].get("message", data["error"])))
    return ""


def stream_chat(cfg: LLMConfig, messages: list[dict[str, Any]], system: str = "") -> Iterator[str]:
    if not cfg.base_url:
        raise LLMError("No server address is set. Open Settings and choose a provider.")
    if not cfg.model:
        raise LLMError("No model is chosen. Open Settings and pick or type a model name.")
    url, body = _prepare(cfg, messages, system)
    if not body["messages"] or (cfg.style == "anthropic" and not body["messages"]):
        raise LLMError("There is nothing to send yet.")
    try:
        with httpx.Client(timeout=httpx.Timeout(cfg.timeout, connect=8.0)) as client:
            with client.stream("POST", url, headers=_headers(cfg), json=body) as r:
                if r.status_code >= 400:
                    r.read()
                    raise explain(cfg, resp=r, body=r.text)
                got = False
                for line in r.iter_lines():
                    line = line.strip()
                    if not line or line.startswith(("event:", ":")):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    t = parse_event(cfg.style, data)
                    if t:
                        got = True
                        yield t
                if not got:
                    raise LLMError("The model returned an empty answer. Try again or choose another model.")
    except LLMError:
        raise
    except httpx.HTTPError as exc:
        raise explain(cfg, exc=exc) from exc


def complete(cfg: LLMConfig, messages: list[dict[str, Any]], system: str = "") -> str:
    return "".join(stream_chat(cfg, messages, system))


def list_models(cfg: LLMConfig) -> list[str]:
    if not cfg.base_url:
        raise LLMError("No server address is set.")
    url = cfg.base_url + ("/v1/models" if cfg.style == "anthropic" else "/models")
    try:
        r = httpx.get(url, headers=_headers(cfg), timeout=httpx.Timeout(15.0, connect=5.0))
    except httpx.HTTPError as exc:
        raise explain(cfg, exc=exc) from exc
    if r.status_code >= 400:
        raise explain(cfg, resp=r)
    try:
        j = r.json()
        items = j.get("data") or j.get("models") or []
        ids = [str(i.get("id") or i.get("name", "")).removeprefix("models/") for i in items if isinstance(i, dict)]
    except ValueError:
        ids = []
    return sorted({i for i in ids if i})


def test_connection(cfg: LLMConfig) -> dict[str, Any]:
    text = complete(LLMConfig(**{**cfg.__dict__, "max_tokens": 16, "timeout": 40.0}), [{"role": "user", "content": "Reply with the single word: ready"}])
    return {"ok": True, "reply": text.strip()[:80]}

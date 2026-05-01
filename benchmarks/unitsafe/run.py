#!/usr/bin/env python3
"""UnitSafe benchmark runner.

Evaluates language models on the 500-problem UnitSafe metrological
reasoning benchmark.  Supports Claude and Ollama backends, a configurable
judge model for format-agnostic answer extraction, and optional MCP
tool-augmented evaluation.

Usage examples
--------------
# Bare Claude evaluation
python run.py -m claude:claude-sonnet-4-20250514

# Ollama model evaluated, Claude as judge
python run.py -m ollama:llama3.2:3b --judge claude:claude-haiku-4-5-20251001

# Tool-augmented, remote MCP server
python run.py -m claude:claude-haiku-4-5-20251001 --tools --mcp-url https://mcp.ucon.dev/mcp/inst_abc/mcp

# Quick 10-problem smoke test
python run.py -m claude:claude-haiku-4-5-20251001 --tools --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger("unitsafe")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation made by the model."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """Result returned after executing a tool call."""
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """Normalised model response."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Extraction:
    """Structured answer extracted by the judge."""
    value: float | None = None
    unit: str | None = None
    refused: bool = False
    refusal_reason: str | None = None


@dataclass
class EvalResult:
    """Full result for a single problem."""
    problem: dict[str, Any]
    model: str
    condition: str
    model_response: str
    extraction: Extraction
    score_numerical: bool
    score_unit: bool
    score_refusal: bool
    score_overall: bool
    tool_calls: list[dict[str, Any]]
    n_tool_calls: int
    latency_ms: float
    error: str | None = None


# ---------------------------------------------------------------------------
# Model backends
# ---------------------------------------------------------------------------

@runtime_checkable
class ModelBackend(Protocol):
    """Unified async interface for model inference."""

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> Message: ...


class ClaudeBackend:
    """Wraps ``anthropic.AsyncAnthropic``."""

    def __init__(self, model: str):
        import anthropic
        self.client = anthropic.AsyncAnthropic()
        self.model = model

    async def preflight(self) -> None:
        """Verify the Claude API is reachable and the model exists."""
        try:
            await self.client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        except Exception as exc:
            raise RuntimeError(
                f"Claude preflight failed for model {self.model!r}: {exc}"
            ) from exc

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> Message:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        log.debug("claude request model=%s messages=%d tools=%d",
                  self.model, len(messages), len(tools or []))
        resp = await self.client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        log.debug("claude response text_len=%d tool_calls=%d usage=%s",
                  sum(len(t) for t in text_parts), len(tool_calls),
                  getattr(resp, "usage", None))
        return Message(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
        )


class OllamaBackend:
    """Wraps ``ollama.Client`` with queue-based async bridge."""

    def __init__(self, model: str, *, num_ctx: int | None = None, show_thinking: bool = False, think: bool = True):
        self.model = model
        self.num_ctx = num_ctx
        self.show_thinking = show_thinking
        self.think = think

    async def preflight(self) -> None:
        """Verify Ollama is running and the model is available."""
        import ollama

        try:
            models = await asyncio.to_thread(ollama.list)
        except Exception as exc:
            raise RuntimeError(
                f"Ollama preflight failed — is the server running? {exc}"
            ) from exc

        available = [m.model for m in models.models]
        if not any(
            m == self.model or m.startswith(self.model + ":")
            for m in available
        ):
            raise RuntimeError(
                f"Model {self.model!r} not found in Ollama. "
                f"Available: {', '.join(available) or '(none)'}. "
                f"Pull it with:  ollama pull {self.model}"
            )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        tool_choice: dict[str, Any] | None = None,  # ignored by Ollama
    ) -> Message:
        import ollama

        ollama_msgs: list[dict[str, Any]] = []
        if system:
            ollama_msgs.append({"role": "system", "content": system})

        for m in messages:
            if m["role"] == "tool":
                ollama_msgs.append({
                    "role": "tool",
                    "content": m.get("content", ""),
                })
            elif m["role"] == "assistant" and "tool_calls" in m:
                ollama_msgs.append(m)
            else:
                ollama_msgs.append({
                    "role": m["role"],
                    "content": m.get("content", ""),
                })

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_msgs,
        }
        if not self.think:
            kwargs["think"] = False
        if self.num_ctx:
            kwargs["options"] = {"num_ctx": self.num_ctx}
        if tools:
            ollama_tools = _to_ollama_tools(tools)
            if ollama_tools:
                kwargs["tools"] = ollama_tools

        log.debug("ollama request model=%s messages=%d tools=%d",
                  self.model, len(ollama_msgs), len(kwargs.get("tools", [])))

        text_chunks: list[str] = []
        raw_tool_calls: list[Any] = []
        token_count = 0
        thinking_count = 0
        first_token_at: float | None = None
        t_start = time.monotonic()
        show = self.show_thinking
        in_thinking = False

        # Use a queue to bridge sync streaming thread → async event loop.
        # This lets the heartbeat run between chunks AND lets asyncio
        # cancellation close the HTTP client to stop the thread.
        import queue
        _SENTINEL = object()
        chunk_q: queue.Queue = queue.Queue()
        sync_client = ollama.Client()

        def _stream_thread() -> None:
            try:
                for chunk in sync_client.chat(**kwargs, stream=True):
                    chunk_q.put(chunk)
                chunk_q.put(_SENTINEL)
            except Exception as exc:
                chunk_q.put(exc)

        thread = __import__("threading").Thread(target=_stream_thread, daemon=True)
        thread.start()

        if show:
            print("       ┌── model output ──", file=sys.stderr, flush=True)

        # Consume chunks from the queue with periodic heartbeats
        heartbeat_interval = 10
        try:
            while True:
                try:
                    item = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: chunk_q.get(timeout=heartbeat_interval),
                    )
                except Exception:
                    # queue.Empty on timeout — print heartbeat
                    elapsed = time.monotonic() - t_start
                    if token_count == 0 and thinking_count == 0:
                        print(
                            f"       Still waiting for model... ({elapsed:.0f}s elapsed)",
                            file=sys.stderr, flush=True,
                        )
                    elif thinking_count > 0 and token_count == 0 and not show:
                        print(
                            f"       Still thinking... ({elapsed:.0f}s, {thinking_count} thinking tokens so far)",
                            file=sys.stderr, flush=True,
                        )
                    continue

                if item is _SENTINEL:
                    break
                if isinstance(item, Exception):
                    raise item

                chunk = item
                msg = chunk.message
                thinking = getattr(msg, "thinking", None) or ""
                token = msg.content or ""

                if thinking:
                    thinking_count += 1
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                        if show:
                            print("       (thinking) ", end="", file=sys.stderr, flush=True)
                        else:
                            wait = first_token_at - t_start
                            print(
                                f"       Model is thinking... (first token after {wait:.1f}s)",
                                file=sys.stderr,
                                flush=True,
                            )
                        in_thinking = True
                    if show:
                        print(thinking, end="", file=sys.stderr, flush=True)

                if token:
                    if in_thinking and show:
                        print(
                            f"\n       (done thinking, {thinking_count} tokens)",
                            file=sys.stderr,
                            flush=True,
                        )
                        print("       ", end="", file=sys.stderr, flush=True)
                        in_thinking = False
                    text_chunks.append(token)
                    token_count += 1
                    if show:
                        print(token, end="", file=sys.stderr, flush=True)
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                        if not show:
                            wait = first_token_at - t_start
                            print(
                                f"       First token after {wait:.1f}s, generating...",
                                file=sys.stderr,
                                flush=True,
                            )
                    if not show and token_count % 100 == 0:
                        elapsed = time.monotonic() - first_token_at
                        tps = token_count / elapsed if elapsed > 0 else 0
                        print(
                            f"       ... {token_count} tokens ({tps:.0f} tok/s)",
                            file=sys.stderr,
                            flush=True,
                        )

                tc = getattr(msg, "tool_calls", None)
                if tc:
                    raw_tool_calls.extend(tc)
        except (asyncio.CancelledError, Exception):
            # On cancellation (timeout), close the sync client's httpx session
            # to abort the in-flight HTTP request and unblock the thread
            try:
                sync_client._client.close()
            except Exception:
                pass
            raise

        text = "".join(text_chunks) or None
        elapsed = time.monotonic() - t_start
        total_tokens = token_count + thinking_count
        thinking_note = f" ({thinking_count} thinking + {token_count} content)" if thinking_count > 0 else ""
        if show and total_tokens > 0:
            print(
                f"\n       └── {total_tokens} tokens in {elapsed:.1f}s{thinking_note}",
                file=sys.stderr,
                flush=True,
            )
        elif total_tokens > 0:
            gen_time = elapsed - ((first_token_at or t_start) - t_start)
            tps = total_tokens / gen_time if gen_time > 0 else 0
            print(
                f"       Done: {total_tokens} tokens in {elapsed:.1f}s ({tps:.0f} tok/s){thinking_note}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                f"       Model returned empty response after {elapsed:.1f}s",
                file=sys.stderr,
                flush=True,
            )

        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(raw_tool_calls):
            fn = tc.get("function", {})
            tool_calls.append(
                ToolCall(
                    id=f"ollama-{i}",
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments", {}),
                )
            )

        return Message(text=text, tool_calls=tool_calls)


class ClaudeCodeBackend:
    """Wraps the ``claude`` CLI via subprocess for users with a Claude Code subscription."""

    def __init__(self, model: str | None = None):
        self.model = model  # None → use CLI default

    async def preflight(self) -> None:
        """Verify the claude CLI is installed and responsive."""
        proc = await asyncio.create_subprocess_exec(
            "claude", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"'claude' CLI not found or not working: {stderr.decode().strip()}"
            )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        tool_choice: dict[str, Any] | None = None,  # not supported via CLI
    ) -> Message:
        # Build the prompt from messages — claude -p takes a single text prompt
        parts: list[str] = []
        if system:
            parts.append(system)
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, list):
                # Flatten content blocks
                content = "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            if content:
                parts.append(content)

        prompt = "\n\n".join(parts)

        cmd = ["claude", "-p", prompt, "--output-format", "text"]
        if self.model:
            cmd.extend(["--model", self.model])

        log.debug("claude-code request model=%s prompt_len=%d",
                  self.model or "(default)", len(prompt))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise

        if proc.returncode != 0:
            err = stderr.decode().strip()
            log.warning("claude-code exit=%d stderr=%s", proc.returncode, err)
            return Message(text=f"[claude-code error: {err}]")

        text = stdout.decode().strip()
        log.debug("claude-code response text_len=%d", len(text))
        return Message(text=text)


def _to_ollama_tools(
    claude_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Claude-format tool definitions to Ollama function-calling format."""
    result = []
    for t in claude_tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        })
    return result


def make_backend(
    spec: str,
    *,
    num_ctx: int | None = None,
    show_thinking: bool = False,
    think: bool = True,
) -> ModelBackend:
    """Parse a ``backend:model`` spec and return the corresponding backend.

    Specs use ``backend:model`` format.  For ``claude-code``, the model
    portion is optional (uses CLI default when omitted).
    """
    backend, _, model = spec.partition(":")
    backend = backend.lower()

    if backend == "claude-code":
        return ClaudeCodeBackend(model or None)

    if not model:
        raise ValueError(
            f"Invalid model spec {spec!r} — expected 'backend:model' "
            "(e.g. 'claude:claude-haiku-4-5-20251001', 'ollama:llama3.2:3b', "
            "or 'claude-code' / 'claude-code:claude-sonnet-4-20250514')"
        )
    if backend == "claude":
        return ClaudeBackend(model)
    elif backend == "ollama":
        return OllamaBackend(model, num_ctx=num_ctx, show_thinking=show_thinking, think=think)
    else:
        raise ValueError(
            f"Unknown backend {backend!r} — supported: claude, claude-code, ollama"
        )


# ---------------------------------------------------------------------------
# MCP tool bridge
# ---------------------------------------------------------------------------

class MCPToolBridge:
    """Bridges model tool calls to an MCP server.

    Lazily imports ``mcp`` so the dependency is only needed when ``--tools``
    is passed.
    """

    def __init__(self) -> None:
        self._session: Any = None
        self._read: Any = None
        self._write: Any = None
        self._tools: list[dict[str, Any]] = []
        self._cm: Any = None
        self._session_cm: Any = None

    async def connect_stdio(
        self, command: str, args: list[str] | None = None, *, timeout: float = 30,
    ) -> None:
        if not shutil.which(command):
            raise RuntimeError(
                f"MCP server command {command!r} not found on PATH. "
                f"Install it with:  uv sync --extra mcp"
            )

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=command, args=args or [])
        self._cm = stdio_client(params)
        try:
            self._read, self._write = await asyncio.wait_for(
                self._cm.__aenter__(), timeout=timeout,
            )
            self._session_cm = ClientSession(self._read, self._write)
            self._session = await asyncio.wait_for(
                self._session_cm.__aenter__(), timeout=timeout,
            )
            await asyncio.wait_for(self._session.initialize(), timeout=timeout)
            await asyncio.wait_for(self._fetch_tools(), timeout=timeout)
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError(
                f"MCP server {command!r} did not respond within {timeout}s. "
                f"Verify it starts correctly by running: {command}"
            )

    async def connect_url(
        self, url: str, *, api_key: str | None = None, timeout: float = 30,
    ) -> None:
        """Connect to a remote MCP server.

        Tries Streamable HTTP first, falls back to SSE.
        """
        headers: dict[str, str] | None = None
        if api_key:
            headers = {"Authorization": f"Bearer {api_key}"}

        # Try Streamable HTTP first (default for mcp SDK >=1.8)
        try:
            await self._connect_streamable_http(url, headers=headers, timeout=timeout)
            return
        except Exception as streamable_err:
            log.debug("Streamable HTTP failed: %s — falling back to SSE", streamable_err)
            # Reset any partial state
            await self.close()
            self._session = None
            self._read = None
            self._write = None
            self._cm = None
            self._session_cm = None

        # Fall back to SSE
        try:
            await self._connect_sse(url, headers=headers, timeout=timeout)
        except Exception as sse_err:
            raise RuntimeError(
                f"Could not connect to MCP server at {url}. "
                f"Streamable HTTP failed: {streamable_err}  |  SSE failed: {sse_err}"
            ) from sse_err

    async def _connect_streamable_http(
        self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 30,
    ) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._cm = streamablehttp_client(url, headers=headers)
        try:
            read, write, _get_session_id = await asyncio.wait_for(
                self._cm.__aenter__(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError(f"Streamable HTTP server at {url} did not respond within {timeout}s")

        self._read, self._write = read, write
        self._session_cm = ClientSession(self._read, self._write)
        try:
            self._session = await asyncio.wait_for(
                self._session_cm.__aenter__(), timeout=timeout,
            )
            await asyncio.wait_for(self._session.initialize(), timeout=timeout)
            await asyncio.wait_for(self._fetch_tools(), timeout=timeout)
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError(f"MCP session init timed out after {timeout}s")

    async def _connect_sse(
        self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 30,
    ) -> None:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        self._cm = sse_client(url, headers=headers)
        try:
            self._read, self._write = await asyncio.wait_for(
                self._cm.__aenter__(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError(f"SSE server at {url} did not respond within {timeout}s")

        self._session_cm = ClientSession(self._read, self._write)
        try:
            self._session = await asyncio.wait_for(
                self._session_cm.__aenter__(), timeout=timeout,
            )
            await asyncio.wait_for(self._session.initialize(), timeout=timeout)
            await asyncio.wait_for(self._fetch_tools(), timeout=timeout)
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError(f"MCP session init timed out after {timeout}s")

    async def close(self) -> None:
        if self._session_cm:
            await self._session_cm.__aexit__(None, None, None)
        if self._cm:
            await self._cm.__aexit__(None, None, None)

    async def _fetch_tools(self) -> None:
        result = await self._session.list_tools()
        self._tools = []
        for t in result.tools:
            self._tools.append({
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema if hasattr(t, "inputSchema") else {},
            })

    @property
    def tool_definitions(self) -> list[dict[str, Any]]:
        """Claude-format tool definitions."""
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._session.call_tool(name, arguments)
        parts: list[str] = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
            else:
                parts.append(str(item))
        return "\n".join(parts) if parts else ""


_FORCE_TOOLS_SYSTEM = """\
You are being evaluated on your ability to use tools for unit conversion.
You MUST use the provided tools to perform any unit conversions or lookups.
Do NOT solve problems from memory or mental math.
Always call at least one tool before giving your final answer.
After receiving tool results, present your final answer clearly.\
"""


# ---------------------------------------------------------------------------
# Judge — extracts structured answers from free-text model output
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = """\
You are a grading assistant for a unit conversion benchmark.

You will receive a model's free-text response to a scientific problem.
Your job is to extract the model's final answer as structured JSON.

Return ONLY a JSON object with these fields:
- "value": the numeric answer (float or int), or null if the model did not produce one
- "unit": the unit string the model gave, or null
- "refused": true if the model refused to answer or said the conversion is invalid/impossible
- "refusal_reason": a short string describing why the model refused, or null

If the model gave multiple candidate answers, extract the FINAL one.
If the model showed work but gave a clear final answer, extract that.

Return ONLY the JSON object, no other text."""


class Judge:
    """Uses a model backend to extract structured answers from free text."""

    def __init__(self, backend: ModelBackend):
        self.backend = backend

    async def extract(self, model_response: str) -> Extraction:
        messages = [
            {"role": "user", "content": model_response},
        ]
        resp = await self.backend.generate(messages, system=_JUDGE_SYSTEM)
        raw = resp.text or ""
        extraction = _parse_extraction(raw)
        log.debug("judge extraction value=%s unit=%s refused=%s",
                  extraction.value, extraction.unit, extraction.refused)
        return extraction


def _parse_extraction(raw: str) -> Extraction:
    """Parse JSON from judge output, tolerant of markdown fences."""
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try to find a JSON object
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not match:
        log.warning("judge returned no JSON: %s", text[:200])
        return Extraction()

    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        log.warning("judge JSON parse failed: %s — raw: %s", exc, text[:200])
        return Extraction()

    return Extraction(
        value=_to_float(obj.get("value")),
        unit=obj.get("unit"),
        refused=bool(obj.get("refused", False)),
        refusal_reason=obj.get("refusal_reason"),
    )


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

# Unicode superscript/subscript normalisation table
_SUPERSCRIPT_MAP = str.maketrans({
    "\u00b2": "2", "\u00b3": "3", "\u00b9": "1",
    "\u2070": "0", "\u2071": "i", "\u2074": "4",
    "\u2075": "5", "\u2076": "6", "\u2077": "7",
    "\u2078": "8", "\u2079": "9", "\u207a": "+",
    "\u207b": "-", "\u207c": "=", "\u207d": "(",
    "\u207e": ")", "\u207f": "n",
    "\u2080": "0", "\u2081": "1", "\u2082": "2",
    "\u2083": "3", "\u2084": "4", "\u2085": "5",
    "\u2086": "6", "\u2087": "7", "\u2088": "8",
    "\u2089": "9",
})


# Long-form and plural unit names → canonical short form (lowercase).
# Covers the aliases observed in model outputs from the control run.
_UNIT_ALIASES: dict[str, str] = {
    # Time
    "seconds": "s", "second": "s",
    "minutes": "min", "minute": "min",
    "hours": "h", "hour": "h",
    # Length
    "meters": "m", "meter": "m", "metres": "m", "metre": "m",
    "inches": "in", "inch": "in",
    "feet": "ft", "foot": "ft",
    # Mass
    "grams": "g", "gram": "g",
    "kilograms": "kg", "kilogram": "kg",
    "pounds": "lb", "pound": "lb",
    # Energy / Power
    "watts": "w", "watt": "w",
    "joules": "j", "joule": "j",
    # Volume
    "gallons": "gal", "gallon": "gal",
    "liters": "l", "liter": "l", "litres": "l", "litre": "l",
    # Astronomy
    "light-years": "ly", "light-year": "ly",
    "parsecs": "pc", "parsec": "pc",
    "solar masses": "m☉", "solar mass": "m☉",
    "arcseconds": "arcsec", "arcsecond": "arcsec",
    "arcminutes": "arcmin", "arcminute": "arcmin",
    "microradians": "µrad", "microradian": "µrad",
    # Photometry
    "millilumens": "mlm", "millilumen": "mlm",
}

# Strings that should be treated as equivalent to "dimensionless"
_DIMENSIONLESS_SYNONYMS = {"", "dimensionless", "ratio", "unitless", "pure number"}


def normalise_unit(u: str) -> str:
    """Normalise a unit string for comparison.

    Applies cosmetic normalisation (unicode, case, brackets) then parses the
    unit into a canonical factored form so that algebraically equivalent
    representations compare equal.  For example ``J/K/mol`` and ``J/(mol·K)``
    both canonicalise to ``j*k^-1*mol^-1``.
    """
    s = u.strip()
    # Unicode NFKD normalisation (decomposes compatibility chars)
    s = unicodedata.normalize("NFKD", s)
    # Explicit superscript/subscript mapping
    s = s.translate(_SUPERSCRIPT_MAP)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Normalise brackets/parens
    s = s.replace("[", "(").replace("]", ")")
    # Normalise middot/cdot to *
    s = s.replace("·", "*").replace("⋅", "*").replace("\u00b7", "*")
    # Lowercase
    s = s.lower()

    # Check for dimensionless synonyms early
    if s in _DIMENSIONLESS_SYNONYMS:
        return "dimensionless"

    # Replace long-form / plural unit names with canonical short forms
    # Try longest match first to handle multi-word aliases ("solar masses")
    for alias, canonical in sorted(_UNIT_ALIASES.items(), key=lambda x: -len(x[0])):
        s = re.sub(r'\b' + re.escape(alias) + r'\b', canonical, s)

    # Re-apply NFKD after alias substitution so that characters injected by
    # aliases (e.g. U+00B5 MICRO SIGN in "µrad") get normalised to their
    # canonical decomposition (U+03BC GREEK SMALL MU), matching the expected
    # unit which also goes through NFKD.
    s = unicodedata.normalize("NFKD", s)

    # Try to parse into a canonical factored form
    try:
        factors = _parse_unit_factors(s)
        # Build canonical string: sorted factors with explicit exponents
        parts = []
        for base, exp in sorted(factors.items()):
            if exp == 1:
                parts.append(base)
            else:
                parts.append(f"{base}^{exp}")
        return "*".join(parts) if parts else s
    except Exception:
        # Fall back to cosmetic normalisation only
        return s


def _parse_unit_factors(s: str) -> dict[str, int]:
    """Parse a normalised unit string into {base_unit: exponent} factors.

    Handles patterns like:
      - ``j/k/mol``        → {j: 1, k: -1, mol: -1}
      - ``j/(mol*k)``      → {j: 1, mol: -1, k: -1}
      - ``kg*m^2/s^2``     → {kg: 1, m: 2, s: -2}
      - ``kg*m^2*s^-2``    → {kg: 1, m: 2, s: -2}
      - ``m/s^2``          → {m: 1, s: -2}
    """
    factors: dict[str, int] = {}
    # Tokenise: split on / at the top level (respecting parentheses)
    # First, split into numerator and denominator groups by top-level /
    groups: list[tuple[str, int]] = []  # (group_str, sign)
    depth = 0
    current: list[str] = []
    sign = 1  # +1 for numerator, -1 for denominator
    for ch in s:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "/" and depth == 0:
            groups.append(("".join(current), sign))
            current = []
            sign = -1
        else:
            current.append(ch)
    groups.append(("".join(current), sign))

    for group, gsign in groups:
        group = group.strip()
        # Strip outer parens: (mol*k) → mol*k
        if group.startswith("(") and group.endswith(")"):
            group = group[1:-1]
        # Split on * or space (multiplication)
        tokens = re.split(r"[* ]+", group)
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            # Parse exponent: kg^2, s^-2, m2, m^2
            m = re.match(r"^([a-z_]+)\^?(-?\d+)$", tok)
            if m:
                base, exp = m.group(1), int(m.group(2))
            else:
                base, exp = tok, 1
            factors[base] = factors.get(base, 0) + exp * gsign

    # Remove factors with exponent 0
    return {b: e for b, e in factors.items() if e != 0}


def score_problem(
    problem: dict[str, Any],
    extraction: Extraction,
) -> tuple[bool, bool, bool, bool]:
    """Return (score_numerical, score_unit, score_refusal, score_overall)."""
    must_fail = problem.get("must_fail", False)
    answer = problem.get("answer", {})
    expected_value = answer.get("value")
    expected_unit = answer.get("unit", "")
    tolerance_pct = answer.get("tolerance_pct", 5.0)

    if must_fail:
        # Model should have refused
        score_refusal = extraction.refused
        return False, False, score_refusal, score_refusal

    # Conversion problem — model should have produced a numeric answer
    score_refusal = not extraction.refused  # Should NOT refuse

    # Numerical accuracy
    score_numerical = False
    if extraction.value is not None and expected_value is not None:
        if expected_value == 0:
            score_numerical = abs(extraction.value) < 1e-9
        else:
            pct_error = abs(extraction.value - expected_value) / abs(expected_value) * 100
            score_numerical = pct_error <= tolerance_pct

    # Unit match
    score_unit = False
    norm_expected = normalise_unit(expected_unit) if expected_unit else ""
    if extraction.unit is not None and expected_unit:
        score_unit = normalise_unit(extraction.unit) == norm_expected
    elif extraction.unit is None and norm_expected == "dimensionless":
        # Model gave a bare number for a dimensionless quantity — correct
        score_unit = True

    # Scale-prefix fallback: if unit strings differ but represent the same
    # dimension (e.g. kJ/mol vs J/mol), rescale the predicted value and
    # re-check numerical accuracy.  Unit.fold_scale() is only on UnitProduct;
    # bare Unit objects have an implicit scale of 1.
    if not score_unit and not score_numerical and extraction.unit and extraction.value is not None:
        try:
            from ucon.units import get_unit_by_name
            u_exp = get_unit_by_name(expected_unit)
            u_pred = get_unit_by_name(extraction.unit)
            if u_exp.dimension == u_pred.dimension:
                score_unit = True
                s_pred = u_pred.fold_scale() if hasattr(u_pred, "fold_scale") else 1.0
                s_exp = u_exp.fold_scale() if hasattr(u_exp, "fold_scale") else 1.0
                adjusted = extraction.value * (s_pred / s_exp)
                if expected_value is not None and expected_value != 0:
                    pct_error = abs(adjusted - expected_value) / abs(expected_value) * 100
                    score_numerical = pct_error <= tolerance_pct
        except Exception:
            pass

    score_overall = score_numerical and score_unit and score_refusal
    return score_numerical, score_unit, score_refusal, score_overall


# ---------------------------------------------------------------------------
# Evaluator — agentic loop for a single problem
# ---------------------------------------------------------------------------

class Evaluator:
    """Evaluates a single problem with optional tool augmentation."""

    def __init__(
        self,
        backend: ModelBackend,
        judge: Judge,
        *,
        mcp_bridge: MCPToolBridge | None = None,
        max_tool_rounds: int = 10,
        condition: str = "bare",
        timeout: float = 120,
        force_tools: bool = False,
    ):
        self.backend = backend
        self.judge = judge
        self.mcp_bridge = mcp_bridge
        self.max_tool_rounds = max_tool_rounds
        self.condition = condition
        self.timeout = timeout
        self.force_tools = force_tools

    async def evaluate(
        self,
        problem: dict[str, Any],
        model_spec: str,
    ) -> EvalResult:
        t0 = time.monotonic()
        tool_log: list[dict[str, Any]] = []
        error: str | None = None

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": problem["problem_text"]},
        ]

        tools = (
            self.mcp_bridge.tool_definitions
            if self.mcp_bridge
            else None
        )

        pid = problem.get("problem_id", "?")
        _say = lambda msg: print(f"       {msg}", file=sys.stderr, flush=True)

        try:
            final_text, extraction, tool_log = await asyncio.wait_for(
                self._run_loop(pid, messages, tools, tool_log, _say),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            _say(f"Timed out waiting for model response ({self.timeout:.0f}s limit)")
            final_text = ""
            extraction = Extraction()
            error = f"timeout after {self.timeout}s"
        except Exception as exc:
            _say(f"Error: {exc}")
            final_text = ""
            extraction = Extraction()
            error = str(exc)

        latency_ms = (time.monotonic() - t0) * 1000
        s_num, s_unit, s_ref, s_overall = score_problem(problem, extraction)

        return EvalResult(
            problem=problem,
            model=model_spec,
            condition=self.condition,
            model_response=final_text,
            extraction=extraction,
            score_numerical=s_num,
            score_unit=s_unit,
            score_refusal=s_ref,
            score_overall=s_overall,
            tool_calls=tool_log,
            n_tool_calls=len(tool_log),
            latency_ms=latency_ms,
            error=error,
        )

    async def _run_loop(
        self,
        pid: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_log: list[dict[str, Any]],
        _say: Any,
    ) -> tuple[str, Extraction, list[dict[str, Any]]]:
        """Inner evaluation loop — model, tool rounds, judge."""
        _say("Waiting for model response...")
        final_text = ""
        for _round in range(self.max_tool_rounds + 1):
            gen_kwargs: dict[str, Any] = {"tools": tools}

            # On the first round with force_tools, instruct the model to use tools
            if _round == 0 and self.force_tools and tools:
                gen_kwargs["system"] = _FORCE_TOOLS_SYSTEM
                # Claude API: tool_choice=any forces at least one tool call
                if isinstance(self.backend, ClaudeBackend):
                    gen_kwargs["tool_choice"] = {"type": "any"}

            resp = await self.backend.generate(messages, **gen_kwargs)

            if resp.text:
                final_text = resp.text

            if not resp.tool_calls or not self.mcp_bridge:
                break

            tool_names = ", ".join(tc.name for tc in resp.tool_calls)
            _say(f"Model requested tool(s): {tool_names}")

            # Build assistant message with tool use
            assistant_content: list[dict[str, Any]] = []
            if resp.text:
                assistant_content.append({"type": "text", "text": resp.text})
            for tc in resp.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tool calls and build tool result messages
            for tc in resp.tool_calls:
                _say(f"Calling tool '{tc.name}'...")
                try:
                    result_text = await self.mcp_bridge.call_tool(
                        tc.name, tc.arguments
                    )
                    is_error = False
                except Exception as exc:
                    result_text = f"Error: {exc}"
                    is_error = True
                    _say(f"Tool '{tc.name}' failed: {exc}")

                tool_log.append({
                    "round": _round,
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "result": result_text[:500],
                    "is_error": is_error,
                })

                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": result_text,
                            "is_error": is_error,
                        }
                    ],
                })

            _say("Waiting for model response...")

        # Judge extracts structured answer
        _say("Extracting answer from response...")
        extraction = await self.judge.extract(final_text) if final_text else Extraction()
        return final_text, extraction, tool_log


# ---------------------------------------------------------------------------
# Runner — orchestrates concurrency, I/O, and summary
# ---------------------------------------------------------------------------

class Runner:
    """Loads problems, runs evaluations concurrently, writes output."""

    def __init__(
        self,
        evaluator: Evaluator,
        model_spec: str,
        *,
        concurrency: int = 4,
    ):
        self.evaluator = evaluator
        self.model_spec = model_spec
        self.concurrency = concurrency

    async def run(
        self,
        problems: list[dict[str, Any]],
        output: Path | None = None,
    ) -> list[EvalResult]:
        sem = asyncio.Semaphore(self.concurrency)
        results: list[EvalResult] = []
        completed = 0
        total = len(problems)

        async def _eval_one(p: dict[str, Any]) -> EvalResult:
            nonlocal completed
            async with sem:
                pid = p.get("problem_id", "?")
                print(f"\n[{completed + 1}/{total}] {pid}", file=sys.stderr, flush=True)

                r = await self.evaluator.evaluate(p, self.model_spec)
                completed += 1

                elapsed = f"{r.latency_ms / 1000:.1f}s"

                if r.error:
                    print(f"  ==>  ERROR  ({elapsed})  {r.error}", file=sys.stderr)
                elif r.problem.get("must_fail", False):
                    refused = "yes" if r.extraction.refused else "no"
                    verdict = "PASS" if r.score_overall else "FAIL"
                    print(
                        f"  ==>  {verdict}  ({elapsed})  "
                        f"should refuse: model {'refused' if r.extraction.refused else 'answered'}",
                        file=sys.stderr,
                    )
                else:
                    expected = r.problem.get("answer", {})
                    exp_val = expected.get("value")
                    exp_unit = expected.get("unit", "")
                    tol = expected.get("tolerance_pct", 5.0)
                    got_val = r.extraction.value
                    got_unit = r.extraction.unit or ""
                    verdict = "PASS" if r.score_overall else "FAIL"
                    print(
                        f"  ==>  {verdict}  ({elapsed})  "
                        f"expected: {exp_val} {exp_unit} (+/-{tol}%)  "
                        f"got: {got_val} {got_unit}",
                        file=sys.stderr,
                    )
                return r

        tasks = [asyncio.create_task(_eval_one(p)) for p in problems]
        results = await asyncio.gather(*tasks)

        # Write output
        lines = [_result_to_jsonl(r) for r in results]
        if output:
            output.write_text("\n".join(lines) + "\n")
            log.info("results written to %s", output)
        else:
            for line in lines:
                print(line)

        # Summary to stderr
        _print_summary(list(results), file=sys.stderr)

        return list(results)


def _result_to_jsonl(r: EvalResult) -> str:
    """Serialise an EvalResult to a single JSONL line."""
    row: dict[str, Any] = {}
    # Copy all original problem fields
    row.update(r.problem)
    # Add evaluation fields
    row["model"] = r.model
    row["condition"] = r.condition
    row["model_response"] = r.model_response
    row["extracted_value"] = r.extraction.value
    row["extracted_unit"] = r.extraction.unit
    row["extracted_refused"] = r.extraction.refused
    row["extracted_refusal_reason"] = r.extraction.refusal_reason
    row["score_numerical"] = r.score_numerical
    row["score_unit"] = r.score_unit
    row["score_refusal"] = r.score_refusal
    row["score_overall"] = r.score_overall
    row["tool_calls"] = r.tool_calls
    row["n_tool_calls"] = r.n_tool_calls
    row["latency_ms"] = round(r.latency_ms, 1)
    row["error"] = r.error
    return json.dumps(row, ensure_ascii=False)


def _print_summary(results: list[EvalResult], *, file: Any = sys.stderr) -> None:
    """Print summary metrics."""
    if not results:
        print("\nNo results.", file=file)
        return

    total = len(results)
    overall_pass = sum(1 for r in results if r.score_overall)
    errors = sum(1 for r in results if r.error)

    conversion = [r for r in results if not r.problem.get("must_fail", False)]
    must_fail = [r for r in results if r.problem.get("must_fail", False)]

    conv_pass = sum(1 for r in conversion if r.score_overall)
    ref_pass = sum(1 for r in must_fail if r.score_overall)

    p = lambda n, d: f"{n/d*100:.1f}%" if d else "N/A"

    print("\n" + "=" * 60, file=file)
    print("UNITSAFE BENCHMARK RESULTS", file=file)
    print("=" * 60, file=file)
    print(f"  Model:                {results[0].model}", file=file)
    print(f"  Condition:            {results[0].condition}", file=file)
    print(f"  Problems evaluated:   {total}", file=file)
    print(f"  Errors:               {errors}", file=file)
    print(file=file)
    print(f"  Overall accuracy:     {p(overall_pass, total)}  ({overall_pass}/{total})", file=file)
    if conversion:
        print(f"  Conversion accuracy:  {p(conv_pass, len(conversion))}  ({conv_pass}/{len(conversion)})", file=file)
    if must_fail:
        print(f"  Refusal accuracy:     {p(ref_pass, len(must_fail))}  ({ref_pass}/{len(must_fail)})", file=file)

    # KOQ discrimination score — accuracy on KOQ-clustered problems
    koq_problems = [
        r for r in results
        if r.problem.get("koq_cluster", "none") not in ("none", "dimensional_safety")
    ]
    if koq_problems:
        koq_pass = sum(1 for r in koq_problems if r.score_overall)
        print(f"  KOQ discrimination:   {p(koq_pass, len(koq_problems))}  ({koq_pass}/{len(koq_problems)})", file=file)

    # Per-tier breakdown
    tiers = sorted({r.problem.get("difficulty", "") for r in results})
    if tiers:
        print(file=file)
        print("  Per-tier breakdown:", file=file)
        for tier in tiers:
            tier_results = [r for r in results if r.problem.get("difficulty") == tier]
            tier_pass = sum(1 for r in tier_results if r.score_overall)
            print(f"    {tier:12s}  {p(tier_pass, len(tier_results)):>6s}  ({tier_pass}/{len(tier_results)})", file=file)

    # Per-cluster breakdown
    clusters = sorted({
        r.problem.get("koq_cluster", "none")
        for r in results
        if r.problem.get("koq_cluster", "none") not in ("none",)
    })
    if clusters:
        print(file=file)
        print("  Per-cluster breakdown:", file=file)
        for cluster in clusters:
            c_results = [r for r in results if r.problem.get("koq_cluster") == cluster]
            c_pass = sum(1 for r in c_results if r.score_overall)
            print(f"    {cluster:40s}  {p(c_pass, len(c_results)):>6s}  ({c_pass}/{len(c_results)})", file=file)

    print("=" * 60, file=file)


# ---------------------------------------------------------------------------
# Problem loading and filtering
# ---------------------------------------------------------------------------

def load_problems(path: Path) -> list[dict[str, Any]]:
    """Load problems from a JSONL file."""
    problems = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                problems.append(json.loads(line))
    return problems


def filter_problems(
    problems: list[dict[str, Any]],
    *,
    difficulty: str | None = None,
    domain: str | None = None,
    cluster: str | None = None,
    must_fail: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Apply filters to the problem list."""
    filtered = problems

    if difficulty:
        filtered = [p for p in filtered if p.get("difficulty") == difficulty]

    if domain:
        filtered = [
            p for p in filtered
            if p.get("source", {}).get("origin") == domain
        ]

    if cluster:
        filtered = [p for p in filtered if p.get("koq_cluster") == cluster]

    if must_fail is not None:
        mf = must_fail.lower() in ("true", "1", "yes")
        filtered = [p for p in filtered if p.get("must_fail", False) is mf]

    if limit is not None and limit > 0:
        filtered = filtered[:limit]

    return filtered


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UnitSafe benchmark runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v for INFO, -vv for DEBUG)",
    )
    parser.add_argument(
        "-m", "--model",
        required=True,
        help="Model spec as backend:model (e.g. claude:claude-haiku-4-5-20251001, ollama:llama3.2:3b)",
    )
    parser.add_argument(
        "--judge",
        default=None,
        help="Judge model spec (default: same as --model)",
    )
    parser.add_argument(
        "--tools",
        action="store_true",
        help="Enable MCP tool-augmented evaluation",
    )
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="MCP server URL for SSE transport (default: spawn stdio server)",
    )
    parser.add_argument(
        "--mcp-api-key",
        default=None,
        help="API key for MCP server authentication (sent as Bearer token)",
    )
    parser.add_argument(
        "-j",
        type=int,
        default=4,
        help="Max concurrent evaluations (default: 4)",
    )
    parser.add_argument(
        "-o",
        default=None,
        help="Output JSONL file (default: stdout)",
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Input JSONL file (default: data/test.jsonl relative to this script)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max problems to evaluate",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=None,
        help="Ollama context window size (overrides model default)",
    )
    parser.add_argument(
        "--show-thinking",
        action="store_true",
        help="Stream model output to stderr in real time (useful for thinking models)",
    )
    parser.add_argument(
        "--no-think",
        action="store_true",
        help="Disable thinking/chain-of-thought for models that support it (e.g. qwen3)",
    )
    parser.add_argument(
        "--filter-difficulty",
        default=None,
        help="Filter by difficulty tier (e.g. tier_1)",
    )
    parser.add_argument(
        "--filter-domain",
        default=None,
        help="Filter by source.origin (e.g. radiation_physics)",
    )
    parser.add_argument(
        "--filter-cluster",
        default=None,
        help="Filter by koq_cluster (e.g. cluster_4_Jkg)",
    )
    parser.add_argument(
        "--filter-must-fail",
        default=None,
        help="Filter by must_fail (true/false)",
    )
    parser.add_argument(
        "--force-tools",
        action="store_true",
        help="Force the model to use tools on the first round (Claude: tool_choice=any, all: system prompt)",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=10,
        help="Max tool call rounds per problem (default: 10)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="Per-problem timeout in seconds (default: 120)",
    )
    return parser


async def async_main(args: argparse.Namespace) -> None:
    # Resolve data path
    script_dir = Path(__file__).resolve().parent
    if args.data:
        data_path = Path(args.data)
    else:
        data_path = script_dir / "data" / "test.jsonl"

    if not data_path.exists():
        log.error("data file not found: %s", data_path)
        sys.exit(1)

    # Load and filter problems
    _say = lambda msg: print(msg, file=sys.stderr, flush=True)

    problems = load_problems(data_path)

    problems = filter_problems(
        problems,
        difficulty=args.filter_difficulty,
        domain=args.filter_domain,
        cluster=args.filter_cluster,
        must_fail=args.filter_must_fail,
        limit=args.limit,
    )

    if not problems:
        _say("No problems matched the given filters.")
        sys.exit(0)

    judge_spec = args.judge or args.model
    condition = "tool-augmented" if args.tools else "bare"

    # Header
    _say("")
    _say("=" * 60)
    _say("UnitSafe Benchmark Runner")
    _say("=" * 60)
    _say(f"  Model:       {args.model}")
    _say(f"  Judge:       {judge_spec}")
    _say(f"  Mode:        {condition}")
    _say(f"  Problems:    {len(problems)}")
    _say(f"  Concurrency: {args.j}")
    _say(f"  Timeout:     {args.timeout:.0f}s per problem")
    if args.no_think:
        _say(f"  Thinking:    disabled")
    if args.force_tools:
        _say(f"  Force tools: yes")
    _say("")

    # Build backends
    model_backend = make_backend(
        args.model, num_ctx=args.num_ctx, show_thinking=args.show_thinking,
        think=not args.no_think,
    )
    judge_backend = make_backend(judge_spec, num_ctx=args.num_ctx)
    judge = Judge(judge_backend)

    # Preflight — verify backends are reachable before starting eval
    _say("Checking connectivity...")
    preflight_targets: list[tuple[str, str, Any]] = [
        ("Model", args.model, model_backend),
    ]
    if judge_spec != args.model:
        preflight_targets.append(("Judge", judge_spec, judge_backend))
    for label, spec, backend in preflight_targets:
        _say(f"  {label} ({spec})...")
        try:
            await backend.preflight()
            _say(f"  {label} ({spec}) — ok")
        except RuntimeError as exc:
            _say(f"  {label} ({spec}) — FAILED")
            _say(f"    {exc}")
            sys.exit(1)

    # Validate: claude-code backend doesn't support tool use
    if args.tools and isinstance(model_backend, ClaudeCodeBackend):
        _say("ERROR: 'claude-code' backend does not support tool-augmented evaluation.")
        _say("  The claude-code backend uses 'claude -p' which cannot make tool calls.")
        _say("  Use 'claude:<model>' instead (requires ANTHROPIC_API_KEY).")
        _say(f"  Example: -m claude:{args.model.partition(':')[2] or 'claude-haiku-4-5-20251001'}")
        sys.exit(1)

    # MCP bridge
    mcp_bridge: MCPToolBridge | None = None
    if args.tools:
        mcp_target = args.mcp_url or "ucon-mcp (stdio)"
        _say(f"  MCP server ({mcp_target})...")
        mcp_bridge = MCPToolBridge()
        try:
            if args.mcp_url:
                await mcp_bridge.connect_url(args.mcp_url, api_key=args.mcp_api_key)
            else:
                await mcp_bridge.connect_stdio("ucon-mcp")
            tool_count = len(mcp_bridge.tool_definitions)
            _say(f"  MCP server ({mcp_target}) — ok, {tool_count} tools")
        except RuntimeError as exc:
            _say(f"  MCP server ({mcp_target}) — FAILED")
            _say(f"    {exc}")
            sys.exit(1)

    _say("")
    _say(f"Running {len(problems)} evaluations...")

    # Build evaluator and runner
    evaluator = Evaluator(
        model_backend,
        judge,
        mcp_bridge=mcp_bridge,
        max_tool_rounds=args.max_tool_rounds,
        condition=condition,
        timeout=args.timeout,
        force_tools=args.force_tools,
    )

    runner = Runner(evaluator, args.model, concurrency=args.j)

    output_path = Path(args.o) if args.o else None

    try:
        await runner.run(problems, output=output_path)
    finally:
        if mcp_bridge:
            await mcp_bridge.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    level = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}.get(
        args.verbose, logging.DEBUG
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()

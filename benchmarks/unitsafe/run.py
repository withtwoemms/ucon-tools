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
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


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

        return Message(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
        )


class OllamaBackend:
    """Wraps ``ollama.chat`` via ``asyncio.to_thread``."""

    def __init__(self, model: str):
        self.model = model

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
        # Ollama normalises tags: "qwen3:0.6b" may appear as "qwen3:0.6b"
        # or with a default tag appended.  Check prefix match.
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
        if tools:
            ollama_tools = _to_ollama_tools(tools)
            if ollama_tools:
                kwargs["tools"] = ollama_tools

        resp = await asyncio.to_thread(ollama.chat, **kwargs)

        text = resp.get("message", {}).get("content") or None
        raw_tool_calls = resp.get("message", {}).get("tool_calls") or []
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


def make_backend(spec: str) -> ModelBackend:
    """Parse a ``backend:model`` spec and return the corresponding backend."""
    backend, _, model = spec.partition(":")
    if not model:
        raise ValueError(
            f"Invalid model spec {spec!r} — expected 'backend:model' "
            "(e.g. 'claude:claude-haiku-4-5-20251001' or 'ollama:llama3.2:3b')"
        )
    backend = backend.lower()
    if backend == "claude":
        return ClaudeBackend(model)
    elif backend == "ollama":
        return OllamaBackend(model)
    else:
        raise ValueError(
            f"Unknown backend {backend!r} — supported: claude, ollama"
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

    async def connect_stdio(self, command: str, args: list[str] | None = None) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=command, args=args or [])
        self._cm = stdio_client(params)
        self._read, self._write = await self._cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        await self._fetch_tools()

    async def connect_sse(self, url: str) -> None:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        self._cm = sse_client(url)
        self._read, self._write = await self._cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        await self._fetch_tools()

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
        return _parse_extraction(raw)


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
        return Extraction()

    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError:
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


def normalise_unit(u: str) -> str:
    """Normalise a unit string for comparison."""
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
    return s


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
    if extraction.unit is not None and expected_unit:
        score_unit = normalise_unit(extraction.unit) == normalise_unit(expected_unit)

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
    ):
        self.backend = backend
        self.judge = judge
        self.mcp_bridge = mcp_bridge
        self.max_tool_rounds = max_tool_rounds
        self.condition = condition

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

        try:
            final_text = ""
            for _round in range(self.max_tool_rounds + 1):
                resp = await self.backend.generate(messages, tools=tools)

                if resp.text:
                    final_text = resp.text

                if not resp.tool_calls or not self.mcp_bridge:
                    break

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
                    try:
                        result_text = await self.mcp_bridge.call_tool(
                            tc.name, tc.arguments
                        )
                        is_error = False
                    except Exception as exc:
                        result_text = f"Error: {exc}"
                        is_error = True

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

            # Judge extracts structured answer
            extraction = await self.judge.extract(final_text) if final_text else Extraction()

        except Exception as exc:
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
                r = await self.evaluator.evaluate(p, self.model_spec)
                completed += 1
                status = "PASS" if r.score_overall else "FAIL"
                if r.error:
                    status = "ERR "
                print(
                    f"[{completed:>3}/{total}] {status}  {p['problem_id']}",
                    file=sys.stderr,
                )
                return r

        tasks = [asyncio.create_task(_eval_one(p)) for p in problems]
        results = await asyncio.gather(*tasks)

        # Write output
        lines = [_result_to_jsonl(r) for r in results]
        if output:
            output.write_text("\n".join(lines) + "\n")
            print(f"\nResults written to {output}", file=sys.stderr)
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
        "--max-tool-rounds",
        type=int,
        default=10,
        help="Max tool call rounds per problem (default: 10)",
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
        print(f"Error: data file not found: {data_path}", file=sys.stderr)
        sys.exit(1)

    # Load and filter problems
    problems = load_problems(data_path)
    print(f"Loaded {len(problems)} problems from {data_path}", file=sys.stderr)

    problems = filter_problems(
        problems,
        difficulty=args.filter_difficulty,
        domain=args.filter_domain,
        cluster=args.filter_cluster,
        must_fail=args.filter_must_fail,
        limit=args.limit,
    )
    print(f"After filtering: {len(problems)} problems", file=sys.stderr)

    if not problems:
        print("No problems to evaluate.", file=sys.stderr)
        sys.exit(0)

    # Build backends
    model_backend = make_backend(args.model)

    judge_spec = args.judge or args.model
    judge_backend = make_backend(judge_spec)
    judge = Judge(judge_backend)

    # Preflight — verify backends are reachable before starting eval
    preflight_targets: list[tuple[str, Any]] = [(args.model, model_backend)]
    if judge_spec != args.model:
        preflight_targets.append((judge_spec, judge_backend))
    for spec, backend in preflight_targets:
        print(f"Preflight check: {spec}...", file=sys.stderr, end=" ", flush=True)
        try:
            await backend.preflight()
            print("ok", file=sys.stderr)
        except RuntimeError as exc:
            print("FAILED", file=sys.stderr)
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    # MCP bridge
    mcp_bridge: MCPToolBridge | None = None
    condition = "bare"
    if args.tools:
        condition = "tools"
        mcp_bridge = MCPToolBridge()
        if args.mcp_url:
            print(f"Connecting to MCP server at {args.mcp_url}...", file=sys.stderr)
            await mcp_bridge.connect_sse(args.mcp_url)
        else:
            print("Spawning MCP stdio server (ucon-mcp)...", file=sys.stderr)
            await mcp_bridge.connect_stdio("ucon-mcp")
        tool_count = len(mcp_bridge.tool_definitions)
        print(f"MCP bridge ready: {tool_count} tools available", file=sys.stderr)

    # Build evaluator and runner
    evaluator = Evaluator(
        model_backend,
        judge,
        mcp_bridge=mcp_bridge,
        max_tool_rounds=args.max_tool_rounds,
        condition=condition,
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
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()

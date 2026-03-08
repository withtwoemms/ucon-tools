#!/usr/bin/env python
"""
Ollama Model Evaluation for MCP Tools.

Tests whether small models can correctly use decompose/compute tools
to solve unit conversion problems.

Usage:
    # Run with default model (qwen2.5:0.5b)
    python scripts/eval_ollama.py

    # Run with specific model
    python scripts/eval_ollama.py --model llama3.2:1b

    # Run against SSE server
    python scripts/eval_ollama.py --sse http://localhost:8000/sse

Requirements:
    pip install ollama
    ollama pull qwen2.5:0.5b  # or your preferred model
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    import ollama
except ImportError:
    print("Install ollama: pip install ollama")
    sys.exit(1)


# Tool definitions in Ollama format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "solve",
            "description": """Solve a unit conversion problem from natural language.
Just pass the problem text and the target unit. The tool extracts
quantities automatically and computes the answer.

Examples:
  solve(problem="5 mcg/kg/min for a 70 kg patient", target_unit="mg/h")
  # Returns: 21 mg/h

  solve(problem="1000 mL over 8 hours using 15 gtt/mL tubing", target_unit="gtt/min")
  # Returns: 31.25 gtt/min

  solve(problem="Convert 500 mL to liters", target_unit="L")
  # Returns: 0.5 L

ALWAYS use this tool. Never calculate manually.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "problem": {
                        "type": "string",
                        "description": "The problem statement in natural language"
                    },
                    "target_unit": {
                        "type": "string",
                        "description": "The unit for the answer (e.g., 'mg/h', 'gtt/min', 'L')"
                    }
                },
                "required": ["problem", "target_unit"]
            }
        }
    }
]


@dataclass
class Problem:
    """A test problem."""
    id: str
    problem: str
    expected_value: float
    expected_unit: str
    tolerance: float = 0.02
    hint: str = ""  # Optional hint about expected approach


@dataclass
class EvalResult:
    """Result of evaluating a problem."""
    problem: Problem
    passed: bool = False
    model_response: str = ""
    tool_calls: list = field(default_factory=list)
    final_value: float | None = None
    error: str | None = None
    iterations: int = 0


# Test problems - mix of simple and complex
PROBLEMS = [
    # Simple (decompose query mode)
    Problem("S1", "Convert 500 mL to liters.", 0.5, "L",
            hint="decompose(query='500 mL to L')"),
    Problem("S2", "Convert 2.5 g to mg.", 2500, "mg",
            hint="decompose(query='2.5 g to mg')"),
    Problem("S3", "What is 50 psi in kPa?", 344.74, "kPa",
            hint="decompose(query='50 psi to kPa')"),

    # Complex (decompose structured mode)
    Problem("C1",
        "A patient weighs 70 kg. The dose is 5 mcg/kg/min. "
        "What is the rate in mg/hour?",
        21, "mg/h",
        hint="decompose(initial_unit='mcg/(kg*min)', target_unit='mg/h', known_quantities=[{value:70, unit:'kg'}])"),
    Problem("C2",
        "IV order: 1000 mL over 8 hours using 15 gtt/mL tubing. "
        "Calculate the drip rate in gtt/min.",
        31.25, "gtt/min",
        hint="decompose(initial_unit='mL', target_unit='gtt/min', known_quantities=[{value:8, unit:'h'}, {value:15, unit:'gtt/mL'}])"),
    Problem("C3",
        "Pediatric dose: 25 mg/kg/day divided into 3 doses. "
        "Child weighs 15 kg. How many mg per dose?",
        125, "mg",
        hint="decompose(initial_unit='mg/(kg*day)', target_unit='mg', known_quantities=[{value:15, unit:'kg'}, {value:3, unit:'ea/day'}])"),
]


class OllamaEval:
    """Evaluation harness for Ollama models."""

    def __init__(self, model: str, mcp_session, max_iterations: int = 3, verbose: bool = False):
        self.model = model
        self.mcp_session = mcp_session
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.results: list[EvalResult] = []

    async def call_mcp_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool and return the result."""
        result = await self.mcp_session.call_tool(name, arguments)

        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)

        return {"error": "No content in response"}

    async def eval_problem(self, problem: Problem) -> EvalResult:
        """Evaluate a single problem with the model."""
        result = EvalResult(problem=problem)

        # Build user message with expected unit hint
        user_content = problem.problem
        if problem.expected_unit:
            user_content += f"\n\nThe answer should be in: {problem.expected_unit}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You solve unit conversion problems using the solve() tool.\n\n"
                    "ALWAYS call solve(problem=<the problem text>, target_unit=<answer unit>)\n\n"
                    "Example:\n"
                    "  User: '5 mcg/kg/min for a 70 kg patient, rate in mg/h?'\n"
                    "  You: solve(problem='5 mcg/kg/min for a 70 kg patient', target_unit='mg/h')\n\n"
                    "The tool extracts values and computes the answer automatically.\n"
                    "NEVER calculate manually. ALWAYS use the solve() tool."
                )
            },
            {
                "role": "user",
                "content": user_content
            }
        ]

        for iteration in range(self.max_iterations):
            result.iterations = iteration + 1

            try:
                # Call Ollama
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                )

                result.model_response = response.message.content or ""

                # Check for tool calls
                if not response.message.tool_calls:
                    # No tool call - model tried to answer directly
                    result.error = "Model did not use tools"
                    break

                # Process tool calls
                for tool_call in response.message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    result.tool_calls.append({
                        "name": tool_name,
                        "arguments": tool_args
                    })

                    # Execute tool via MCP
                    tool_result = await self.call_mcp_tool(tool_name, tool_args)

                    # Check for errors
                    if "error_type" in tool_result:
                        # Tool returned an error - add to messages for retry
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [tool_call]
                        })
                        messages.append({
                            "role": "tool",
                            "content": json.dumps(tool_result)
                        })
                        continue

                    # Check if this is a solve/compute result (has quantity)
                    if "quantity" in tool_result:
                        result.final_value = tool_result["quantity"]

                        # Check answer
                        if problem.expected_value == 0:
                            result.passed = abs(result.final_value) < 1e-5
                        else:
                            rel_error = abs(result.final_value - problem.expected_value) / abs(problem.expected_value)
                            result.passed = rel_error < problem.tolerance

                        if result.passed:
                            return result
                        else:
                            result.error = f"Wrong answer: got {result.final_value}, expected {problem.expected_value}"
                            return result

            except Exception as e:
                result.error = str(e)
                break

        if not result.error:
            result.error = f"Did not converge in {self.max_iterations} iterations"

        return result

    async def run_all(self) -> list[EvalResult]:
        """Run all problems."""
        print(f"\nEvaluating model: {self.model}")
        print("=" * 60)

        for problem in PROBLEMS:
            result = await self.eval_problem(problem)
            self.results.append(result)
            self._print_result(result)

        return self.results

    def _print_result(self, result: EvalResult):
        """Print a single result."""
        status = "✓" if result.passed else "✗"
        p = result.problem

        print(f"\n{status} [{p.id}] {p.problem[:60]}...")
        print(f"   Expected: {p.expected_value} {p.expected_unit}")

        if result.passed:
            print(f"   Got: {result.final_value}")
        else:
            print(f"   Error: {result.error}")

        print(f"   Tool calls: {len(result.tool_calls)}, Iterations: {result.iterations}")

        # Show tool call details for failures or in verbose mode
        if (not result.passed or self.verbose) and result.tool_calls:
            print(f"   Tool call details:")
            for i, tc in enumerate(result.tool_calls):
                name = tc.get("name", "?")
                args = tc.get("arguments", {})
                # Compact display of arguments
                if name == "solve":
                    problem = args.get("problem", "?")
                    target = args.get("target_unit", "?")
                    # Truncate problem if too long
                    if len(problem) > 50:
                        problem = problem[:47] + "..."
                    print(f"      [{i+1}] solve: \"{problem}\" → {target}")
                else:
                    print(f"      [{i+1}] {name}: {args}")

    def print_summary(self):
        """Print summary."""
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)

        print("\n" + "=" * 60)
        print(f"MODEL: {self.model}")
        print(f"PASSED: {passed}/{total}")
        print("=" * 60)

        # Breakdown by complexity
        simple = [r for r in self.results if r.problem.id.startswith("S")]
        complex_ = [r for r in self.results if r.problem.id.startswith("C")]

        simple_passed = sum(1 for r in simple if r.passed)
        complex_passed = sum(1 for r in complex_ if r.passed)

        print(f"Simple (decompose): {simple_passed}/{len(simple)}")
        print(f"Complex (compute):  {complex_passed}/{len(complex_)}")

        return passed == total


async def run_eval(model: str, sse_url: str | None = None, verbose: bool = False):
    """Run evaluation against MCP server."""
    from mcp import ClientSession

    if sse_url:
        from mcp.client.sse import sse_client
        print(f"Connecting to SSE server at {sse_url}...")
        async with sse_client(sse_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                evaluator = OllamaEval(model, session, verbose=verbose)
                await evaluator.run_all()
                evaluator.print_summary()
    else:
        from mcp.client.stdio import stdio_client, StdioServerParameters
        print("Spawning MCP server via stdio...")

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from ucon.tools.mcp.server import main; main()"],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Register custom units for nursing problems
                await session.call_tool("define_unit", {
                    "name": "drop",
                    "dimension": "count",
                    "aliases": ["gtt", "drops"]
                })

                evaluator = OllamaEval(model, session, verbose=verbose)
                await evaluator.run_all()
                evaluator.print_summary()


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate Ollama models on MCP unit conversion tasks"
    )
    parser.add_argument(
        "--model",
        default="qwen2.5:0.5b",
        help="Ollama model to evaluate (default: qwen2.5:0.5b)"
    )
    parser.add_argument(
        "--sse",
        metavar="URL",
        help="SSE server URL (e.g., http://localhost:8000/sse)"
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available Ollama models and exit"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show tool call details for all problems (not just failures)"
    )
    args = parser.parse_args()

    if args.list_models:
        try:
            models = ollama.list()
            print("Available models:")
            for m in models.get("models", []):
                print(f"  {m['name']}")
        except Exception as e:
            print(f"Error listing models: {e}")
        return

    asyncio.run(run_eval(args.model, args.sse, args.verbose))


if __name__ == "__main__":
    main()

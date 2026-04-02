#!/usr/bin/env python
# © 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0
# See the LICENSE file for details.

"""
Live MCP Server Evaluation for decompose → compute Pipeline.

This script runs evaluation tests against a live ucon MCP server,
testing the full end-to-end flow via the MCP protocol.

Usage:
    # Spawn server automatically via stdio
    python scripts/eval_decompose_live.py

    # Connect to running SSE server
    python scripts/eval_decompose_live.py --sse http://localhost:8000/sse

    # Via Makefile
    make eval-decompose-live
    make eval-decompose-live SSE_URL=http://localhost:8000/sse
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any


class Colors:
    """ANSI color codes."""
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN = "\033[0;36m"
    RESET = "\033[0m"


@dataclass
class EvalResult:
    """Result of a single eval test."""
    name: str
    passed: bool
    expected: float | None
    actual: float | None
    error: str | None = None


class LiveServerEval:
    """Evaluation harness for live MCP server."""

    def __init__(self, sse_url: str | None = None, verbose: bool = False):
        self.sse_url = sse_url
        self.verbose = verbose
        self.results: list[EvalResult] = []

    async def call_tool(self, session, tool_name: str, arguments: dict) -> dict:
        """Call a tool and return parsed result."""
        result = await session.call_tool(tool_name, arguments)

        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return json.loads(content.text)

        return {"error": "No content in response"}

    async def run_decompose_compute(
        self,
        session,
        query: str,
        expected_value: float,
        tolerance: float = 0.02,
    ) -> EvalResult:
        """Run decompose → compute and verify result."""
        name = query

        try:
            # Step 1: decompose
            decompose_result = await self.call_tool(session, "decompose", {"query": query})

            if "error_type" in decompose_result:
                return EvalResult(
                    name=name,
                    passed=False,
                    expected=expected_value,
                    actual=None,
                    error=f"decompose: {decompose_result['error']}",
                )

            # Step 2: compute
            initial_value = decompose_result.get("initial_value") or 1.0
            compute_result = await self.call_tool(session, "compute", {
                "initial_value": initial_value,
                "initial_unit": decompose_result["initial_unit"],
                "factors": decompose_result["factors"],
            })

            if "error_type" in compute_result:
                return EvalResult(
                    name=name,
                    passed=False,
                    expected=expected_value,
                    actual=None,
                    error=f"compute: {compute_result['error']}",
                )

            # Step 3: verify
            actual = compute_result["quantity"]
            if expected_value == 0:
                passed = abs(actual) < 1e-5
            else:
                rel_error = abs(actual - expected_value) / abs(expected_value)
                passed = rel_error < tolerance

            return EvalResult(
                name=name,
                passed=passed,
                expected=expected_value,
                actual=actual,
                error=None if passed else f"rel_error={rel_error:.4f}",
            )

        except Exception as e:
            return EvalResult(
                name=name,
                passed=False,
                expected=expected_value,
                actual=None,
                error=str(e),
            )

    async def run_structured_decompose_compute(
        self,
        session,
        name: str,
        initial_value: float,
        initial_unit: str,
        target_unit: str,
        known_quantities: list[dict],
        expected_value: float,
        tolerance: float = 0.02,
    ) -> EvalResult:
        """Run structured decompose → compute and verify result."""
        try:
            # Step 1: decompose (structured mode)
            decompose_result = await self.call_tool(session, "decompose", {
                "initial_unit": initial_unit,
                "target_unit": target_unit,
                "known_quantities": known_quantities,
            })

            if "error_type" in decompose_result:
                return EvalResult(
                    name=name,
                    passed=False,
                    expected=expected_value,
                    actual=None,
                    error=f"decompose: {decompose_result['error']}",
                )

            # Step 2: compute
            compute_result = await self.call_tool(session, "compute", {
                "initial_value": initial_value,
                "initial_unit": decompose_result["initial_unit"],
                "factors": decompose_result["factors"],
            })

            if "error_type" in compute_result:
                return EvalResult(
                    name=name,
                    passed=False,
                    expected=expected_value,
                    actual=None,
                    error=f"compute: {compute_result['error']}",
                )

            # Step 3: verify
            actual = compute_result["quantity"]
            if expected_value == 0:
                passed = abs(actual) < 1e-5
            else:
                rel_error = abs(actual - expected_value) / abs(expected_value)
                passed = rel_error < tolerance

            return EvalResult(
                name=name,
                passed=passed,
                expected=expected_value,
                actual=actual,
                error=None if passed else f"rel_error={rel_error:.4f}",
            )

        except Exception as e:
            return EvalResult(
                name=name,
                passed=False,
                expected=expected_value,
                actual=None,
                error=str(e),
            )

    async def run_structured_expect_error(
        self,
        session,
        name: str,
        initial_unit: str,
        target_unit: str,
        known_quantities: list[dict],
        expect_hint: str | None = None,
    ) -> EvalResult:
        """Run structured decompose and expect an error, optionally checking for a hint."""
        try:
            result = await self.call_tool(session, "decompose", {
                "initial_unit": initial_unit,
                "target_unit": target_unit,
                "known_quantities": known_quantities,
            })

            if "error_type" not in result:
                return EvalResult(
                    name=name,
                    passed=False,
                    expected=None,
                    actual=None,
                    error=f"Expected error but got success: {result}",
                )

            # Check for expected hint if specified
            if expect_hint:
                hints = result.get("hints", [])
                hint_text = " ".join(hints)
                if expect_hint.lower() not in hint_text.lower():
                    return EvalResult(
                        name=name,
                        passed=False,
                        expected=None,
                        actual=None,
                        error=f"Error returned but missing hint '{expect_hint}'. Hints: {hints}",
                    )

            return EvalResult(name=name, passed=True, expected=None, actual=None)

        except Exception as e:
            return EvalResult(
                name=name,
                passed=False,
                expected=None,
                actual=None,
                error=str(e),
            )

    async def run_expect_error(
        self,
        session,
        query: str,
        description: str,
    ) -> EvalResult:
        """Run decompose and expect an error."""
        name = f"{query} (expect error)"

        try:
            result = await self.call_tool(session, "decompose", {"query": query})

            if "error_type" in result:
                return EvalResult(name=name, passed=True, expected=None, actual=None)
            else:
                return EvalResult(
                    name=name,
                    passed=False,
                    expected=None,
                    actual=None,
                    error=f"Expected error but got success: {result}",
                )

        except Exception as e:
            return EvalResult(
                name=name,
                passed=False,
                expected=None,
                actual=None,
                error=str(e),
            )

    async def run_all_tests(self, session) -> list[EvalResult]:
        """Run all evaluation tests."""
        results = []

        # === Basic Conversions ===
        print("\n--- Basic Conversions ---")
        basic_tests = [
            ("0.25 mg to mcg", 250),
            ("70 kg to lb", 154.32),
            ("50 psi to kPa", 344.74),
            ("10000 lbf to N", 44482),
            ("500 mL to L", 0.5),
            ("2.5 g to mg", 2500),
            ("35000 ft to m", 10668),
        ]
        for query, expected in basic_tests:
            result = await self.run_decompose_compute(session, query, expected)
            results.append(result)
            self._print_result(result)

        # === Composite Units ===
        print("\n--- Composite Units ---")
        composite_tests = [
            ("1 m/s to km/h", 3.6),
            ("100 gal/min to m^3/h", 22.71),
            ("1000 kg/h to lb/s", 0.6124),
            ("120 mL/h to L/day", 2.88),
            ("9.81 m/s^2 to ft/s^2", 32.185),
        ]
        for query, expected in composite_tests:
            result = await self.run_decompose_compute(session, query, expected)
            results.append(result)
            self._print_result(result)

        # === Structured Mode ===
        print("\n--- Structured Mode ---")

        # Eval 2.1: Weight-based dosing
        result = await self.run_structured_decompose_compute(
            session,
            name="Eval 2.1: Dopamine 5 mcg/kg/min, 70 kg → mg/h",
            initial_value=5,
            initial_unit="mcg/(kg*min)",
            target_unit="mg/h",
            known_quantities=[{"value": 70, "unit": "kg"}],
            expected_value=21.0,
        )
        results.append(result)
        self._print_result(result)

        # Eval 2.3: Concentration with separate quantities
        result = await self.run_structured_decompose_compute(
            session,
            name="Eval 2.3: Dopamine 5 mcg/kg/min, 80 kg, 400 mg/250 mL → mL/h",
            initial_value=5,
            initial_unit="mcg/(kg*min)",
            target_unit="mL/h",
            known_quantities=[
                {"value": 80, "unit": "kg"},
                {"value": 250, "unit": "mL"},
                {"value": 400, "unit": "mg"},
            ],
            expected_value=15.0,
        )
        results.append(result)
        self._print_result(result)

        # Eval 2.3b: Concentration pre-composed
        result = await self.run_structured_decompose_compute(
            session,
            name="Eval 2.3b: Dopamine 5 mcg/kg/min, 80 kg, 0.625 mL/mg → mL/h",
            initial_value=5,
            initial_unit="mcg/(kg*min)",
            target_unit="mL/h",
            known_quantities=[
                {"value": 80, "unit": "kg"},
                {"value": 0.625, "unit": "mL/mg"},
            ],
            expected_value=15.0,
        )
        results.append(result)
        self._print_result(result)

        # Eval 2.4: Dosing with count rate
        result = await self.run_structured_decompose_compute(
            session,
            name="Eval 2.4: 25 mg/kg/d, 15 kg, 3 ea/d → mg",
            initial_value=25,
            initial_unit="mg/(kg*d)",
            target_unit="mg",
            known_quantities=[
                {"value": 15, "unit": "kg"},
                {"value": 3, "unit": "ea/d"},
            ],
            expected_value=125.0,
        )
        results.append(result)
        self._print_result(result)

        # Eval 2.4 error: bare count diagnostic
        result = await self.run_structured_expect_error(
            session,
            name="Eval 2.4 error: bare ea returns diagnostic",
            initial_unit="mg/(kg*d)",
            target_unit="mg",
            known_quantities=[
                {"value": 15, "unit": "kg"},
                {"value": 3, "unit": "ea"},
            ],
            expect_hint="ea/d",
        )
        results.append(result)
        self._print_result(result)

        # Eval 3.1: Specific impulse
        result = await self.run_structured_decompose_compute(
            session,
            name="Eval 3.1: Isp 300 s × g₀ 9.80665 m/s² → m/s",
            initial_value=300,
            initial_unit="s",
            target_unit="m/s",
            known_quantities=[{"value": 9.80665, "unit": "m/s^2"}],
            expected_value=2941.995,
        )
        results.append(result)
        self._print_result(result)

        # === Error Cases ===
        print("\n--- Error Cases (expect rejection) ---")
        error_tests = [
            ("100 mg to mL", "mass ≠ volume"),
            ("5 foobar to m", "unknown unit"),
            ("1000 lb to N", "mass ≠ force"),
            ("5 m to kg", "length ≠ mass"),
        ]
        for query, desc in error_tests:
            result = await self.run_expect_error(session, query, desc)
            results.append(result)
            self._print_result(result)

        return results

    def _print_result(self, result: EvalResult):
        """Print a single result."""
        status = "✓" if result.passed else "✗"
        if result.passed:
            if result.expected is not None:
                print(f"  {status} {result.name}: {result.actual:.4g} (expected {result.expected})")
            else:
                print(f"  {status} {result.name}")
        else:
            print(f"  {status} {result.name}: {result.error}")

    async def run_stdio(self):
        """Run eval against stdio subprocess."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        print("Spawning ucon-mcp server via stdio...")

        # Use the ucon-mcp entry point or fall back to module invocation
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from ucon.tools.mcp.server import main; main()"],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Connected to server.\n")

                self.results = await self.run_all_tests(session)

    async def run_sse(self, url: str):
        """Run eval against SSE server."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        print(f"Connecting to SSE server at {url}...")

        try:
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    print("Connected to server.\n")

                    self.results = await self.run_all_tests(session)
        except* Exception as eg:
            # Extract the root cause from exception groups
            for exc in eg.exceptions:
                if "ConnectError" in type(exc).__name__ or "connection" in str(exc).lower():
                    print(f"\n{Colors.RED}Connection failed:{Colors.RESET} {url}")
                    print(f"\nMake sure the SSE server is running:")
                    print(f"  ucon-mcp --sse --port 8000")
                    print(f"\nOr run without SSE_URL to spawn a stdio server automatically:")
                    print(f"  make eval-decompose-live")
                    sys.exit(1)
            # Re-raise if not a connection error
            raise

    def print_summary(self):
        """Print summary of results."""
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        failed = total - passed

        print("\n" + "=" * 60)
        print("LIVE SERVER EVAL SUMMARY")
        print("=" * 60)
        print(f"  Passed: {passed}/{total}")
        print(f"  Failed: {failed}/{total}")

        if failed > 0:
            print("\nFailed tests:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.error}")

        print("=" * 60)

        return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="Run decompose eval against live MCP server"
    )
    parser.add_argument(
        "--sse",
        metavar="URL",
        help="SSE server URL (e.g., http://localhost:8000/sse)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    eval_harness = LiveServerEval(sse_url=args.sse, verbose=args.verbose)

    if args.sse:
        asyncio.run(eval_harness.run_sse(args.sse))
    else:
        asyncio.run(eval_harness.run_stdio())

    success = eval_harness.print_summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

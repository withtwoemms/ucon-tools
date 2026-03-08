#!/usr/bin/env python
# © 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0
# See the LICENSE file for details.

"""
Natural Language Problem Evaluation for MCP Tools.

This eval tests complex natural language problems that require:
1. Understanding multi-value problems (e.g., "5 mcg/kg/min for a 70 kg patient")
2. Building factor chains with multiple conversion steps
3. Handling concentrations, rates, and dosage calculations

These problems go beyond simple "X to Y" conversions and test the full
capability of the MCP tooling when paired with an LLM.

Usage:
    # Test which problems decompose can handle directly
    python scripts/eval_natural_language_problems.py --analyze

    # Test with live MCP server (stdio)
    python scripts/eval_natural_language_problems.py

    # Test against SSE server
    python scripts/eval_natural_language_problems.py --sse http://localhost:8000/sse
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class Colors:
    """ANSI color codes."""
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN = "\033[0;36m"
    GRAY = "\033[0;90m"
    RESET = "\033[0m"


@dataclass
class Problem:
    """A natural language conversion problem."""
    id: str
    domain: str
    difficulty: str
    problem: str
    expected_value: float | None
    expected_unit: str
    tolerance: float | None = 0.02
    must_fail: bool = False
    # For complex problems, the factor chain that compute needs
    compute_input: dict | None = None


@dataclass
class EvalResult:
    """Result of evaluating a problem."""
    problem: Problem
    decompose_success: bool = False
    decompose_result: dict | None = None
    compute_success: bool = False
    compute_result: dict | None = None
    final_value: float | None = None
    passed: bool = False
    error: str | None = None
    notes: list[str] = field(default_factory=list)


# =============================================================================
# Problem Set (from problems.json)
# =============================================================================

PROBLEMS = [
    # --- Nursing: Simple (decompose should handle) ---
    Problem(
        id="N07", domain="nursing", difficulty="easy",
        problem="Convert 0.25 mg to mcg.",
        expected_value=250, expected_unit="mcg",
    ),
    Problem(
        id="N11", domain="nursing", difficulty="easy",
        problem="Convert 2.5 g to mg.",
        expected_value=2500, expected_unit="mg",
    ),
    Problem(
        id="N15", domain="nursing", difficulty="easy",
        problem="Convert 500 mL to liters.",
        expected_value=0.5, expected_unit="L",
    ),
    Problem(
        id="N08", domain="nursing", difficulty="easy",
        problem="Maintenance IV fluids: 3 L/day. Calculate the rate in mL/hour.",
        expected_value=125, expected_unit="mL/h",
    ),

    # --- Nursing: Complex (require factor chains) ---
    Problem(
        id="N03", domain="nursing", difficulty="medium",
        problem="IV order: 1000 mL normal saline over 8 hours. Using a 15 gtt/mL drip set, calculate the drip rate in gtt/min.",
        expected_value=31.25, expected_unit="gtt/min",
        compute_input={
            "initial_value": 1000,
            "initial_unit": "mL",
            "factors": [
                {"value": 1, "numerator": "ea", "denominator": "8 h"},
                {"value": 1, "numerator": "h", "denominator": "60 min"},
                {"value": 15, "numerator": "gtt", "denominator": "mL"},
            ],
            "custom_units": [{"name": "drop", "dimension": "count", "aliases": ["gtt"]}],
        },
    ),
    Problem(
        id="N04", domain="nursing", difficulty="hard",
        problem="Dopamine drip ordered at 5 mcg/kg/min for a 70 kg patient. What is the infusion rate in mg/hour?",
        expected_value=21, expected_unit="mg/h",
        compute_input={
            "initial_value": 5,
            "initial_unit": "mcg/(kg*min)",
            "factors": [
                {"value": 70, "numerator": "kg", "denominator": "ea"},
                {"value": 60, "numerator": "min", "denominator": "h"},
                {"value": 1, "numerator": "mg", "denominator": "1000 mcg"},
            ],
        },
    ),
    Problem(
        id="N05", domain="nursing", difficulty="medium",
        problem="Heparin protocol: 18 units/kg bolus. Patient weighs 82 kg. How many units for the bolus?",
        expected_value=1476, expected_unit="units",
        compute_input={
            "initial_value": 18,
            "initial_unit": "units/kg",
            "factors": [
                {"value": 82, "numerator": "kg", "denominator": "ea"},
            ],
            "custom_units": [{"name": "unit", "dimension": "count", "aliases": ["units"]}],
        },
    ),
    Problem(
        id="N06", domain="nursing", difficulty="medium",
        problem="Pediatric amoxicillin: 25 mg/kg/day divided q8h. Child weighs 15 kg. Dose per administration?",
        expected_value=125, expected_unit="mg",
        compute_input={
            "initial_value": 25,
            "initial_unit": "mg/(kg*day)",
            "factors": [
                {"value": 15, "numerator": "kg", "denominator": "ea"},
                {"value": 1, "numerator": "day", "denominator": "3 ea"},
            ],
        },
    ),
    Problem(
        id="N19", domain="nursing", difficulty="hard",
        problem="Propofol 10 mg/mL running at 50 mcg/kg/min for 80 kg patient. mL/hour rate?",
        expected_value=24, expected_unit="mL/h",
        compute_input={
            "initial_value": 50,
            "initial_unit": "mcg/(kg*min)",
            "factors": [
                {"value": 80, "numerator": "kg", "denominator": "ea"},
                {"value": 60, "numerator": "min", "denominator": "h"},
                {"value": 1, "numerator": "mg", "denominator": "1000 mcg"},
                {"value": 1, "numerator": "mL", "denominator": "10 mg"},
            ],
        },
    ),
    Problem(
        id="N24", domain="nursing", difficulty="medium",
        problem="100 mL over 20 minutes. Rate in mL/h?",
        expected_value=300, expected_unit="mL/h",
        compute_input={
            "initial_value": 100,
            "initial_unit": "mL",
            "factors": [
                {"value": 1, "numerator": "ea", "denominator": "20 min"},
                {"value": 60, "numerator": "min", "denominator": "h"},
            ],
        },
    ),
    Problem(
        id="N18", domain="nursing", difficulty="medium",
        problem="Lidocaine 2% solution. How many mg per mL?",
        expected_value=20, expected_unit="mg/mL",
        # This is a percentage → concentration conversion
        # 2% = 2g/100mL = 0.02 g/mL = 20 mg/mL
        compute_input={
            "initial_value": 0.02,
            "initial_unit": "g/mL",
            "factors": [
                {"value": 1000, "numerator": "mg", "denominator": "g"},
            ],
        },
    ),

    # --- Nursing: Must Fail ---
    Problem(
        id="N21", domain="nursing", difficulty="must_fail",
        problem="Convert 100 mg directly to mL without knowing concentration.",
        expected_value=None, expected_unit="error",
        must_fail=True,
    ),

    # --- Chemical Engineering ---
    Problem(
        id="C03", domain="chemeng", difficulty="easy",
        problem="Convert volumetric flow: 100 gal/min to m³/h",
        expected_value=22.71, expected_unit="m³/h",
    ),
    Problem(
        id="C04", domain="chemeng", difficulty="easy",
        problem="Convert pressure: 50 psi to kPa",
        expected_value=344.74, expected_unit="kPa",
    ),

    # --- Aerospace ---
    Problem(
        id="A01", domain="aerospace", difficulty="easy",
        problem="Convert thrust: 10000 lbf to Newtons",
        expected_value=44482, expected_unit="N",
    ),
    Problem(
        id="A03", domain="aerospace", difficulty="must_fail",
        problem="Convert 1000 lbm (pound-mass) directly to Newtons (force)",
        expected_value=None, expected_unit="error",
        must_fail=True,
    ),
]


class NaturalLanguageEval:
    """Evaluation harness for natural language problems."""

    def __init__(self, verbose: bool = False):
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

    def extract_simple_query(self, problem: Problem) -> str | None:
        """Try to extract a simple 'X to Y' query from the problem text.

        Returns None if the problem is too complex for decompose.
        """
        import re

        # Use original case (unit names are case-sensitive)
        text = problem.problem

        # Pattern: "convert X to Y" (with optional description before value)
        # e.g., "Convert 0.25 mg to mcg" or "Convert volumetric flow: 100 gal/min to m³/h"
        match = re.search(
            r'[Cc]onvert\s+(?:[\w\s]+:\s*)?([\d.]+\s*[\w/³²µ]+)\s+to\s+([\w/³²µ]+)',
            text
        )
        if match:
            return f"{match.group(1)} to {match.group(2)}"

        # Pattern: "X. Calculate/rate in Y"
        # e.g., "3 L/day. Calculate the rate in mL/hour"
        match = re.search(
            r'([\d.]+\s*[\w/]+)[.,]\s*(?:[Cc]alculate|[Rr]ate|[Cc]onvert).*?in\s+([\w/]+)',
            text
        )
        if match:
            return f"{match.group(1)} to {match.group(2)}"

        return None

    async def eval_problem(self, session, problem: Problem) -> EvalResult:
        """Evaluate a single problem."""
        result = EvalResult(problem=problem)

        # Step 1: Try decompose with extracted query
        simple_query = self.extract_simple_query(problem)

        if simple_query:
            result.notes.append(f"Extracted query: '{simple_query}'")
            decompose_result = await self.call_tool(session, "decompose", {"query": simple_query})
            result.decompose_result = decompose_result

            if "error_type" not in decompose_result:
                result.decompose_success = True

                # Try compute with decompose output
                initial_value = decompose_result.get("initial_value") or 1.0
                compute_result = await self.call_tool(session, "compute", {
                    "initial_value": initial_value,
                    "initial_unit": decompose_result["initial_unit"],
                    "factors": decompose_result["factors"],
                })
                result.compute_result = compute_result

                if "error_type" not in compute_result:
                    result.compute_success = True
                    result.final_value = compute_result["quantity"]
            else:
                result.notes.append(f"decompose failed: {decompose_result.get('error', 'unknown')}")
        else:
            result.notes.append("No simple query extractable - requires factor chain")

        # Step 2: If decompose failed but we have compute_input, try direct compute
        if not result.compute_success and problem.compute_input:
            result.notes.append("Trying provided factor chain")
            compute_result = await self.call_tool(session, "compute", problem.compute_input)
            result.compute_result = compute_result

            if "error_type" not in compute_result:
                result.compute_success = True
                result.final_value = compute_result["quantity"]
            else:
                result.error = compute_result.get("error", "compute failed")

        # Step 3: Check result
        if problem.must_fail:
            # Should have failed
            result.passed = not result.compute_success
            if not result.passed:
                result.error = "Expected failure but succeeded"
        elif result.final_value is not None and problem.expected_value is not None:
            # Check tolerance
            rel_error = abs(result.final_value - problem.expected_value) / abs(problem.expected_value)
            result.passed = rel_error < (problem.tolerance or 0.02)
            if not result.passed:
                result.error = f"Expected {problem.expected_value}, got {result.final_value} (rel_error={rel_error:.4f})"
        else:
            result.passed = False
            if not result.error:
                result.error = "No result produced"

        return result

    async def run_all(self, session) -> list[EvalResult]:
        """Run all problems."""
        results = []

        for problem in PROBLEMS:
            result = await self.eval_problem(session, problem)
            results.append(result)
            self._print_result(result)

        return results

    def _print_result(self, result: EvalResult):
        """Print a single result."""
        p = result.problem
        status = f"{Colors.GREEN}✓{Colors.RESET}" if result.passed else f"{Colors.RED}✗{Colors.RESET}"

        # Difficulty color
        diff_color = {
            "easy": Colors.GREEN,
            "medium": Colors.YELLOW,
            "hard": Colors.RED,
            "must_fail": Colors.GRAY,
        }.get(p.difficulty, "")

        print(f"\n{status} [{p.id}] {diff_color}{p.difficulty}{Colors.RESET} - {p.domain}")
        print(f"   {Colors.CYAN}{p.problem[:80]}{'...' if len(p.problem) > 80 else ''}{Colors.RESET}")

        if result.decompose_success:
            print(f"   {Colors.GREEN}decompose: ✓{Colors.RESET}")
        else:
            print(f"   {Colors.YELLOW}decompose: ✗ (needs factor chain){Colors.RESET}")

        if result.passed:
            if result.final_value is not None:
                print(f"   Result: {result.final_value:.4g} {p.expected_unit}")
        else:
            print(f"   {Colors.RED}Error: {result.error}{Colors.RESET}")

        if self.verbose:
            for note in result.notes:
                print(f"   {Colors.GRAY}→ {note}{Colors.RESET}")

    async def run_stdio(self):
        """Run eval against stdio subprocess."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        print("Spawning ucon-mcp server via stdio...")

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from ucon.tools.mcp.server import main; main()"],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Register custom units needed for nursing problems
                await self._setup_custom_units(session)

                print("Connected. Running evaluation...\n")
                self.results = await self.run_all(session)

    async def run_sse(self, url: str):
        """Run eval against SSE server."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        print(f"Connecting to SSE server at {url}...")

        try:
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Register custom units
                    await self._setup_custom_units(session)

                    print("Connected. Running evaluation...\n")
                    self.results = await self.run_all(session)
        except* Exception as eg:
            for exc in eg.exceptions:
                if "ConnectError" in type(exc).__name__ or "connection" in str(exc).lower():
                    print(f"\n{Colors.RED}Connection failed:{Colors.RESET} {url}")
                    print(f"\nMake sure the SSE server is running:")
                    print(f"  ucon-mcp --sse --port 8000")
                    sys.exit(1)
            raise

    async def _setup_custom_units(self, session):
        """Register custom units needed for nursing problems."""
        # Register 'drop' unit for IV drip calculations
        await self.call_tool(session, "define_unit", {
            "name": "drop",
            "dimension": "count",
            "aliases": ["gtt", "drops"],
        })

        # Register 'unit' for heparin/insulin
        await self.call_tool(session, "define_unit", {
            "name": "unit",
            "dimension": "count",
            "aliases": ["units", "U", "IU"],
        })

    def print_summary(self):
        """Print summary of results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        decompose_ok = sum(1 for r in self.results if r.decompose_success)

        print("\n" + "=" * 70)
        print("NATURAL LANGUAGE PROBLEM EVALUATION SUMMARY")
        print("=" * 70)

        # By difficulty
        by_diff = {}
        for r in self.results:
            d = r.problem.difficulty
            if d not in by_diff:
                by_diff[d] = {"total": 0, "passed": 0, "decompose": 0}
            by_diff[d]["total"] += 1
            if r.passed:
                by_diff[d]["passed"] += 1
            if r.decompose_success:
                by_diff[d]["decompose"] += 1

        print("\nBy Difficulty:")
        for diff in ["easy", "medium", "hard", "must_fail"]:
            if diff in by_diff:
                d = by_diff[diff]
                print(f"  {diff:12s}: {d['passed']}/{d['total']} passed, "
                      f"{d['decompose']}/{d['total']} via decompose")

        # By domain
        by_domain = {}
        for r in self.results:
            d = r.problem.domain
            if d not in by_domain:
                by_domain[d] = {"total": 0, "passed": 0}
            by_domain[d]["total"] += 1
            if r.passed:
                by_domain[d]["passed"] += 1

        print("\nBy Domain:")
        for domain, counts in by_domain.items():
            print(f"  {domain:12s}: {counts['passed']}/{counts['total']} passed")

        print("-" * 70)
        print(f"Total: {passed}/{total} passed")
        print(f"Decompose coverage: {decompose_ok}/{total} problems handled by decompose alone")
        print("=" * 70)

        # Analysis
        print("\n" + "=" * 70)
        print("ANALYSIS: decompose vs compute")
        print("=" * 70)
        print(f"""
Problems that decompose handles directly: {decompose_ok}
  - Simple "X to Y" conversions
  - Composite unit conversions (m/s to km/h)

Problems requiring factor chains: {total - decompose_ok}
  - Multi-value problems (weight × dose rate)
  - Concentration calculations
  - Time-based infusion rates
  - Percentage conversions

For complex problems, an LLM must:
  1. Parse quantities from natural language
  2. Construct the factor chain
  3. Call compute() with the chain

The decompose tool serves as a shortcut for simple conversions,
reducing LLM workload for the ~{100*decompose_ok//total}% of problems it handles.
""")
        print("=" * 70)

        return passed == total

    def analyze_only(self):
        """Analyze problems without running against server."""
        print("=" * 70)
        print("PROBLEM ANALYSIS (no server)")
        print("=" * 70)

        simple = []
        complex_probs = []

        for p in PROBLEMS:
            query = self.extract_simple_query(p)
            # Simple if we can extract a query AND no complex factor chain is needed
            if query and not p.compute_input and not p.must_fail:
                simple.append((p, query))
            else:
                complex_probs.append(p)

        print(f"\n{Colors.GREEN}Simple (decompose can handle):{Colors.RESET}")
        for p, q in simple:
            print(f"  [{p.id}] {p.problem[:60]}...")
            print(f"       → decompose('{q}')")

        print(f"\n{Colors.YELLOW}Complex (require factor chains):{Colors.RESET}")
        for p in complex_probs:
            print(f"  [{p.id}] {p.problem[:60]}...")
            if p.compute_input:
                factors = p.compute_input.get("factors", [])
                print(f"       → {len(factors)} factor steps")
            elif p.must_fail:
                print(f"       → Expected to fail (dimension mismatch)")

        print(f"\nSummary: {len(simple)} simple, {len(complex_probs)} complex")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate natural language problems against MCP server"
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
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze problems without running against server",
    )
    args = parser.parse_args()

    eval_harness = NaturalLanguageEval(verbose=args.verbose)

    if args.analyze:
        eval_harness.analyze_only()
        return

    if args.sse:
        asyncio.run(eval_harness.run_sse(args.sse))
    else:
        asyncio.run(eval_harness.run_stdio())

    success = eval_harness.print_summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

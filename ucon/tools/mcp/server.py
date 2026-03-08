# ucon MCP Server
#
# Provides unit conversion and dimensional analysis tools for AI agents.
#
# Usage:
#   ucon-mcp              # Run via entry point
#   python -m ucon.mcp    # Run as module

import hashlib
import json
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel

from ucon import Dimension, get_default_graph
from ucon.dimension import all_dimensions
from ucon.core import Number, Scale, Unit, UnitProduct
from ucon.units import get_unit_by_name
from ucon.graph import ConversionGraph, DimensionMismatch, ConversionNotFound, using_graph
from ucon.maps import LinearMap
from ucon.tools.mcp.formulas import list_formulas as _list_formulas, get_formula
from ucon.tools.mcp.session import SessionState, DefaultSessionState
from ucon.tools.mcp.suggestions import (
    ConversionError,
    resolve_unit,
    build_dimension_mismatch_error,
    build_no_path_error,
    build_unknown_dimension_error,
)
from ucon.packages import EdgeDef, PackageLoadError, UnitDef


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Server lifespan - creates session state that persists across tool calls."""
    yield {"session": DefaultSessionState()}


mcp = FastMCP("ucon", lifespan=lifespan)


# -----------------------------------------------------------------------------
# Session Graph Management
# -----------------------------------------------------------------------------

# Cache for inline graph compilation (keyed by hash of definitions)
_inline_graph_cache: dict[str, ConversionGraph] = {}


def _get_session(ctx: Context | None) -> SessionState:
    """Extract session state from context.

    Falls back to a default session for direct function calls (testing).
    """
    if ctx is not None and hasattr(ctx, 'request_context'):
        lifespan_ctx = ctx.request_context.lifespan_context
        if lifespan_ctx and "session" in lifespan_ctx:
            return lifespan_ctx["session"]
    # Fallback for direct calls (testing without MCP context)
    return _get_fallback_session()


# Fallback session for testing without MCP context
_fallback_session: DefaultSessionState | None = None


def _get_fallback_session() -> DefaultSessionState:
    """Get or create fallback session for direct function calls."""
    global _fallback_session
    if _fallback_session is None:
        _fallback_session = DefaultSessionState()
    return _fallback_session


def _reset_fallback_session() -> None:
    """Reset the fallback session (for testing)."""
    global _fallback_session
    if _fallback_session is not None:
        _fallback_session.reset()


def _resolve_constant(symbol: str, ctx: Context | None = None):
    """Resolve a constant symbol from built-in or session constants."""
    from ucon.constants import get_constant_by_symbol

    # Try built-in first
    const = get_constant_by_symbol(symbol)
    if const is not None:
        return const

    # Try session constants
    session = _get_session(ctx)
    return session.get_constants().get(symbol)


def _hash_definitions(
    custom_units: list[dict] | None,
    custom_edges: list[dict] | None,
) -> str:
    """Compute a stable hash for inline definitions."""
    data = {
        'units': sorted([json.dumps(u, sort_keys=True) for u in (custom_units or [])]),
        'edges': sorted([json.dumps(e, sort_keys=True) for e in (custom_edges or [])]),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def _build_inline_graph(
    custom_units: list[dict] | None,
    custom_edges: list[dict] | None,
    base_graph: ConversionGraph | None = None,
) -> tuple[ConversionGraph | None, ConversionError | None]:
    """Build an ephemeral graph with inline definitions.

    Returns (graph, None) on success, (None, error) on failure.
    Uses caching to avoid redundant compilation.
    """
    if not custom_units and not custom_edges:
        return None, None

    # Check cache
    cache_key = _hash_definitions(custom_units, custom_edges)
    if cache_key in _inline_graph_cache:
        return _inline_graph_cache[cache_key], None

    # Build new graph from provided base (or default)
    if base_graph is None:
        base_graph = get_default_graph()
    graph = base_graph.copy()

    # Register custom units first
    for i, unit_dict in enumerate(custom_units or []):
        try:
            unit_def = UnitDef(
                name=unit_dict.get('name', ''),
                dimension=unit_dict.get('dimension', ''),
                aliases=tuple(unit_dict.get('aliases', ())),
            )
            unit = unit_def.materialize()
            graph.register_unit(unit)
        except PackageLoadError as e:
            return None, ConversionError(
                error=str(e),
                error_type="invalid_input",
                parameter=f"custom_units[{i}]",
                hints=["Check dimension name is valid (use list_dimensions())"],
            )
        except Exception as e:
            return None, ConversionError(
                error=f"Invalid unit definition: {e}",
                error_type="invalid_input",
                parameter=f"custom_units[{i}]",
                hints=["Unit needs 'name' and 'dimension' fields"],
            )

    # Add custom edges
    for i, edge_dict in enumerate(custom_edges or []):
        try:
            edge_def = EdgeDef(
                src=edge_dict.get('src', ''),
                dst=edge_dict.get('dst', ''),
                factor=float(edge_dict.get('factor', 1.0)),
            )
            edge_def.materialize(graph)
        except PackageLoadError as e:
            return None, ConversionError(
                error=str(e),
                error_type="invalid_input",
                parameter=f"custom_edges[{i}]",
                hints=["Check that src and dst units are defined"],
            )
        except Exception as e:
            return None, ConversionError(
                error=f"Invalid edge definition: {e}",
                error_type="invalid_input",
                parameter=f"custom_edges[{i}]",
                hints=["Edge needs 'src', 'dst', and 'factor' fields"],
            )

    # Cache the compiled graph
    _inline_graph_cache[cache_key] = graph
    return graph, None


# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------


class ConversionResult(BaseModel):
    """Result of a unit conversion."""

    quantity: float
    unit: str | None
    dimension: str
    uncertainty: float | None = None


class UnitInfo(BaseModel):
    """Information about an available unit."""

    name: str
    shorthand: str
    aliases: list[str]
    dimension: str
    scalable: bool


class ScaleInfo(BaseModel):
    """Information about a scale prefix."""

    name: str
    prefix: str
    factor: float


class DimensionCheck(BaseModel):
    """Result of a dimensional compatibility check."""

    compatible: bool
    dimension_a: str
    dimension_b: str


class ComputeStep(BaseModel):
    """A single step in a compute chain."""

    factor: str
    dimension: str
    unit: str


class ComputeResult(BaseModel):
    """Result of a multi-step factor-label computation."""

    quantity: float
    unit: str
    dimension: str
    steps: list[ComputeStep]


class SessionResult(BaseModel):
    """Result of a session management operation."""

    success: bool
    message: str


class UnitDefinitionResult(BaseModel):
    """Result of defining a custom unit."""

    success: bool
    name: str
    dimension: str
    aliases: list[str]
    message: str


class ConversionDefinitionResult(BaseModel):
    """Result of defining a custom conversion."""

    success: bool
    src: str
    dst: str
    factor: float
    message: str


class FormulaInfoResponse(BaseModel):
    """Metadata about a registered formula."""

    name: str
    description: str
    parameters: dict[str, str | None]


class FormulaResult(BaseModel):
    """Result of calling a registered formula."""

    formula: str
    quantity: float
    unit: str | None
    dimension: str
    uncertainty: float | None = None


class FormulaError(BaseModel):
    """Error from calling a formula."""

    error: str
    error_type: str  # "unknown_formula", "invalid_parameter", "dimension_mismatch", "missing_parameter"
    formula: str | None = None
    parameter: str | None = None
    expected: str | None = None
    got: str | None = None
    hints: list[str] = []


class DecomposeResult(BaseModel):
    """Result of decomposing a conversion query into a compute-ready factor chain."""

    initial_value: float | None
    initial_unit: str
    target_unit: str
    factors: list[dict]


class ConstantInfo(BaseModel):
    """Information about a physical constant."""

    symbol: str
    name: str
    value: float
    unit: str | None
    dimension: str
    uncertainty: float | None
    is_exact: bool
    source: str
    category: str  # "exact", "derived", "measured", "session"


class ConstantDefinitionResult(BaseModel):
    """Result of defining a custom constant."""

    success: bool
    symbol: str
    name: str
    unit: str
    uncertainty: float | None
    message: str


class ConstantError(BaseModel):
    """Error from constant operations."""

    error: str
    error_type: str  # "duplicate_symbol", "invalid_unit", "invalid_value", "unknown_constant", "invalid_input"
    parameter: str | None = None
    hints: list[str] = []


def _constant_to_info(const, category: str | None = None) -> ConstantInfo:
    """Convert a Constant to ConstantInfo for MCP response."""
    unit_str = None
    if hasattr(const.unit, 'shorthand'):
        unit_str = const.unit.shorthand
    elif hasattr(const.unit, 'name'):
        unit_str = const.unit.name
    else:
        unit_str = str(const.unit)

    dim_name = const.dimension.name if hasattr(const.dimension, 'name') else str(const.dimension)

    return ConstantInfo(
        symbol=const.symbol,
        name=const.name,
        value=const.value,
        unit=unit_str,
        dimension=dim_name,
        uncertainty=const.uncertainty,
        is_exact=const.is_exact,
        source=const.source,
        category=category or getattr(const, 'category', 'measured'),
    )


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------


@mcp.tool()
def convert(
    value: float,
    from_unit: str,
    to_unit: str,
    custom_units: list[dict] | None = None,
    custom_edges: list[dict] | None = None,
    ctx: Context | None = None,
) -> ConversionResult | ConversionError:
    """
    Convert a numeric value from one unit to another.

    Units can be specified as:
    - Base units: "meter", "m", "second", "s", "gram", "g"
    - Scaled units: "km", "mL", "kg", "MHz" (use list_scales for prefixes)
    - Composite units: "m/s", "kg*m/s^2", "N*m"
    - Exponents: "m^2", "s^-1" (ASCII) or "m²", "s⁻¹" (Unicode)

    For custom/domain-specific units, you can either:
    1. Use define_unit() and define_conversion() to register them for the session
    2. Pass them inline via custom_units and custom_edges parameters

    Args:
        value: The numeric quantity to convert.
        from_unit: Source unit string.
        to_unit: Target unit string.
        custom_units: Optional list of inline unit definitions for this call only.
            Each dict should have: {"name": str, "dimension": str, "aliases": [str]}
        custom_edges: Optional list of inline conversion edges for this call only.
            Each dict should have: {"src": str, "dst": str, "factor": float}

    Returns:
        ConversionResult with converted quantity, unit, and dimension.
        ConversionError if the conversion fails, with suggestions for correction.

    Example with inline definitions:
        convert(1, "slug", "kg",
            custom_units=[{"name": "slug", "dimension": "mass", "aliases": ["slug"]}],
            custom_edges=[{"src": "slug", "dst": "kg", "factor": 14.5939}])
    """
    session = _get_session(ctx)
    session_graph = session.get_graph()

    # Build inline graph if custom definitions provided
    inline_graph, err = _build_inline_graph(custom_units, custom_edges, session_graph)
    if err:
        return err

    # Use inline graph or session graph
    graph = inline_graph or session_graph

    # Perform resolution and conversion within graph context
    with using_graph(graph):
        # 1. Parse source unit
        src, err = resolve_unit(from_unit, parameter="from_unit")
        if err:
            return err

        # 2. Parse target unit
        dst, err = resolve_unit(to_unit, parameter="to_unit")
        if err:
            return err

        # 3. Perform conversion
        try:
            num = Number(quantity=value, unit=src)
            result = num.to(dst, graph=graph)
        except DimensionMismatch:
            return build_dimension_mismatch_error(from_unit, to_unit, src, dst)
        except ConversionNotFound as e:
            return build_no_path_error(from_unit, to_unit, src, dst, e)

    # Use the target unit string as output (what the user asked for).
    # This handles cases like mg/kg → µg/kg where internal representation
    # may lose unit info due to dimension cancellation.
    unit_str = to_unit
    dim_name = dst.dimension.name if hasattr(dst, 'dimension') else "none"

    return ConversionResult(
        quantity=result.quantity,
        unit=unit_str,
        dimension=dim_name,
        uncertainty=result.uncertainty,
    )


@mcp.tool()
def list_units(
    dimension: str | None = None,
    ctx: Context | None = None,
) -> list[UnitInfo] | ConversionError:
    """
    List available units, optionally filtered by dimension.

    Returns base units only. Use scale prefixes (from list_scales) to form
    scaled variants. For example, "meter" with prefix "k" becomes "km".

    Includes both built-in units and session-defined units (from define_unit).

    Args:
        dimension: Optional filter by dimension name (e.g., "length", "mass", "time").
                   Use list_dimensions() to see available dimensions.

    Returns:
        List of UnitInfo objects describing available units.
        ConversionError if the dimension filter is invalid.
    """
    import ucon.units as units_module

    # Validate dimension filter if provided
    if dimension:
        known_dimensions = [d.name for d in all_dimensions()]
        if dimension not in known_dimensions:
            return build_unknown_dimension_error(dimension)

    # Units that accept SI scale prefixes
    SCALABLE_UNITS = {
        "meter", "gram", "second", "ampere", "kelvin", "mole", "candela",
        "hertz", "newton", "pascal", "joule", "watt", "coulomb", "volt",
        "farad", "ohm", "siemens", "weber", "tesla", "henry", "lumen",
        "lux", "becquerel", "gray", "sievert", "katal",
        "liter", "byte",
    }

    result = []
    seen_names = set()

    # Built-in units from ucon.units module
    for name in dir(units_module):
        obj = getattr(units_module, name)
        if isinstance(obj, Unit) and obj.name and obj.name not in seen_names:
            seen_names.add(obj.name)

            if dimension and obj.dimension.name != dimension:
                continue

            result.append(
                UnitInfo(
                    name=obj.name,
                    shorthand=obj.shorthand,
                    aliases=list(obj.aliases) if obj.aliases else [],
                    dimension=obj.dimension.name,
                    scalable=obj.name in SCALABLE_UNITS,
                )
            )

    # Session-defined units from graph registry
    session = _get_session(ctx)
    graph = session.get_graph()

    # Get unique units from graph's case-sensitive registry
    # (registry maps names/aliases to units, so we need unique values)
    session_units = set(graph._name_registry_cs.values())
    for unit in session_units:
        if unit.name and unit.name not in seen_names:
            seen_names.add(unit.name)

            if dimension and unit.dimension.name != dimension:
                continue

            result.append(
                UnitInfo(
                    name=unit.name,
                    shorthand=unit.shorthand or unit.name,
                    aliases=list(unit.aliases) if unit.aliases else [],
                    dimension=unit.dimension.name,
                    scalable=False,  # Session units are not scalable by default
                )
            )

    return sorted(result, key=lambda u: (u.dimension, u.name))


@mcp.tool()
def list_scales() -> list[ScaleInfo]:
    """
    List available scale prefixes for units.

    These prefixes can be combined with scalable units (see list_units).
    For example, prefix "k" (kilo) with unit "m" (meter) forms "km".

    Includes both SI decimal prefixes (kilo, mega, milli, micro, etc.)
    and binary prefixes (kibi, mebi, gibi) for information units.

    Note on bytes:
    - SI prefixes: kB = 1000 B, MB = 1,000,000 B (decimal)
    - Binary prefixes: KiB = 1024 B, MiB = 1,048,576 B (powers of 2)

    Returns:
        List of ScaleInfo objects with name, prefix symbol, and numeric factor.
    """
    result = []
    for scale in Scale:
        if scale == Scale.one:
            continue  # Skip the identity scale
        result.append(
            ScaleInfo(
                name=scale.name,
                prefix=scale.shorthand,
                factor=scale.descriptor.evaluated,
            )
        )
    return sorted(result, key=lambda s: -s.factor)


@mcp.tool()
def check_dimensions(
    unit_a: str,
    unit_b: str,
    ctx: Context | None = None,
) -> DimensionCheck | ConversionError:
    """
    Check if two units have compatible dimensions.

    Units with the same dimension can be converted between each other.
    Units with different dimensions cannot be added or directly compared.

    Args:
        unit_a: First unit string.
        unit_b: Second unit string.

    Returns:
        DimensionCheck indicating compatibility and the dimension of each unit.
        ConversionError if a unit string cannot be parsed.
    """
    session = _get_session(ctx)
    graph = session.get_graph()

    # Resolve units within session graph context
    with using_graph(graph):
        a, err = resolve_unit(unit_a, parameter="unit_a")
        if err:
            return err

        b, err = resolve_unit(unit_b, parameter="unit_b")
        if err:
            return err

    dim_a = a.dimension if isinstance(a, Unit) else a.dimension
    dim_b = b.dimension if isinstance(b, Unit) else b.dimension

    return DimensionCheck(
        compatible=(dim_a == dim_b),
        dimension_a=dim_a.name,
        dimension_b=dim_b.name,
    )


@mcp.tool()
def compute(
    initial_value: float,
    initial_unit: str,
    factors: list[dict],
    custom_units: list[dict] | None = None,
    custom_edges: list[dict] | None = None,
    expected_unit: str | None = None,
    ctx: Context | None = None,
) -> ComputeResult | ConversionError:
    """
    Perform multi-step factor-label calculations with dimensional tracking.

    IMPORTANT: Always use this tool for unit calculations. Do not calculate
    manually - the tool validates dimensional consistency and catches errors
    that manual calculation would miss.

    This tool processes a chain of conversion factors, validating dimensional
    consistency at each step. It's designed for dosage calculations, stoichiometry,
    and other multi-step unit conversions.

    Each factor is applied as: result = result × (value × numerator / denominator)

    For custom/domain-specific units, you can either:
    1. Use define_unit() and define_conversion() to register them for the session
    2. Pass them inline via custom_units and custom_edges parameters

    Args:
        initial_value: Starting numeric quantity.
        initial_unit: Starting unit string.
        factors: List of conversion factors. Each factor is a dict with:
            - value: Numeric coefficient (multiplied into numerator)
            - numerator: Numerator unit string (e.g., "kg", "mg")
            - denominator: Denominator unit string, optionally with numeric prefix
                          (e.g., "lb", "2.205 lb", "kg*day")
        custom_units: Optional list of inline unit definitions for this call only.
            Each dict should have: {"name": str, "dimension": str, "aliases": [str]}
        custom_edges: Optional list of inline conversion edges for this call only.
            Each dict should have: {"src": str, "dst": str, "factor": float}
        expected_unit: Optional target unit for validation. If provided, compute
            will verify the result has the correct dimension and return diagnostic
            feedback if not. This enables convergence loops where a model can
            iterate on the factor chain until dimensions match.

    Returns:
        ComputeResult with final quantity, unit, dimension, and step-by-step trace.
        ConversionError with step localization if any factor fails, or with
        dimension mismatch diagnostics if expected_unit doesn't match.

    Examples:
        Example 1: Weight-based dosing
        Problem: "15 mg/kg/day for a 70 kg patient, divided into 3 doses. mg per dose?"
        - Start with the rate: 15 mg/(kg*day)
        - Multiply by patient weight: 70 kg
        - Divide by doses per day: 3 doses

        compute(
            initial_value=15,
            initial_unit="mg/(kg*day)",
            factors=[
                {"value": 70, "numerator": "kg", "denominator": "ea"},
                {"value": 1, "numerator": "day", "denominator": "3 ea"},
            ],
            expected_unit="mg"
        )
        # Result: 350 mg per dose

        Example 2: IV drip rate
        Problem: "1000 mL over 8 hours with 15 gtt/mL tubing. Drip rate in gtt/min?"
        - Start with volume: 1000 mL
        - Divide by time: 8 hours
        - Convert hours to minutes
        - Multiply by drip factor: 15 gtt/mL

        compute(
            initial_value=1000,
            initial_unit="mL",
            factors=[
                {"value": 1, "numerator": "ea", "denominator": "8 h"},
                {"value": 60, "numerator": "min", "denominator": "h"},
                {"value": 15, "numerator": "gtt", "denominator": "mL"},
            ],
            expected_unit="gtt/min"
        )
        # Result: 31.25 gtt/min

        Example 3: Concentration-based infusion
        Problem: "Dopamine 5 mcg/kg/min for 80 kg patient. Drug is 400 mg in 250 mL. mL/h?"
        - Start with rate: 5 mcg/(kg*min)
        - Multiply by weight: 80 kg
        - Convert time: min to h
        - Convert mass: mcg to mg
        - Apply concentration: 250 mL per 400 mg

        compute(
            initial_value=5,
            initial_unit="mcg/(kg*min)",
            factors=[
                {"value": 80, "numerator": "kg", "denominator": "ea"},
                {"value": 60, "numerator": "min", "denominator": "h"},
                {"value": 1, "numerator": "mg", "denominator": "1000 mcg"},
                {"value": 250, "numerator": "mL", "denominator": "400 mg"},
            ],
            expected_unit="mL/h"
        )
        # Result: 15 mL/h

        Example 4: Using expected_unit for validation
        If your factor chain produces the wrong dimension, compute returns
        diagnostic hints:

        compute(
            initial_value=5,
            initial_unit="mcg/(kg*min)",
            factors=[
                {"value": 80, "numerator": "kg", "denominator": "min"},  # Wrong!
            ],
            expected_unit="mg/h"
        )
        # Returns error with hints:
        # "Missing 'time' in result. Try adding 'time' to a numerator..."
    """
    session = _get_session(ctx)
    session_graph = session.get_graph()

    # Build inline graph if custom definitions provided
    inline_graph, err = _build_inline_graph(custom_units, custom_edges, session_graph)
    if err:
        return err

    # Use inline graph or session graph
    graph = inline_graph or session_graph

    # All unit resolution within graph context
    with using_graph(graph):
        # Parse initial unit
        initial_parsed, err = resolve_unit(initial_unit, parameter="initial_unit")
        if err:
            return err

        # Track numeric value separately from unit accumulator
        # The flat accumulator keys by (unit.name, dimension, scale) so that
        # mg and kg remain separate entries (different scales, shouldn't cancel)
        running_value = float(initial_value)
        accum: dict[tuple, tuple] = {}
        _accumulate_factors(accum, initial_parsed, +1.0)

        steps: list[ComputeStep] = []

        # Record initial state
        running_unit = _build_product_from_accum(accum)
        initial_dim = initial_parsed.dimension.name
        initial_unit_str = _format_unit_output(running_unit)
        steps.append(ComputeStep(
            factor=f"{initial_value} {initial_unit}",
            dimension=initial_dim,
            unit=initial_unit_str,
        ))

        # Process each factor
        for i, factor in enumerate(factors):
            step_num = i + 1  # 1-indexed for user-facing errors

            # Validate factor structure
            if not isinstance(factor, dict):
                return ConversionError(
                    error=f"Factor at step {step_num} must be a dict",
                    error_type="invalid_input",
                    parameter=f"factors[{i}]",
                    step=i,
                    hints=["Each factor should be: {\"value\": float, \"numerator\": str, \"denominator\": str}"],
                )

            value = factor.get("value", 1.0)
            numerator = factor.get("numerator")
            denominator = factor.get("denominator")

            if numerator is None:
                return ConversionError(
                    error=f"Factor at step {step_num} missing 'numerator' field",
                    error_type="invalid_input",
                    parameter=f"factors[{i}].numerator",
                    step=i,
                    hints=["Each factor needs a numerator unit string"],
                )

            if denominator is None:
                return ConversionError(
                    error=f"Factor at step {step_num} missing 'denominator' field",
                    error_type="invalid_input",
                    parameter=f"factors[{i}].denominator",
                    step=i,
                    hints=["Each factor needs a denominator unit string"],
                )

            # Parse numerator unit
            num_unit, err = resolve_unit(numerator, parameter=f"factors[{i}].numerator", step=i)
            if err:
                return err

            # Parse denominator - may have numeric prefix (e.g., "2.205 lb")
            denom_value = 1.0
            denom_unit_str = denominator.strip()

            # Try to extract leading number from denominator
            match = re.match(r'^([0-9]*\.?[0-9]+)\s*(.+)$', denom_unit_str)
            if match:
                denom_value = float(match.group(1))
                denom_unit_str = match.group(2).strip()

            denom_unit, err = resolve_unit(denom_unit_str, parameter=f"factors[{i}].denominator", step=i)
            if err:
                return err

            # Apply factor: multiply by (value * num_unit) / (denom_value * denom_unit)
            try:
                # Compute numeric factor: value / denom_value
                numeric_factor = value / denom_value
                running_value *= numeric_factor

                # Accumulate numerator factors at +1, denominator factors at -1
                _accumulate_factors(accum, num_unit, +1.0)
                _accumulate_factors(accum, denom_unit, -1.0)

                # Build current unit product for step recording
                running_unit = _build_product_from_accum(accum)

            except Exception as e:
                return ConversionError(
                    error=f"Error applying factor at step {step_num}: {str(e)}",
                    error_type="computation_error",
                    parameter=f"factors[{i}]",
                    step=i,
                    hints=["Check that units are compatible for this operation"],
                )

            # Record step
            result_dim = running_unit.dimension.name if running_unit else "none"
            result_unit_str = _format_unit_output(running_unit)

            # Format factor description
            if denom_value != 1.0:
                factor_desc = f"× ({value} {numerator} / {denom_value} {denom_unit_str})"
            else:
                factor_desc = f"× ({value} {numerator} / {denom_unit_str})"

            steps.append(ComputeStep(
                factor=factor_desc,
                dimension=result_dim,
                unit=result_unit_str,
            ))

        # Build final result
        running_unit = _build_product_from_accum(accum)
        final_dim = running_unit.dimension.name if running_unit else "none"
        final_unit_str = _format_unit_output(running_unit)

        # Validate against expected_unit if provided
        if expected_unit is not None:
            expected_parsed, err = resolve_unit(expected_unit, parameter="expected_unit")
            if err:
                return err

            expected_dim = expected_parsed.dimension.name
            if final_dim != expected_dim:
                # Build diagnostic feedback
                hints = _diagnose_dimension_mismatch(
                    got_dim=running_unit.dimension if running_unit else None,
                    expected_dim=expected_parsed.dimension,
                )
                return ConversionError(
                    error=f"Dimension mismatch: got '{final_dim}', expected '{expected_dim}'",
                    error_type="dimension_mismatch",
                    parameter="factors",
                    got=final_dim,
                    expected=expected_dim,
                    hints=hints,
                )

        return ComputeResult(
            quantity=running_value,
            unit=final_unit_str,
            dimension=final_dim,
            steps=steps,
        )


def _format_unit_output(unit) -> str:
    """Format a unit or unit product for output display."""
    if unit is None:
        return "1"
    elif isinstance(unit, Unit):
        return unit.shorthand or unit.name
    elif isinstance(unit, UnitProduct):
        return unit.shorthand or "1"
    else:
        return str(unit)


def _diagnose_dimension_mismatch(
    got_dim: 'Dimension | None',
    expected_dim: 'Dimension',
) -> list[str]:
    """Generate diagnostic hints for dimension mismatch.

    Analyzes the difference between got and expected dimensions to provide
    actionable feedback for factor chain correction.

    Args:
        got_dim: The dimension that resulted from the factor chain.
        expected_dim: The dimension that was expected.

    Returns:
        List of diagnostic hints.
    """
    hints = []

    if got_dim is None:
        hints.append("Result is dimensionless. You may need additional factors.")
        hints.append(f"Expected dimension: {expected_dim.name}")
        return hints

    # Get base expansions for detailed comparison
    try:
        got_bases = {d.name: float(exp) for d, exp in got_dim.base_expansion().items()}
        expected_bases = {d.name: float(exp) for d, exp in expected_dim.base_expansion().items()}
    except Exception:
        # Fallback if base_expansion not available
        hints.append(
            f"Got '{got_dim.name}' but expected '{expected_dim.name}'. "
            f"Review factor chain for correctness."
        )
        return hints

    # Find differences in dimension exponents
    all_bases = set(got_bases.keys()) | set(expected_bases.keys())

    for base in sorted(all_bases):
        got_exp = got_bases.get(base, 0)
        expected_exp = expected_bases.get(base, 0)
        diff = got_exp - expected_exp

        if diff == 0:
            continue

        if diff > 0:
            # Extra dimension in result
            if diff == 1:
                hints.append(
                    f"Extra '{base}' in result. "
                    f"Try adding '{base}' to a denominator, or remove a factor with '{base}' in numerator."
                )
            else:
                hints.append(
                    f"Extra '{base}^{int(diff)}' in result. "
                    f"Check factors involving '{base}' — may need to invert or remove some."
                )
        else:
            # Missing dimension in result
            if diff == -1:
                hints.append(
                    f"Missing '{base}' in result. "
                    f"Try adding '{base}' to a numerator, or remove a factor with '{base}' in denominator."
                )
            else:
                hints.append(
                    f"Missing '{base}^{int(-diff)}' in result. "
                    f"Check factors involving '{base}' — may need to add or invert some."
                )

    if not hints:
        hints.append(
            f"Got '{got_dim.name}' but expected '{expected_dim.name}'. "
            f"Review factor chain for correctness."
        )

    return hints


def _accumulate_factors(
    accum: dict[tuple, tuple],
    product: Unit | UnitProduct,
    sign: float,
) -> None:
    """Add all UnitFactors from a parsed unit into the accumulator.

    The accumulator is keyed by (unit.name, dimension, scale) so that
    same-unit-different-scale entries (mg vs kg) don't cancel.

    Args:
        accum: The accumulator dict mapping key → (UnitFactor, exponent).
        product: A Unit or UnitProduct to accumulate.
        sign: +1.0 for numerator factors, -1.0 for denominator factors.
    """
    from ucon.core import UnitFactor

    if isinstance(product, Unit):
        product = UnitProduct.from_unit(product)

    for uf, exp in product.factors.items():
        key = (uf.unit.name, uf.unit.dimension, uf.scale)
        if key in accum:
            existing_uf, existing_exp = accum[key]
            accum[key] = (existing_uf, existing_exp + exp * sign)
        else:
            accum[key] = (uf, exp * sign)


def _build_product_from_accum(
    accum: dict[tuple, tuple],
) -> UnitProduct:
    """Build a UnitProduct from surviving non-zero accumulator entries."""
    surviving = {}
    for key, (uf, exp) in accum.items():
        if abs(exp) > 1e-12:
            surviving[uf] = exp
    if not surviving:
        return UnitProduct({})
    return UnitProduct(surviving)


@mcp.tool()
def list_dimensions() -> list[str]:
    """
    List available physical dimensions.

    Dimensions represent fundamental physical quantities (length, mass, time, etc.)
    and derived quantities (velocity, force, energy, etc.).

    Use these dimension names to filter list_units().

    Returns:
        List of dimension names.
    """
    return sorted([d.name for d in all_dimensions()])


# -----------------------------------------------------------------------------
# Session Management Tools
# -----------------------------------------------------------------------------


@mcp.tool()
def list_constants(
    category: str | None = None,
    ctx: Context | None = None,
) -> list[ConstantInfo] | ConstantError:
    """
    List available physical constants, optionally filtered by category.

    Categories:
    - "exact": SI defining constants (c, h, e, k_B, N_A, K_cd, ΔνCs)
    - "derived": Constants derived from exact values (ℏ, R, σ)
    - "measured": Constants with experimental uncertainty (G, α, m_e, etc.)
    - "session": User-defined constants for this session
    - "all" or None: Return all constants

    Args:
        category: Optional category filter.

    Returns:
        List of ConstantInfo objects describing available constants.
        ConstantError if the category is invalid.
    """
    valid_categories = {"exact", "derived", "measured", "session", "all", None}
    if category not in valid_categories:
        return ConstantError(
            error=f"Unknown category: '{category}'",
            error_type="invalid_input",
            parameter="category",
            hints=["Valid categories: exact, derived, measured, session, all"],
        )

    from ucon.constants import all_constants

    session = _get_session(ctx)
    result = []

    # Built-in constants
    if category != "session":
        for const in all_constants():
            if category and category != "all" and const.category != category:
                continue
            result.append(_constant_to_info(const))

    # Session constants
    if category in (None, "all", "session"):
        for const in session.get_constants().values():
            result.append(_constant_to_info(const, category="session"))

    return sorted(result, key=lambda c: (c.category, c.symbol))


@mcp.tool()
def define_constant(
    symbol: str,
    name: str,
    value: float,
    unit: str,
    uncertainty: float | None = None,
    source: str = "user-defined",
    ctx: Context | None = None,
) -> ConstantDefinitionResult | ConstantError:
    """
    Define a custom constant for the current session.

    The constant will be available for use in compute() and other tools
    until reset_session() is called.

    Args:
        symbol: Short symbol for the constant (e.g., "vₛ", "Eg").
        name: Full descriptive name.
        value: Numeric value in the given units.
        unit: Unit string (e.g., "m/s", "J", "kg*m/s^2").
        uncertainty: Standard uncertainty (None for exact constants).
        source: Data source reference.

    Returns:
        ConstantDefinitionResult on success.
        ConstantError if the symbol is already defined or unit is invalid.

    Example:
        define_constant(
            symbol="vₛ",
            name="speed of sound in dry air at 20°C",
            value=343,
            unit="m/s"
        )
    """
    import math
    from ucon.constants import Constant, get_constant_by_symbol

    # Check for duplicate symbol in built-in constants
    existing = get_constant_by_symbol(symbol)
    if existing is not None:
        return ConstantError(
            error=f"Symbol '{symbol}' is already defined as '{existing.name}'",
            error_type="duplicate_symbol",
            parameter="symbol",
            hints=["Use a different symbol or use the built-in constant"],
        )

    # Check for duplicate in session constants
    session = _get_session(ctx)
    session_constants = session.get_constants()
    if symbol in session_constants:
        return ConstantError(
            error=f"Symbol '{symbol}' is already defined in this session",
            error_type="duplicate_symbol",
            parameter="symbol",
            hints=["Use reset_session() to clear session constants"],
        )

    # Validate value
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return ConstantError(
            error=f"Invalid value: {value}",
            error_type="invalid_value",
            parameter="value",
            hints=["Value must be a finite number"],
        )

    # Parse unit
    parsed_unit, err = resolve_unit(unit, parameter="unit")
    if err:
        return ConstantError(
            error=f"Invalid unit: '{unit}'",
            error_type="invalid_unit",
            parameter="unit",
            hints=err.hints if hasattr(err, 'hints') else [],
        )

    # Validate uncertainty
    if uncertainty is not None:
        if not isinstance(uncertainty, (int, float)) or uncertainty < 0:
            return ConstantError(
                error=f"Invalid uncertainty: {uncertainty}",
                error_type="invalid_value",
                parameter="uncertainty",
                hints=["Uncertainty must be a non-negative number or None"],
            )

    # Create constant
    const = Constant(
        symbol=symbol,
        name=name,
        value=float(value),
        unit=parsed_unit,
        uncertainty=uncertainty,
        source=source,
        category="session",
    )

    # Register in session
    session_constants[symbol] = const

    return ConstantDefinitionResult(
        success=True,
        symbol=symbol,
        name=name,
        unit=unit,
        uncertainty=uncertainty,
        message=f"Constant '{symbol}' registered for session.",
    )


@mcp.tool()
def define_unit(
    name: str,
    dimension: str,
    aliases: list[str] | None = None,
    ctx: Context | None = None,
) -> UnitDefinitionResult | ConversionError:
    """
    Define a custom unit for the current session.

    The unit will be available for all subsequent convert() and compute() calls
    until reset_session() is called. Use this to extend ucon with domain-specific
    units (e.g., "slug" for aerospace, "mmHg" for medical).

    After defining a unit, use define_conversion() to add conversion edges
    to existing units.

    Args:
        name: Canonical name of the unit (e.g., "slug", "nautical_mile").
        dimension: Dimension name (e.g., "mass", "length"). Use list_dimensions()
            to see available dimensions.
        aliases: Optional list of shorthand symbols (e.g., ["slug"] or ["nmi", "NM"]).

    Returns:
        UnitDefinitionResult confirming the unit was registered.
        ConversionError if the dimension is invalid.

    Example:
        define_unit(name="slug", dimension="mass", aliases=["slug"])
    """
    aliases = aliases or []

    # Get session graph first for validation
    session = _get_session(ctx)
    graph = session.get_graph()

    # Validate dimension
    known_dimensions = [d.name for d in all_dimensions()]
    if dimension not in known_dimensions:
        return build_unknown_dimension_error(dimension)

    # Check for duplicate unit name (Issue 1: re-registration destroys edges)
    existing = graph.resolve_unit(name)
    if existing is not None:
        existing_unit, _ = existing
        return ConversionError(
            error=f"Unit '{name}' is already defined (dimension: {existing_unit.dimension.name})",
            error_type="duplicate_unit",
            parameter="name",
            hints=[
                "Use a different name for the new unit",
                "Use reset_session() to clear all custom definitions",
            ],
        )

    # Check for alias collisions (Issue 2: alias collisions silently accepted)
    for alias in aliases:
        existing = graph.resolve_unit(alias)
        if existing is not None:
            existing_unit, _ = existing
            return ConversionError(
                error=f"Alias '{alias}' is already claimed by unit '{existing_unit.name}' (dimension: {existing_unit.dimension.name})",
                error_type="alias_collision",
                parameter="aliases",
                hints=[
                    f"Remove '{alias}' from aliases or use a different alias",
                    f"The existing unit '{existing_unit.name}' already uses this alias",
                ],
            )

    # Create unit definition and materialize
    try:
        unit_def = UnitDef(
            name=name,
            dimension=dimension,
            aliases=tuple(aliases),
        )
        unit = unit_def.materialize()
    except PackageLoadError as e:
        return ConversionError(
            error=str(e),
            error_type="invalid_input",
            parameter="dimension",
            hints=["Use list_dimensions() to see available dimensions"],
        )

    # Register in session graph
    graph.register_unit(unit)

    return UnitDefinitionResult(
        success=True,
        name=name,
        dimension=dimension,
        aliases=aliases,
        message=f"Unit '{name}' registered for session. Use define_conversion() to add conversion edges.",
    )


@mcp.tool()
def define_conversion(
    src: str,
    dst: str,
    factor: float,
    ctx: Context | None = None,
) -> ConversionDefinitionResult | ConversionError:
    """
    Define a conversion edge between two units for the current session.

    The conversion factor specifies: dst_value = src_value × factor

    Both src and dst must be resolvable units - either standard ucon units
    or custom units previously defined via define_unit().

    Args:
        src: Source unit name or alias (e.g., "slug").
        dst: Destination unit name or alias (e.g., "kg").
        factor: Conversion multiplier (e.g., 14.5939 for slug → kg).

    Returns:
        ConversionDefinitionResult confirming the edge was added.
        ConversionError if either unit cannot be resolved.

    Example:
        define_conversion(src="slug", dst="kg", factor=14.5939)
    """
    session = _get_session(ctx)
    graph = session.get_graph()

    # Create edge definition and materialize
    try:
        edge_def = EdgeDef(src=src, dst=dst, factor=factor)
        edge_def.materialize(graph)
    except PackageLoadError as e:
        return ConversionError(
            error=str(e),
            error_type="unknown_unit",
            parameter="src" if src in str(e) else "dst",
            hints=[
                "Make sure both units are defined (use define_unit() for custom units)",
                "Use list_units() to see available standard units",
            ],
        )

    return ConversionDefinitionResult(
        success=True,
        src=src,
        dst=dst,
        factor=factor,
        message=f"Conversion edge '{src}' → '{dst}' (factor={factor}) added to session.",
    )


@mcp.tool()
def reset_session(ctx: Context | None = None) -> SessionResult:
    """
    Reset the session, clearing all custom units, conversions, and constants.

    After reset, the session starts fresh with only the standard ucon units
    and built-in physical constants. Any units defined via define_unit(),
    edges from define_conversion(), and constants from define_constant()
    will be removed.

    Returns:
        SessionResult confirming the reset.
    """
    session = _get_session(ctx)
    session.reset()
    return SessionResult(
        success=True,
        message="Session reset. All custom units, conversions, and constants cleared.",
    )


# -----------------------------------------------------------------------------
# Decompose Tool
# -----------------------------------------------------------------------------


def _find_conversion_path(
    graph: ConversionGraph,
    src: Unit,
    dst: Unit,
) -> list[tuple[Unit, Unit, float]] | None:
    """Find the BFS path between two units and return edge info.

    Returns a list of (from_unit, to_unit, factor) tuples representing the path.
    Returns None if no path exists.
    """
    from collections import deque

    if src == dst:
        return []  # Identity conversion

    dim = src.dimension
    if dim != dst.dimension:
        return None

    if dim not in graph._unit_edges:
        return None

    # BFS tracking both the composed map and the path
    # visited: unit → (predecessor_unit, edge_factor) or None for start
    visited: dict[Unit, tuple[Unit | None, float]] = {src: (None, 1.0)}
    queue = deque([src])

    while queue:
        current = queue.popleft()

        if current not in graph._unit_edges[dim]:
            continue

        for neighbor, edge_map in graph._unit_edges[dim][current].items():
            if neighbor in visited:
                continue

            # Extract factor from the map
            # LinearMap has .a attribute, AffineMap has .a and .b
            if hasattr(edge_map, 'a'):
                factor = float(edge_map.a)
            else:
                factor = 1.0  # Identity or unknown map type

            visited[neighbor] = (current, factor)

            if neighbor == dst:
                # Reconstruct path
                path = []
                node = dst
                while visited[node][0] is not None:
                    predecessor, edge_factor = visited[node]
                    path.append((predecessor, node, edge_factor))
                    node = predecessor
                path.reverse()
                return path

            queue.append(neighbor)

    return None  # No path found


def _format_unit_for_chain(unit: Unit | UnitProduct) -> str:
    """Format a unit for use in a factor chain."""
    if isinstance(unit, Unit):
        return unit.shorthand or unit.name
    elif isinstance(unit, UnitProduct):
        return unit.shorthand or str(unit)
    return str(unit)


def _get_dimension_exponents(dim: Dimension) -> dict[str, float]:
    """Get base dimension exponents as a dict."""
    try:
        return {d.name: float(exp) for d, exp in dim.base_expansion().items()}
    except Exception:
        return {dim.name: 1.0}


def _compute_dimension_gap(
    initial_dim: Dimension,
    target_dim: Dimension,
) -> dict[str, float]:
    """Compute the dimensional gap: what exponents are needed to go from initial to target.

    Returns a dict of {base_dimension: exponent_needed}.
    Positive exponent means we need to multiply by that dimension.
    Negative exponent means we need to divide by that dimension.
    """
    initial_exp = _get_dimension_exponents(initial_dim)
    target_exp = _get_dimension_exponents(target_dim)

    all_bases = set(initial_exp.keys()) | set(target_exp.keys())
    gap = {}

    for base in all_bases:
        init = initial_exp.get(base, 0.0)
        targ = target_exp.get(base, 0.0)
        diff = targ - init
        if abs(diff) > 1e-12:
            gap[base] = diff

    return gap


def _find_unit_for_dimension(
    graph: ConversionGraph,
    dim_name: str,
    preferred_unit_str: str | None = None,
) -> Unit | None:
    """Find a unit for a given dimension name.

    If preferred_unit_str is given, try to resolve it first.
    Otherwise, find any unit in that dimension.
    """
    from ucon.dimension import all_dimensions

    # If preferred unit given, try to resolve it
    if preferred_unit_str:
        result = graph.resolve_unit(preferred_unit_str)
        if result:
            unit, _ = result
            return unit

    # Find the dimension
    target_dim = None
    for d in all_dimensions():
        if d.name == dim_name:
            target_dim = d
            break

    if target_dim is None:
        return None

    # Find any unit in that dimension from the graph
    if target_dim in graph._unit_edges:
        units = list(graph._unit_edges[target_dim].keys())
        if units:
            return units[0]

    return None


def _build_scale_conversion_factor(
    graph: ConversionGraph,
    src_unit: Unit | UnitProduct,
    dst_unit: Unit | UnitProduct,
) -> dict | None:
    """Build a conversion factor between units of the same dimension but different scales.

    Returns a factor dict for compute(), or None if no conversion needed/possible.
    """
    # Get the conversion factor
    try:
        with using_graph(graph):
            conv_map = graph.convert(src=src_unit, dst=dst_unit)

        if hasattr(conv_map, 'a'):
            factor = float(conv_map.a)
        else:
            factor = 1.0

        if abs(factor - 1.0) < 1e-12:
            return None  # Identity, no factor needed

        src_str = _format_unit_for_chain(src_unit)
        dst_str = _format_unit_for_chain(dst_unit)

        return {
            "value": factor,
            "numerator": dst_str,
            "denominator": src_str,
        }
    except Exception:
        return None


@mcp.tool()
def decompose(
    query: str | None = None,
    initial_unit: str | None = None,
    target_unit: str | None = None,
    known_quantities: list[dict] | None = None,
    ctx: Context | None = None,
) -> DecomposeResult | ConversionError:
    """
    Build a factor chain for compute() by analyzing dimensional requirements.

    This tool bridges the gap between natural language problems and compute().
    It handles dimensional gap analysis, places known quantities correctly,
    and constructs the complete factor chain.

    TWO MODES OF OPERATION:

    Mode 1 - Query string (simple conversions):
        decompose(query="500 mL to L")
        For direct unit-to-unit conversions where dimensions already match.

    Mode 2 - Structured input (complex problems):
        decompose(
            initial_unit="mcg/(kg*min)",
            target_unit="mg/h",
            known_quantities=[{"value": 70, "unit": "kg"}]
        )
        For multi-step problems where known quantities bridge dimensional gaps.

    Args:
        query: Simple conversion query like "500 mL to L" or "50 psi to kPa".
            Use this for direct conversions where source and target have the
            same dimension.

        initial_unit: Starting unit string (e.g., "mcg/(kg*min)").
            Use with target_unit for complex problems.

        target_unit: Target unit string (e.g., "mg/h").
            The tool will analyze what's needed to bridge the dimensional gap.

        known_quantities: List of quantities that should be incorporated into
            the factor chain. Each dict should have:
            - value: Numeric value (e.g., 70)
            - unit: Unit string (e.g., "kg")
            The tool will determine whether each quantity goes in a numerator
            or denominator based on dimensional analysis.

    Returns:
        DecomposeResult with initial_value, initial_unit, target_unit, factors.
        The factors list can be passed directly to compute().
        ConversionError if the dimensional gap cannot be bridged.

    Examples:
        Example 1: Simple conversion (query mode)
        decompose(query="500 mL to L")
        # Returns factors for mL→L conversion

        Example 2: Weight-based dosing
        Problem: "5 mcg/kg/min for a 70 kg patient. Rate in mg/h?"
        decompose(
            initial_unit="mcg/(kg*min)",
            target_unit="mg/h",
            known_quantities=[{"value": 70, "unit": "kg"}]
        )
        # Returns:
        # {
        #   "initial_value": 1,
        #   "initial_unit": "mcg/(kg*min)",
        #   "target_unit": "mg/h",
        #   "factors": [
        #     {"value": 70, "numerator": "kg", "denominator": "ea"},
        #     {"value": 60, "numerator": "min", "denominator": "h"},
        #     {"value": 1, "numerator": "mg", "denominator": "1000 mcg"}
        #   ]
        # }
        # Then: compute(initial_value=5, initial_unit="mcg/(kg*min)", factors=...)

        Example 3: IV drip rate
        Problem: "1000 mL over 8 hours, 15 gtt/mL tubing. Rate in gtt/min?"
        decompose(
            initial_unit="mL",
            target_unit="gtt/min",
            known_quantities=[
                {"value": 8, "unit": "h"},
                {"value": 15, "unit": "gtt/mL"}
            ]
        )

        Example 4: Concentration problem
        Problem: "Drug is 400 mg in 250 mL. Dose in mg, volume needed?"
        decompose(
            initial_unit="mg",
            target_unit="mL",
            known_quantities=[
                {"value": 250, "unit": "mL"},
                {"value": 400, "unit": "mg"}
            ]
        )
        # Places 250 mL in numerator, 400 mg in denominator (to cancel mg → mL)
    """
    from ucon.parsing import parse

    session = _get_session(ctx)
    graph = session.get_graph()

    # Determine mode based on parameters
    if query is not None:
        # Mode 1: Simple query string parsing
        return _decompose_query_mode(query, graph)
    elif initial_unit is not None and target_unit is not None:
        # Mode 2: Structured dimensional analysis
        return _decompose_structured_mode(
            initial_unit, target_unit, known_quantities or [], graph
        )
    else:
        return ConversionError(
            error="Must provide either 'query' or both 'initial_unit' and 'target_unit'",
            error_type="invalid_input",
            parameter="query",
            hints=[
                "For simple conversions: decompose(query='500 mL to L')",
                "For complex problems: decompose(initial_unit='mcg/(kg*min)', target_unit='mg/h', known_quantities=[...])",
            ],
        )


def _decompose_query_mode(
    query: str,
    graph: ConversionGraph,
) -> DecomposeResult | ConversionError:
    """Handle simple 'X to Y' query parsing."""
    from ucon.parsing import parse

    # Split on conversion separators
    query_stripped = query.strip()
    parts = None

    for sep_pattern in [r'\s+to\s+', r'\s+→\s+', r'\s+->\s+', r'\s+in\s+']:
        split_result = re.split(sep_pattern, query_stripped, maxsplit=1)
        if len(split_result) == 2:
            parts = split_result
            break

    if parts is None or len(parts) != 2:
        return ConversionError(
            error=f"Cannot parse conversion query: '{query}'",
            error_type="parse_error",
            parameter="query",
            hints=[
                "Expected format: '<value> <unit> to <unit>' or '<unit> to <unit>'",
                "Examples: '3 TB to GiB', '60 mph to km/h', 'm/s to ft/s'",
            ],
        )

    source_str, target_str = parts[0].strip(), parts[1].strip()

    with using_graph(graph):
        initial_value = None
        initial_unit_str = source_str

        try:
            source_parsed = parse(source_str)
            initial_value = source_parsed.quantity
            if source_parsed.unit is not None:
                initial_unit_str = _format_unit_for_chain(source_parsed.unit)
                source_unit = source_parsed.unit
            else:
                return ConversionError(
                    error=f"Source '{source_str}' has no unit",
                    error_type="parse_error",
                    parameter="query",
                    hints=["Source must include a unit, e.g., '3 TB' not just '3'"],
                )
        except Exception:
            src_result, err = resolve_unit(source_str, parameter="query")
            if err:
                return err
            source_unit = src_result
            initial_unit_str = source_str
            initial_value = None

        dst_result, err = resolve_unit(target_str, parameter="query")
        if err:
            return err
        target_unit = dst_result

    src_dim = source_unit.dimension
    dst_dim = target_unit.dimension

    if src_dim != dst_dim:
        return build_dimension_mismatch_error(
            from_unit_str=initial_unit_str,
            to_unit_str=target_str,
            src_unit=source_unit,
            dst_unit=target_unit,
        )

    # Build factor chain
    factors = []

    if isinstance(source_unit, UnitProduct) or isinstance(target_unit, UnitProduct):
        try:
            with using_graph(graph):
                conv_map = graph.convert(src=source_unit, dst=target_unit)

            if hasattr(conv_map, 'a'):
                total_factor = float(conv_map.a)
            else:
                total_factor = 1.0

            if abs(total_factor - 1.0) > 1e-12:
                factors.append({
                    "value": total_factor,
                    "numerator": _format_unit_for_chain(target_unit),
                    "denominator": _format_unit_for_chain(source_unit),
                })

        except (DimensionMismatch, ConversionNotFound) as e:
            return build_no_path_error(
                from_unit_str=initial_unit_str,
                to_unit_str=target_str,
                src_unit=source_unit,
                dst_unit=target_unit,
                exception=e,
            )
    else:
        path = _find_conversion_path(graph, source_unit, target_unit)

        if path is None:
            try:
                with using_graph(graph):
                    graph.convert(src=source_unit, dst=target_unit)
            except ConversionNotFound as e:
                return build_no_path_error(
                    from_unit_str=initial_unit_str,
                    to_unit_str=target_str,
                    src_unit=source_unit,
                    dst_unit=target_unit,
                    exception=e,
                )
            except DimensionMismatch:
                return build_dimension_mismatch_error(
                    from_unit_str=initial_unit_str,
                    to_unit_str=target_str,
                    src_unit=source_unit,
                    dst_unit=target_unit,
                )

        for from_unit, to_unit, factor in path:
            factors.append({
                "value": factor,
                "numerator": _format_unit_for_chain(to_unit),
                "denominator": _format_unit_for_chain(from_unit),
            })

    return DecomposeResult(
        initial_value=initial_value,
        initial_unit=initial_unit_str,
        target_unit=target_str,
        factors=factors,
    )


def _decompose_structured_mode(
    initial_unit_str: str,
    target_unit_str: str,
    known_quantities: list[dict],
    graph: ConversionGraph,
) -> DecomposeResult | ConversionError:
    """Handle structured dimensional analysis mode.

    This mode:
    1. Parses initial and target units
    2. Computes the dimensional gap
    3. Places known quantities to bridge the gap
    4. Adds conversion factors for remaining unit mismatches
    """
    with using_graph(graph):
        # Parse initial unit
        initial_parsed, err = resolve_unit(initial_unit_str, parameter="initial_unit")
        if err:
            return err

        # Parse target unit
        target_parsed, err = resolve_unit(target_unit_str, parameter="target_unit")
        if err:
            return err

    initial_dim = initial_parsed.dimension
    target_dim = target_parsed.dimension

    # Compute dimensional gap
    gap = _compute_dimension_gap(initial_dim, target_dim)

    factors = []
    remaining_gap = dict(gap)

    # Parse and place known quantities
    for i, qty in enumerate(known_quantities):
        if "value" not in qty:
            return ConversionError(
                error=f"known_quantities[{i}] missing 'value' field",
                error_type="invalid_input",
                parameter=f"known_quantities[{i}]",
                hints=["Each quantity needs: {\"value\": 70, \"unit\": \"kg\"}"],
            )

        value = qty["value"]
        unit_str = qty.get("unit", "ea")

        with using_graph(graph):
            qty_unit, err = resolve_unit(unit_str, parameter=f"known_quantities[{i}].unit")
            if err:
                return err

        qty_dim = qty_unit.dimension
        qty_exp = _get_dimension_exponents(qty_dim)

        # Determine placement: does this quantity help close the gap?
        # Check if adding it (numerator) or dividing by it (denominator) helps
        placement = _determine_quantity_placement(qty_exp, remaining_gap)

        if placement == "numerator":
            # Quantity goes in numerator: multiply by it
            factors.append({
                "value": value,
                "numerator": unit_str,
                "denominator": "ea",
            })
            # Update remaining gap (adding this dimension)
            for base, exp in qty_exp.items():
                remaining_gap[base] = remaining_gap.get(base, 0) - exp
                if abs(remaining_gap[base]) < 1e-12:
                    del remaining_gap[base]

        elif placement == "denominator":
            # Quantity goes in denominator: divide by it
            factors.append({
                "value": 1,
                "numerator": "ea",
                "denominator": f"{value} {unit_str}",
            })
            # Update remaining gap (subtracting this dimension)
            for base, exp in qty_exp.items():
                remaining_gap[base] = remaining_gap.get(base, 0) + exp
                if abs(remaining_gap[base]) < 1e-12:
                    del remaining_gap[base]

        else:
            # Quantity doesn't help with dimensional gap - still include it
            # but warn that it may not be correctly placed
            factors.append({
                "value": value,
                "numerator": unit_str,
                "denominator": "ea",
            })

    # After placing known quantities, check if we need unit conversions
    # for same-dimension different-unit cases
    # This handles cases like mcg→mg, min→h within the factor chain

    # Build the current accumulated unit product
    accum: dict[tuple, tuple] = {}
    _accumulate_factors(accum, initial_parsed, +1.0)

    for factor in factors:
        num_str = factor["numerator"]
        denom_str = factor["denominator"]

        # Parse numerator
        if num_str != "ea":
            with using_graph(graph):
                num_unit, _ = resolve_unit(num_str, parameter="numerator")
                if num_unit:
                    _accumulate_factors(accum, num_unit, +1.0)

        # Parse denominator (may have value prefix)
        if denom_str != "ea":
            denom_parts = denom_str.strip().split(None, 1)
            if len(denom_parts) == 2 and denom_parts[0].replace('.', '').isdigit():
                denom_unit_str = denom_parts[1]
            else:
                denom_unit_str = denom_str

            with using_graph(graph):
                denom_unit, _ = resolve_unit(denom_unit_str, parameter="denominator")
                if denom_unit:
                    _accumulate_factors(accum, denom_unit, -1.0)

    current_product = _build_product_from_accum(accum)
    current_dim = current_product.dimension if current_product else Dimension.dimensionless

    # Add conversion factors to reach target dimension's units
    if current_dim == target_dim:
        # Same dimension - may need scale conversions
        conv_factor = _build_scale_conversion_factor(graph, current_product, target_parsed)
        if conv_factor:
            factors.append(conv_factor)
    elif remaining_gap:
        # Still have dimensional gap - provide diagnostic
        hints = []
        for base, exp in remaining_gap.items():
            if exp > 0:
                hints.append(f"Need to add '{base}' (exponent {exp}) - provide a quantity with this dimension")
            else:
                hints.append(f"Need to cancel '{base}' (exponent {-exp}) - provide a quantity with this dimension")

        return ConversionError(
            error=f"Cannot bridge dimensional gap from '{initial_unit_str}' to '{target_unit_str}'",
            error_type="dimension_mismatch",
            parameter="known_quantities",
            hints=hints + [
                "Add more known_quantities to bridge the gap",
                f"Current gap: {remaining_gap}",
            ],
        )

    return DecomposeResult(
        initial_value=None,  # Value comes from the problem, not decompose
        initial_unit=initial_unit_str,
        target_unit=target_unit_str,
        factors=factors,
    )


def _determine_quantity_placement(
    qty_exp: dict[str, float],
    gap: dict[str, float],
) -> str:
    """Determine whether a quantity should go in numerator or denominator.

    Returns "numerator", "denominator", or "unknown".
    """
    if not qty_exp:
        return "unknown"

    # Check if adding this quantity (numerator) helps close the gap
    numerator_score = 0
    denominator_score = 0

    for base, exp in qty_exp.items():
        gap_exp = gap.get(base, 0)

        if gap_exp > 0 and exp > 0:
            # Gap needs positive, quantity provides positive → numerator
            numerator_score += min(abs(gap_exp), abs(exp))
        elif gap_exp < 0 and exp > 0:
            # Gap needs negative, quantity provides positive → denominator
            denominator_score += min(abs(gap_exp), abs(exp))
        elif gap_exp > 0 and exp < 0:
            # Gap needs positive, quantity provides negative → denominator
            denominator_score += min(abs(gap_exp), abs(exp))
        elif gap_exp < 0 and exp < 0:
            # Gap needs negative, quantity provides negative → numerator
            numerator_score += min(abs(gap_exp), abs(exp))

    if numerator_score > denominator_score:
        return "numerator"
    elif denominator_score > numerator_score:
        return "denominator"
    else:
        return "unknown"


# -----------------------------------------------------------------------------
# Solve Tool (NLP extraction + decompose + compute in one call)
# -----------------------------------------------------------------------------


class SolveResult(BaseModel):
    """Result of solving a unit conversion problem from natural language."""

    quantity: float
    unit: str
    dimension: str
    extracted: dict  # What was extracted from the text
    factors: list[dict]  # The factor chain used


@mcp.tool()
def solve(
    problem: str,
    target_unit: str,
    ctx: Context | None = None,
) -> SolveResult | ConversionError:
    """
    Solve a unit conversion problem from natural language in one step.

    This tool extracts quantities from the problem text using NLP,
    builds the factor chain, and computes the result. No need to
    manually construct factors.

    Args:
        problem: Natural language problem statement.
            Examples:
            - "5 mcg/kg/min for a 70 kg patient"
            - "1000 mL over 8 hours using 15 gtt/mL tubing"
            - "25 mg/kg/day divided into 3 doses, child weighs 15 kg"
        target_unit: The unit for the answer (e.g., "mg/h", "gtt/min", "mg").

    Returns:
        SolveResult with the computed quantity, unit, and extraction details.
        ConversionError if extraction fails or units are incompatible.

    Examples:
        solve(
            problem="5 mcg/kg/min for a 70 kg patient",
            target_unit="mg/h"
        )
        # Returns: quantity=21.0, unit="mg/h"

        solve(
            problem="1000 mL over 8 hours using 15 gtt/mL tubing",
            target_unit="gtt/min"
        )
        # Returns: quantity=31.25, unit="gtt/min"

        solve(
            problem="Convert 500 mL to liters",
            target_unit="L"
        )
        # Returns: quantity=0.5, unit="L"
    """
    from ucon.tools.mcp.extraction import extract_problem
    from ucon.tools.mcp.ner import normalize_unit_string

    session = _get_session(ctx)
    graph = session.get_graph()

    # Normalize target_unit from natural language to canonical form
    # e.g., "mg per dose" → "mg/ea", "milligrams per hour" → "mg/h"
    target_unit = normalize_unit_string(target_unit)

    # Step 1: Extract quantities from problem text
    extraction = extract_problem(problem, target_unit)

    if extraction.initial_unit is None:
        return ConversionError(
            error="Could not extract any quantities from the problem",
            error_type="extraction_error",
            parameter="problem",
            hints=[
                "Make sure the problem contains numeric values with units",
                "Example: '5 mcg/kg/min for a 70 kg patient'",
            ],
        )

    # Step 2: Call decompose with extracted values
    decompose_result = _decompose_structured_mode(
        initial_unit_str=extraction.initial_unit,
        target_unit_str=target_unit,
        known_quantities=extraction.known_quantities,
        graph=graph,
    )

    if isinstance(decompose_result, ConversionError):
        return decompose_result

    # Step 3: Call compute with the factors
    initial_value = extraction.initial_value or 1.0

    compute_result = compute(
        initial_value=initial_value,
        initial_unit=decompose_result.initial_unit,
        factors=decompose_result.factors,
        expected_unit=target_unit,
        ctx=ctx,
    )

    if isinstance(compute_result, ConversionError):
        return compute_result

    return SolveResult(
        quantity=compute_result.quantity,
        unit=compute_result.unit,
        dimension=compute_result.dimension,
        extracted={
            "initial_value": extraction.initial_value,
            "initial_unit": extraction.initial_unit,
            "known_quantities": extraction.known_quantities,
        },
        factors=decompose_result.factors,
    )


# -----------------------------------------------------------------------------
# Formula Discovery Tools
# -----------------------------------------------------------------------------


@mcp.tool()
def list_formulas() -> list[FormulaInfoResponse]:
    """
    List all registered domain formulas with their dimensional constraints.

    Returns formulas that have been registered via @register_formula decorator.
    Each formula includes parameter names and their expected dimensions, enabling
    pre-call validation of inputs.

    Use this to discover available calculations and understand their dimensional
    requirements before calling.

    Returns:
        List of formula metadata including name, description, and parameter dimensions.

    Example response:
        [
            {
                "name": "fib4",
                "description": "FIB-4 liver fibrosis score",
                "parameters": {
                    "age": "time",
                    "ast": "frequency",
                    "alt": "frequency",
                    "platelets": null
                }
            }
        ]
    """
    formulas = _list_formulas()
    return [
        FormulaInfoResponse(
            name=f.name,
            description=f.description,
            parameters=f.parameters,
        )
        for f in formulas
    ]


def _number_dimension(num: Number) -> Dimension:
    """Extract dimension from a Number."""
    if num.unit is None:
        return Dimension.dimensionless
    if isinstance(num.unit, Unit):
        return num.unit.dimension
    if isinstance(num.unit, UnitProduct):
        return num.unit.dimension
    return Dimension.dimensionless


@mcp.tool()
def call_formula(
    name: str,
    parameters: dict[str, dict],
) -> FormulaResult | FormulaError:
    """
    Call a registered formula with the given parameters.

    Use list_formulas() first to discover available formulas and their
    expected parameter dimensions.

    Args:
        name: The formula name (from list_formulas).
        parameters: Dict mapping parameter names to values. Each value should be:
            - {"value": 5.0, "unit": "kg"} for dimensioned quantities
            - {"value": 5.0} for dimensionless quantities

    Returns:
        FormulaResult on success, FormulaError on failure.

    Example:
        call_formula(
            name="bmi",
            parameters={
                "mass": {"value": 70, "unit": "kg"},
                "height": {"value": 1.75, "unit": "m"}
            }
        )
        # Returns: {"formula": "bmi", "quantity": 22.86, "unit": "kg/m²", ...}
    """
    # Look up the formula
    info = get_formula(name)
    if info is None:
        available = [f.name for f in _list_formulas()]
        hints = []
        if available:
            hints.append(f"Available formulas: {', '.join(available)}")
        else:
            hints.append("No formulas registered. Formulas must be registered via @register_formula.")
        return FormulaError(
            error=f"Unknown formula: '{name}'",
            error_type="unknown_formula",
            formula=name,
            hints=hints,
        )

    # Build the arguments
    kwargs = {}
    for param_name, expected_dim in info.parameters.items():
        if param_name not in parameters:
            return FormulaError(
                error=f"Missing required parameter: '{param_name}'",
                error_type="missing_parameter",
                formula=name,
                parameter=param_name,
                expected=expected_dim,
                hints=[f"Parameter '{param_name}' expects dimension: {expected_dim or 'any'}"],
            )

        param_value = parameters[param_name]

        # Parse the parameter value
        if not isinstance(param_value, dict):
            return FormulaError(
                error=f"Invalid parameter format for '{param_name}': expected dict with 'value' key",
                error_type="invalid_parameter",
                formula=name,
                parameter=param_name,
                hints=["Parameters should be: {\"value\": 5.0, \"unit\": \"kg\"} or {\"value\": 5.0}"],
            )

        if "value" not in param_value:
            return FormulaError(
                error=f"Parameter '{param_name}' missing 'value' key",
                error_type="invalid_parameter",
                formula=name,
                parameter=param_name,
                hints=["Parameters should be: {\"value\": 5.0, \"unit\": \"kg\"} or {\"value\": 5.0}"],
            )

        value = param_value["value"]
        unit_str = param_value.get("unit")

        if unit_str:
            # Parse the unit
            try:
                unit = get_unit_by_name(unit_str)
            except Exception as e:
                return FormulaError(
                    error=f"Unknown unit '{unit_str}' for parameter '{param_name}'",
                    error_type="invalid_parameter",
                    formula=name,
                    parameter=param_name,
                    got=unit_str,
                    hints=[str(e)],
                )
            kwargs[param_name] = Number(value, unit)
        else:
            # Dimensionless
            kwargs[param_name] = Number(value)

    # Call the formula
    try:
        result = info.fn(**kwargs)
    except ValueError as e:
        # Dimension mismatch from @enforce_dimensions
        error_msg = str(e)
        # Parse out parameter name if possible
        param = None
        expected = None
        got = None
        if ": expected dimension" in error_msg:
            parts = error_msg.split(":")
            if len(parts) >= 2:
                param = parts[0].strip()
                # Try to extract expected/got
                match = re.search(r"expected dimension '(\w+)', got '(\w+)'", error_msg)
                if match:
                    expected = match.group(1)
                    got = match.group(2)
        return FormulaError(
            error=error_msg,
            error_type="dimension_mismatch",
            formula=name,
            parameter=param,
            expected=expected,
            got=got,
            hints=[f"Check that '{param}' has the correct dimension" if param else "Check parameter dimensions"],
        )
    except TypeError as e:
        return FormulaError(
            error=str(e),
            error_type="invalid_parameter",
            formula=name,
            hints=["Check parameter types match formula signature"],
        )
    except Exception as e:
        return FormulaError(
            error=f"Formula execution failed: {e}",
            error_type="execution_error",
            formula=name,
            hints=[],
        )

    # Format the result
    if isinstance(result, Number):
        unit_str = None
        if result.unit is not None:
            unit_str = result.unit.shorthand
        dim = _number_dimension(result)
        return FormulaResult(
            formula=name,
            quantity=result.quantity,
            unit=unit_str,
            dimension=dim.name,
            uncertainty=result.uncertainty,
        )
    else:
        # Non-Number result (shouldn't happen for well-typed formulas)
        return FormulaResult(
            formula=name,
            quantity=float(result),
            unit=None,
            dimension="unknown",
        )


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------


def main():
    """Run the ucon MCP server.

    Usage:
        ucon-mcp              # stdio mode (default)
        ucon-mcp --sse        # SSE mode on port 8000
        ucon-mcp --sse --port 3000  # SSE mode on custom port
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="ucon MCP server for unit conversion and dimensional analysis"
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Run in SSE (Server-Sent Events) mode instead of stdio",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE mode (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for SSE mode (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    if args.sse:
        # Configure SSE settings
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(f"Starting ucon MCP server in SSE mode on http://{args.host}:{args.port}/sse")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

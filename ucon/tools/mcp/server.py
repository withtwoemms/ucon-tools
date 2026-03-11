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
from ucon.tools.mcp.koq import (
    QuantityKindInfo,
    QuantityKindDefinitionResult,
    ComputationDeclaration,
    ValidationResult,
    ExtendedBasisResult,
    ExtendedBasisInfo,
    KOQError,
    get_quantity_kind,
    get_kinds_by_dimension,
    check_semantic_conflicts,
)
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
    ctx: Context | None = None,
) -> ComputeResult | ConversionError:
    """
    Perform multi-step factor-label calculations with dimensional tracking.

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

    Returns:
        ComputeResult with final quantity, unit, dimension, and step-by-step trace.
        ConversionError with step localization if any factor fails.

    Example:
        # Convert 154 lb to mg/dose for a drug with 15 mg/kg/day dosing, 3 doses/day
        compute(
            initial_value=154,
            initial_unit="lb",
            factors=[
                {"value": 1, "numerator": "kg", "denominator": "2.205 lb"},
                {"value": 15, "numerator": "mg", "denominator": "kg*day"},
                {"value": 1, "numerator": "day", "denominator": "3 dose"},
            ]
        )
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
# KOQ (Kind-of-Quantity) Tools
# -----------------------------------------------------------------------------


def _get_dimension_vector(unit) -> str:
    """Get the dimensional vector signature for a unit.

    Returns a string like "M·L²·T⁻²·N⁻¹" representing the dimensional
    signature of the unit in canonical KOQ order.
    """
    if unit is None:
        return "1"

    dim = unit.dimension if hasattr(unit, 'dimension') else Dimension.none
    if dim == Dimension.none:
        return "1"

    vec = dim.vector
    components = []

    # KOQ canonical order: (symbol, basis_component_name)
    koq_order = [
        ("M", "mass"),
        ("L", "length"),
        ("T", "time"),
        ("I", "current"),
        ("Θ", "temperature"),
        ("N", "amount_of_substance"),
        ("J", "luminous_intensity"),
    ]

    for symbol, basis_name in koq_order:
        try:
            exp = vec[basis_name]
        except (KeyError, TypeError):
            continue

        if exp == 0:
            continue
        elif exp == 1:
            components.append(symbol)
        elif exp == 2:
            components.append(f"{symbol}²")
        elif exp == 3:
            components.append(f"{symbol}³")
        elif exp == -1:
            components.append(f"{symbol}⁻¹")
        elif exp == -2:
            components.append(f"{symbol}⁻²")
        elif exp == -3:
            components.append(f"{symbol}⁻³")
        else:
            components.append(f"{symbol}^{exp}")

    return "·".join(components) if components else "1"


def _normalize_dimension_vector(vector_str: str) -> str:
    """Normalize a dimension vector string to canonical KOQ order.

    Takes a vector like "M·L²·T⁻²·N⁻¹·Θ⁻¹" and returns it in canonical order
    "M·L²·T⁻²·Θ⁻¹·N⁻¹" (M, L, T, I, Θ, N, J).

    This ensures consistent comparison regardless of input order.
    """
    import re

    # KOQ canonical order
    koq_order = ["M", "L", "T", "I", "Θ", "N", "J"]

    # Parse each component from the vector string
    # Components are separated by · and may have exponents like ², ³, ⁻¹, ⁻², ^-1, etc.
    exponents: dict[str, int] = {}

    # Split by · (middle dot)
    parts = vector_str.split("·")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Match symbol and optional exponent
        # Symbols: M, L, T, I, Θ, N, J
        # Exponents: ², ³, ⁻¹, ⁻², ⁻³, ^N, or none (implies 1)
        match = re.match(r'^([MLTIΘNJ])(.*)$', part)
        if not match:
            # Try alternative theta representations
            match = re.match(r'^(Theta|θ)(.*)$', part, re.IGNORECASE)
            if match:
                symbol = "Θ"
                exp_str = match.group(2)
            else:
                continue  # Unknown symbol, skip
        else:
            symbol = match.group(1)
            exp_str = match.group(2)

        # Parse exponent
        if not exp_str:
            exp = 1
        elif exp_str == "²":
            exp = 2
        elif exp_str == "³":
            exp = 3
        elif exp_str == "⁻¹":
            exp = -1
        elif exp_str == "⁻²":
            exp = -2
        elif exp_str == "⁻³":
            exp = -3
        elif exp_str.startswith("^"):
            try:
                exp = int(exp_str[1:])
            except ValueError:
                exp = 1
        else:
            # Try to parse superscript numbers
            superscript_map = {"⁰": 0, "¹": 1, "²": 2, "³": 3, "⁴": 4, "⁵": 5,
                              "⁶": 6, "⁷": 7, "⁸": 8, "⁹": 9, "⁻": "-"}
            exp_digits = ""
            for c in exp_str:
                if c in superscript_map:
                    exp_digits += str(superscript_map[c])
            if exp_digits:
                try:
                    exp = int(exp_digits)
                except ValueError:
                    exp = 1
            else:
                exp = 1

        exponents[symbol] = exponents.get(symbol, 0) + exp

    # Rebuild in canonical order
    components = []
    for symbol in koq_order:
        exp = exponents.get(symbol, 0)
        if exp == 0:
            continue
        elif exp == 1:
            components.append(symbol)
        elif exp == 2:
            components.append(f"{symbol}²")
        elif exp == 3:
            components.append(f"{symbol}³")
        elif exp == -1:
            components.append(f"{symbol}⁻¹")
        elif exp == -2:
            components.append(f"{symbol}⁻²")
        elif exp == -3:
            components.append(f"{symbol}⁻³")
        else:
            components.append(f"{symbol}^{exp}")

    return "·".join(components) if components else "1"


def _parse_dimension_to_vector(dimension_str: str) -> str | None:
    """Parse a dimension string to a vector signature.

    Accepts either:
    - Human-readable: "energy/amount_of_substance", "energy/temperature"
    - Vector notation: "M·L²·T⁻²·N⁻¹"

    Returns the vector signature in canonical order, or None if parsing fails.
    """
    # If it's already in vector notation, normalize to canonical order
    if any(c in dimension_str for c in ["·", "²", "³", "⁻"]):
        return _normalize_dimension_vector(dimension_str)

    # Try to parse as human-readable dimension
    # Common patterns: "X", "X/Y", "X/Y/Z", "X*Y/Z"
    known_vectors = {
        # Pure dimensions
        "energy": "M·L²·T⁻²",
        "length": "L",
        "mass": "M",
        "time": "T",
        "temperature": "Θ",
        "amount_of_substance": "N",
        "current": "I",
        "luminosity": "J",
        # Composite patterns
        "energy/amount_of_substance": "M·L²·T⁻²·N⁻¹",
        "energy/temperature": "M·L²·T⁻²·Θ⁻¹",
        "energy/(temperature*amount_of_substance)": "M·L²·T⁻²·Θ⁻¹·N⁻¹",
        "energy/(temperature·amount_of_substance)": "M·L²·T⁻²·Θ⁻¹·N⁻¹",
    }

    normalized = dimension_str.lower().replace(" ", "")
    return known_vectors.get(normalized)


@mcp.tool()
def define_quantity_kind(
    name: str,
    dimension: str,
    description: str = "",
    aliases: list[str] | None = None,
    category: str = "session",
    disambiguation_hints: list[str] | None = None,
    ctx: Context | None = None,
) -> QuantityKindDefinitionResult | KOQError:
    """
    Register a quantity kind for KOQ disambiguation.

    Quantity kinds identify physically distinct quantities that share
    the same dimensional signature. For example, enthalpy and Gibbs energy
    both have dimension energy/amount_of_substance but represent different
    physical quantities.

    Args:
        name: Unique identifier for the kind (e.g., "reaction_gibbs_energy").
        dimension: Dimension string, either human-readable (e.g., "energy/amount_of_substance")
            or vector notation (e.g., "M·L²·T⁻²·N⁻¹").
        description: Human-readable description of the quantity.
        aliases: Alternative names for the kind.
        category: Classification (defaults to "session").
        disambiguation_hints: Tips for distinguishing from similar kinds.

    Returns:
        QuantityKindDefinitionResult on success.
        KOQError if name conflicts or dimension is invalid.

    Example:
        define_quantity_kind(
            name="reaction_gibbs_energy",
            dimension="energy/amount_of_substance",
            description="Gibbs energy change for a chemical reaction at constant T,P",
            aliases=["delta_G_rxn"],
            disambiguation_hints=["Use ΔG = ΔH - TΔS formula"]
        )
    """
    session = _get_session(ctx)
    aliases = aliases or []
    disambiguation_hints = disambiguation_hints or []

    # Check for duplicate name in built-in kinds
    existing = get_quantity_kind(name)
    if existing is not None:
        return KOQError(
            error=f"Quantity kind '{name}' is already defined as '{existing.description}'",
            error_type="duplicate_kind",
            parameter="name",
            hints=["Use a different name or use the built-in kind"],
        )

    # Check for duplicate in session kinds
    session_kinds = session.get_quantity_kinds()
    if name in session_kinds:
        return KOQError(
            error=f"Quantity kind '{name}' is already defined in this session",
            error_type="duplicate_kind",
            parameter="name",
            hints=["Use reset_session() to clear session kinds"],
        )

    # Parse dimension to vector notation
    vector_signature = _parse_dimension_to_vector(dimension)
    if vector_signature is None:
        return KOQError(
            error=f"Could not parse dimension: '{dimension}'",
            error_type="invalid_dimension",
            parameter="dimension",
            hints=[
                "Use human-readable: 'energy/amount_of_substance'",
                "Or vector notation: 'M·L²·T⁻²·N⁻¹'",
                "Use list_quantity_kinds() to see examples",
            ],
        )

    # Create and register the kind
    kind = QuantityKindInfo(
        name=name,
        dimension_name=dimension,
        dimension_vector=vector_signature,
        description=description,
        aliases=tuple(aliases),
        category=category,
        disambiguation_hints=tuple(disambiguation_hints),
    )
    session.register_quantity_kind(kind)

    return QuantityKindDefinitionResult(
        success=True,
        name=name,
        dimension=dimension,
        vector_signature=vector_signature,
        category=category,
        message=f"Quantity kind '{name}' registered for session.",
    )


@mcp.tool()
def declare_computation(
    quantity_kind: str,
    expected_unit: str,
    context: dict[str, str] | None = None,
    ctx: Context | None = None,
) -> ComputationDeclaration | KOQError:
    """
    Declare computational intent before performing a calculation.

    This tool establishes the expected quantity kind before using
    compute() or other calculation tools. After computation, use
    validate_result() to verify the result matches the declaration.

    Args:
        quantity_kind: Name of the quantity kind (from list_quantity_kinds or
            previously defined via define_quantity_kind).
        expected_unit: Expected unit for the result (e.g., "kJ/mol").
        context: Optional context information (e.g., {"temperature": "298 K"}).

    Returns:
        ComputationDeclaration with warnings about dimensionally compatible kinds.
        KOQError if the quantity kind is unknown.

    Example:
        declare_computation(
            quantity_kind="gibbs_energy",
            expected_unit="kJ/mol",
            context={"temperature": "298.15 K", "pressure": "1 bar"}
        )
    """
    import uuid

    session = _get_session(ctx)
    session_kinds = session.get_quantity_kinds()

    # Look up the quantity kind
    kind = get_quantity_kind(quantity_kind, session_kinds)
    if kind is None:
        # Build suggestions
        available_kinds = list(session_kinds.keys())
        if available_kinds:
            hint_msg = f"Available kinds: {', '.join(sorted(available_kinds)[:10])}"
            if len(available_kinds) > 10:
                hint_msg += "..."
        else:
            hint_msg = "No quantity kinds defined yet"
        return KOQError(
            error=f"Unknown quantity kind: '{quantity_kind}'",
            error_type="unknown_kind",
            parameter="quantity_kind",
            hints=[
                hint_msg,
                "Use define_quantity_kind() to register quantity kinds",
                "Use list_quantity_kinds() to see all defined kinds",
            ],
        )

    # Parse expected unit to get dimension
    parsed_unit, err = resolve_unit(expected_unit, parameter="expected_unit")
    if err:
        return KOQError(
            error=f"Invalid expected_unit: '{expected_unit}'",
            error_type="invalid_unit",
            parameter="expected_unit",
            hints=err.hints if hasattr(err, 'hints') else [],
        )

    unit_vector = _get_dimension_vector(parsed_unit)
    expected_dim = kind.dimension_name

    # Check dimension compatibility
    warnings = []
    if unit_vector != kind.dimension_vector:
        warnings.append(
            f"Expected unit '{expected_unit}' has dimension '{unit_vector}' "
            f"which differs from kind '{quantity_kind}' dimension '{kind.dimension_vector}'"
        )

    # Find compatible kinds (same dimension vector)
    compatible = get_kinds_by_dimension(kind.dimension_vector, session_kinds)
    compatible_names = [k.name for k in compatible if k.name != quantity_kind]

    if compatible_names:
        warnings.append(
            f"{len(compatible_names)} other kinds share this dimension: "
            f"{', '.join(compatible_names[:5])}"
            + ("..." if len(compatible_names) > 5 else "")
        )

    # Generate declaration ID
    declaration_id = str(uuid.uuid4())[:8]

    # Create and store declaration
    decl = ComputationDeclaration(
        declaration_id=declaration_id,
        quantity_kind=quantity_kind,
        expected_unit=expected_unit,
        expected_dimension=expected_dim,
        status="warning" if warnings else "valid",
        warnings=warnings,
        compatible_kinds=compatible_names,
        message=f"Computation declared: computing '{quantity_kind}' in '{expected_unit}'",
    )
    session.set_active_computation(decl)

    return decl


@mcp.tool()
def validate_result(
    value: float,
    unit: str,
    declared_kind: str | None = None,
    reasoning: str | None = None,
    ctx: Context | None = None,
) -> ValidationResult | KOQError:
    """
    Validate that a computed result matches the declared quantity kind.

    Call this after compute() to verify the result is consistent with
    the declared computation. Uses the active declaration if declared_kind
    is not specified.

    Args:
        value: The computed numeric value.
        unit: The result unit string.
        declared_kind: Optional kind to validate against (uses active declaration if None).
        reasoning: Optional reasoning text for semantic consistency checking.

    Returns:
        ValidationResult with pass/fail status and confidence level.
        KOQError if no declaration is active and declared_kind not specified.

    Example:
        validate_result(
            value=-228.6,
            unit="kJ/mol",
            reasoning="Calculated ΔG = ΔH - TΔS at 298 K"
        )
    """
    session = _get_session(ctx)
    session_kinds = session.get_quantity_kinds()

    # Get the kind to validate against
    if declared_kind is not None:
        kind = get_quantity_kind(declared_kind, session_kinds)
        if kind is None:
            return KOQError(
                error=f"Unknown quantity kind: '{declared_kind}'",
                error_type="unknown_kind",
                parameter="declared_kind",
                hints=["Use list_quantity_kinds() to see available kinds"],
            )
        kind_name = declared_kind
        expected_dimension = kind.dimension_vector
    else:
        # Use active declaration
        active = session.get_active_computation()
        if active is None:
            return KOQError(
                error="No active computation declaration",
                error_type="no_active_declaration",
                parameter=None,
                hints=[
                    "Use declare_computation() before validate_result()",
                    "Or specify declared_kind parameter",
                ],
            )
        kind = get_quantity_kind(active.quantity_kind, session_kinds)
        kind_name = active.quantity_kind
        expected_dimension = kind.dimension_vector if kind else "unknown"

    # Parse result unit
    parsed_unit, err = resolve_unit(unit, parameter="unit")
    if err:
        return KOQError(
            error=f"Invalid unit: '{unit}'",
            error_type="invalid_unit",
            parameter="unit",
            hints=err.hints if hasattr(err, 'hints') else [],
        )

    actual_dimension = _get_dimension_vector(parsed_unit)
    dimension_match = actual_dimension == expected_dimension

    # Check semantic consistency if reasoning provided
    semantic_warnings = []
    if reasoning and kind:
        semantic_warnings = check_semantic_conflicts(kind_name, reasoning)

    # Determine confidence level
    if not dimension_match:
        confidence = "low"
        passed = False
        explanation = f"Dimension mismatch: got '{actual_dimension}', expected '{expected_dimension}'"
    elif semantic_warnings:
        confidence = "medium"
        passed = True
        explanation = "Dimension matches but reasoning may indicate different quantity"
    else:
        confidence = "high"
        passed = True
        explanation = f"Result validated as '{kind_name}'"

    # Build suggestions
    suggestions = []
    if not dimension_match:
        suggestions.append(f"Check that '{unit}' is the correct unit for '{kind_name}'")
    if semantic_warnings:
        suggestions.append("Review reasoning to ensure it matches the declared quantity kind")

    # Clear active declaration
    session.set_active_computation(None)

    return ValidationResult(
        passed=passed,
        value=value,
        unit=unit,
        declared_kind=kind_name,
        actual_dimension=actual_dimension,
        expected_dimension=expected_dimension,
        dimension_match=dimension_match,
        semantic_warnings=semantic_warnings,
        confidence=confidence,
        explanation=explanation,
        suggestions=suggestions,
    )


@mcp.tool()
def list_quantity_kinds(
    dimension: str | None = None,
    category: str | None = None,
    ctx: Context | None = None,
) -> list[dict] | KOQError:
    """
    List registered quantity kinds, optionally filtered.

    Returns both built-in and session-defined quantity kinds.

    Args:
        dimension: Optional filter by dimension (e.g., "energy/amount_of_substance"
            or vector notation "M·L²·T⁻²·N⁻¹").
        category: Optional filter by category (e.g., "thermodynamic", "mechanical").

    Returns:
        List of quantity kind information dicts.
        KOQError if dimension filter is invalid.

    Example:
        # List all kinds with energy/mole dimension
        list_quantity_kinds(dimension="energy/amount_of_substance")

        # List all thermodynamic kinds
        list_quantity_kinds(category="thermodynamic")
    """
    session = _get_session(ctx)
    session_kinds = session.get_quantity_kinds()

    # Parse dimension filter if provided
    dimension_vector = None
    if dimension:
        dimension_vector = _parse_dimension_to_vector(dimension)
        # If not a known pattern, assume it's already a vector
        if dimension_vector is None:
            dimension_vector = dimension

    # Collect session-defined kinds
    all_kinds = list(session_kinds.values())

    # Apply filters
    result = []
    for kind in all_kinds:
        if dimension_vector and kind.dimension_vector != dimension_vector:
            continue
        if category and kind.category != category:
            continue

        result.append({
            "name": kind.name,
            "dimension_name": kind.dimension_name,
            "dimension_vector": kind.dimension_vector,
            "description": kind.description,
            "aliases": list(kind.aliases),
            "category": kind.category,
            "disambiguation_hints": list(kind.disambiguation_hints),
        })

    return sorted(result, key=lambda k: (k["category"], k["name"]))


@mcp.tool()
def extend_basis(
    name: str,
    base: str = "SI",
    additional_components: list[dict] | None = None,
    ctx: Context | None = None,
) -> ExtendedBasisResult | KOQError:
    """
    Create an extended dimensional basis for KOQ disambiguation.

    Extended bases add semantic components to the standard SI basis,
    allowing finer-grained distinction between quantity kinds.

    The basis is stored in session state and persists for the session lifetime.
    Use list_extended_bases() to see available bases.

    Note: Phase 1 implementation is informational only. Extended bases
    help explain disambiguation strategies but don't yet affect conversions.

    Args:
        name: Name for the extended basis.
        base: Starting basis ("SI", "CGS"). Defaults to "SI".
        additional_components: List of new components, each with:
            - name: Component name (e.g., "thermal")
            - symbol: Component symbol (e.g., "Φ")
            - description: What the component represents

    Returns:
        ExtendedBasisResult with the new basis description.
        KOQError if base is unknown or name already exists.

    Example:
        extend_basis(
            name="thermodynamic",
            base="SI",
            additional_components=[
                {"name": "thermal", "symbol": "Φ", "description": "Thermal nature marker"},
                {"name": "work", "symbol": "Ψ", "description": "Work/mechanical marker"}
            ]
        )
    """
    session = _get_session(ctx)

    # Check for duplicate name
    existing_bases = session.get_extended_bases()
    if name in existing_bases:
        return KOQError(
            error=f"Extended basis '{name}' already exists in session",
            error_type="duplicate_basis",
            parameter="name",
            hints=["Use a different name or reset_session() to clear existing bases"],
        )

    valid_bases = {"SI", "CGS"}
    if base not in valid_bases:
        return KOQError(
            error=f"Unknown base: '{base}'",
            error_type="unknown_base",
            parameter="base",
            hints=[f"Valid bases: {', '.join(valid_bases)}"],
        )

    additional_components = additional_components or []

    # SI base components
    si_components = ["M (mass)", "L (length)", "T (time)", "I (current)",
                     "Θ (temperature)", "N (amount)", "J (luminosity)"]

    # Build component list
    components = si_components.copy()
    additional_tuples = []
    for comp in additional_components:
        comp_name = comp.get("name", "unknown")
        comp_symbol = comp.get("symbol", "?")
        comp_desc = comp.get("description", "")
        components.append(f"{comp_symbol} ({comp_name})")
        additional_tuples.append((comp_name, comp_symbol, comp_desc))

    # Store in session
    basis_info = ExtendedBasisInfo(
        name=name,
        base=base,
        components=tuple(components),
        additional_components=tuple(additional_tuples),
    )
    session.register_extended_basis(basis_info)

    return ExtendedBasisResult(
        success=True,
        name=name,
        base=base,
        components=components,
        message=f"Extended basis '{name}' created with {len(components)} components. "
                f"(Phase 1: informational only)",
    )


@mcp.tool()
def list_extended_bases(
    ctx: Context | None = None,
) -> list[dict]:
    """
    List all extended bases defined in the current session.

    Returns:
        List of extended basis information dictionaries, each containing:
        - name: The basis name
        - base: The starting basis (e.g., "SI")
        - components: List of all components in the basis
        - additional_components: List of added components as [name, symbol, description]

    Example:
        list_extended_bases()
        # → [{"name": "thermodynamic", "base": "SI", "components": [...], ...}]
    """
    session = _get_session(ctx)
    bases = session.get_extended_bases()

    return [
        {
            "name": basis.name,
            "base": basis.base,
            "components": list(basis.components),
            "additional_components": [
                {"name": c[0], "symbol": c[1], "description": c[2]}
                for c in basis.additional_components
            ],
        }
        for basis in bases.values()
    ]


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------


def main():
    """Run the ucon MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()

# MCP Server

ucon includes a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that exposes unit conversion and dimensional analysis to AI agents like Claude.

## Installation

```bash
pip install ucon-tools[mcp]
```

!!! note "Python 3.10+"
    The MCP server requires Python 3.10 or higher.

## Configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

**Via uvx (recommended):**

```json
{
  "mcpServers": {
    "ucon": {
      "command": "uvx",
      "args": ["--from", "ucon-tools[mcp]", "ucon-mcp"]
    }
  }
}
```

**Local development:**

```json
{
  "mcpServers": {
    "ucon": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ucon-tools", "--extra", "mcp", "ucon-mcp"]
    }
  }
}
```

### Claude Code / Cursor

The same configuration works for other MCP-compatible AI tools.

## Available Tools

### `convert`

Convert a value from one unit to another.

```python
convert(value=5, from_unit="km", to_unit="mi")
# → {"quantity": 3.107, "unit": "mi", "dimension": "length"}
```

Supports:

- Base units: `meter`, `m`, `second`, `s`, `gram`, `g`
- Scaled units: `km`, `mL`, `kg`, `MHz`
- Composite units: `m/s`, `kg*m/s^2`, `N*m`
- Exponents: `m^2`, `s^-1` (ASCII) or `m²`, `s⁻¹` (Unicode)

### `decompose`

Build a factor chain for `compute()` by analyzing dimensional requirements.

**Query mode** — simple conversions:

```python
decompose(query="500 mL to L")
# → {"initial_value": 500, "initial_unit": "mL", "target_unit": "L", "factors": [...]}
```

**Structured mode** — multi-step problems with known quantities:

```python
decompose(
    initial_unit="mcg/(kg*min)",
    target_unit="mg/h",
    known_quantities=[{"value": 70, "unit": "kg"}]
)
# → {"factors": [{"value": 70, "numerator": "kg", ...}, ...]}
# Pass the result's factors directly to compute()
```

The tool performs dimensional gap analysis, solves for the correct signed placement of each quantity (numerator or denominator) via constraint satisfaction, and auto-bridges residual unit mismatches (e.g., mcg to mg, min to h). For dimensionless counts like `ea`, express them as rates (`ea/d`, `ea/h`) to provide the missing time dimension.

### `compute`

Perform multi-step factor-label calculations with dimensional tracking.

```python
compute(
    initial_value=154,
    initial_unit="lb",
    factors=[
        {"value": 1, "numerator": "kg", "denominator": "2.205 lb"},
        {"value": 15, "numerator": "mg", "denominator": "kg*day"},
        {"value": 1, "numerator": "day", "denominator": "3 ea"},
    ]
)
# → {"quantity": 349.2, "unit": "mg/ea", "dimension": "mass/count", "steps": [...]}
```

Each step in the response shows intermediate quantity, unit, and dimension.

### `list_units`

Discover available units, optionally filtered by dimension.

```python
list_units(dimension="length")
# → [{"name": "meter", "shorthand": "m", "dimension": "length", ...}, ...]
```

### `list_scales`

List SI and binary prefixes.

```python
list_scales()
# → [{"name": "kilo", "prefix": "k", "factor": 1000.0}, ...]
```

### `check_dimensions`

Check if two units have compatible dimensions.

```python
check_dimensions(unit_a="kg", unit_b="lb")
# → {"compatible": true, "dimension_a": "mass", "dimension_b": "mass"}

check_dimensions(unit_a="kg", unit_b="m")
# → {"compatible": false, "dimension_a": "mass", "dimension_b": "length"}
```

### `list_dimensions`

List available physical dimensions.

```python
list_dimensions()
# → ["acceleration", "area", "energy", "force", "length", "mass", ...]
```

### `define_unit`

Register a custom unit for the session.

```python
define_unit(name="slug", dimension="mass", aliases=["slug"])
# → {"success": true, "message": "Unit 'slug' registered..."}
```

### `define_conversion`

Add a conversion edge between units.

```python
define_conversion(src="slug", dst="kg", factor=14.5939)
# → {"success": true, "message": "Conversion edge 'slug' → 'kg' added..."}
```

### `list_constants`

List available physical constants, optionally filtered by category.

```python
list_constants()
# → [{"symbol": "c", "name": "speed of light in vacuum", "value": 299792458, ...}, ...]

list_constants(category="exact")
# → [7 SI defining constants]

list_constants(category="session")
# → [user-defined constants]
```

Categories: `"exact"` (7), `"derived"` (3), `"measured"` (7), `"session"` (user-defined).

### `define_constant`

Register a custom constant for the session.

```python
define_constant(
    symbol="vₛ",
    name="speed of sound in dry air at 20°C",
    value=343,
    unit="m/s"
)
# → {"success": true, "symbol": "vₛ", ...}
```

### `reset_session`

Clear custom units, conversions, and constants.

```python
reset_session()
# → {"success": true, "message": "Session reset..."}
```

### `define_quantity_kind`

Register a quantity kind for semantic disambiguation.

```python
define_quantity_kind(
    name="entropy_change",
    dimension="energy/temperature",
    description="Change in entropy for a thermodynamic process"
)
# → {"success": true, "name": "entropy_change", "vector_signature": "M·L²·T⁻²·Θ⁻¹", ...}
```

Quantity kinds identify physically distinct quantities that share the same dimensional signature (e.g., entropy change vs heat capacity).

### `declare_computation`

Declare computational intent before performing a calculation.

```python
declare_computation(
    quantity_kind="entropy_change",
    expected_unit="J/K"
)
# → {"declaration_id": "...", "status": "valid", "compatible_kinds": ["heat_capacity"], ...}
```

Establishes the expected quantity kind so `validate_result()` can verify the result.

### `validate_result`

Validate that a computed result matches the declared quantity kind.

```python
validate_result(
    value=91.5,
    unit="J/K",
    reasoning="Calculated ΔS = Q/T for isothermal heat transfer"
)
# → {"passed": true, "confidence": "high", "semantic_warnings": [], ...}
```

Checks dimensional consistency and analyzes reasoning text for semantic conflicts.

### `list_formulas`

List registered domain formulas with dimensional constraints.

```python
list_formulas()
# → [{"name": "bmi", "description": "Body Mass Index", "parameters": {"mass": "mass", "height": "length"}}]
```

### `call_formula`

Invoke a registered formula with dimensionally-validated inputs.

```python
call_formula(
    name="bmi",
    parameters={
        "mass": {"value": 70, "unit": "kg"},
        "height": {"value": 1.75, "unit": "m"}
    }
)
# → {"formula": "bmi", "quantity": 22.86, "unit": "kg/m²", ...}
```

See [Registering Formulas](registering-formulas.md) for how to create formulas.

## Error Recovery

When conversions fail, the MCP server returns structured errors with suggestions:

```python
convert(value=1, from_unit="kilogram", to_unit="meter")
# → {
#     "error": "Dimension mismatch: mass ≠ length",
#     "error_type": "dimension_mismatch",
#     "likely_fix": "Use a mass unit like 'lb' or 'g'"
# }
```

For typos:

```python
convert(value=1, from_unit="kilgoram", to_unit="kg")
# → {
#     "error": "Unknown unit: 'kilgoram'",
#     "error_type": "unknown_unit",
#     "likely_fix": "Did you mean 'kilogram'?"
# }
```

## Custom Units (Inline)

For one-off conversions without session state:

```python
convert(
    value=1,
    from_unit="slug",
    to_unit="kg",
    custom_units=[{"name": "slug", "dimension": "mass", "aliases": ["slug"]}],
    custom_edges=[{"src": "slug", "dst": "kg", "factor": 14.5939}]
)
```

## Example Conversation

**User:** How many milligrams of ibuprofen should a 154 lb patient receive if the dose is 10 mg/kg?

**Claude:** (calls `compute`)

```python
compute(
    initial_value=154,
    initial_unit="lb",
    factors=[
        {"value": 1, "numerator": "kg", "denominator": "2.205 lb"},
        {"value": 10, "numerator": "mg", "denominator": "kg"},
    ]
)
```

**Result:** 698.4 mg

The step trace shows dimensional consistency at each point, so Claude can verify the calculation is physically meaningful.

## Evaluating with UnitSafe

[UnitSafe](https://huggingface.co/datasets/radiativity/UnitSafe) is a 500-problem benchmark for measuring how well models handle unit conversion, dimensional analysis, and kind-of-quantity discrimination. Use it to compare bare model performance against tool-augmented performance with the MCP server:

```bash
# Bare evaluation (no tools — model solves from memory)
python benchmarks/unitsafe/run.py -m claude:claude-haiku-4-5-20251001

# Tool-augmented evaluation (model uses MCP tools)
python benchmarks/unitsafe/run.py -m claude:claude-haiku-4-5-20251001 \
  --tools --force-tools --mcp-url https://mcp.ucon.dev/mcp/<instance>/mcp

# Use a different model as judge for answer extraction
python benchmarks/unitsafe/run.py -m ollama:llama3.2:3b \
  --judge claude:claude-haiku-4-5-20251001
```

See [`benchmarks/unitsafe/`](https://github.com/withtwoemms/ucon-tools/tree/main/benchmarks/unitsafe) for the full dataset, runner documentation, and evaluation protocol.

## Guides

- [Registering Formulas](registering-formulas.md) — Expose dimensionally-typed calculations to agents
- [Custom Units via MCP](custom-units.md) — Define domain-specific units at runtime

## Background

- [Kind-of-Quantity Problem](https://docs.ucon.dev/architecture/kind-of-quantity) — Why dimensions alone don't uniquely identify physical quantities

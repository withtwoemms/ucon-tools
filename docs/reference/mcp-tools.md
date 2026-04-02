# MCP Tools Reference

Complete schema and response format documentation for ucon MCP server tools.

---

## convert

Convert a numeric value from one unit to another.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `value` | float | Yes | The numeric quantity to convert |
| `from_unit` | string | Yes | Source unit string |
| `to_unit` | string | Yes | Target unit string |
| `custom_units` | list[dict] | No | Inline unit definitions |
| `custom_edges` | list[dict] | No | Inline conversion edges |

### Response Schema

**Success: `ConversionResult`**

```json
{
  "quantity": 3.107,
  "unit": "mi",
  "dimension": "length",
  "uncertainty": null
}
```

**Error: `ConversionError`**

```json
{
  "error": "Dimension mismatch: mass is not length",
  "error_type": "dimension_mismatch",
  "parameter": "to_unit",
  "likely_fix": "Use a mass unit like 'lb' or 'g'"
}
```

### Examples

```python
# Simple conversion
convert(value=5, from_unit="km", to_unit="mi")
# → {"quantity": 3.107, "unit": "mi", "dimension": "length"}

# Composite units
convert(value=10, from_unit="m/s", to_unit="km/h")
# → {"quantity": 36.0, "unit": "km/h", "dimension": "velocity"}

# With inline custom unit
convert(
    value=1,
    from_unit="slug",
    to_unit="kg",
    custom_units=[{"name": "slug", "dimension": "mass", "aliases": ["slug"]}],
    custom_edges=[{"src": "slug", "dst": "kg", "factor": 14.5939}]
)
# → {"quantity": 14.5939, "unit": "kg", "dimension": "mass"}
```

---

## decompose

Build a factor chain for `compute()` by analyzing dimensional requirements.

Operates in two modes: **query mode** for simple conversions, and **structured mode** for multi-step problems where known quantities bridge dimensional gaps.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | No | Simple conversion query (e.g., `"500 mL to L"`, `"50 psi to kPa"`) |
| `initial_unit` | string | No | Starting unit string (use with `target_unit`) |
| `target_unit` | string | No | Target unit string (use with `initial_unit`) |
| `known_quantities` | list[dict] | No | Quantities to incorporate into the factor chain |

Must provide either `query` **or** both `initial_unit` and `target_unit`.

**Known quantity dict schema:**

| Field | Type | Description |
|-------|------|-------------|
| `value` | float | Numeric value (e.g., 70) |
| `unit` | string | Unit string (e.g., `"kg"`) |

### Response Schema

**Success: `DecomposeResult`**

```json
{
  "initial_value": 500,
  "initial_unit": "mL",
  "target_unit": "L",
  "factors": [
    {"value": 0.001, "numerator": "L", "denominator": "mL"}
  ]
}
```

`initial_value` is extracted from the query string (if present) or `null` for structured mode. The `factors` list can be passed directly to `compute()`.

**Error: `ConversionError`**

```json
{
  "error": "Cannot bridge dimensional gap from 'mcg/(kg*min)' to 'mg/h'",
  "error_type": "dimension_mismatch",
  "parameter": "known_quantities",
  "hints": [
    "Need to add 'mass' (exponent 1) - provide a quantity with this dimension",
    "Add more known_quantities to bridge the gap"
  ]
}
```

### Examples

```python
# Query mode: simple conversion
decompose(query="500 mL to L")
# → {"initial_value": 500, "initial_unit": "mL", "target_unit": "L", "factors": [...]}

# Query mode: composite units
decompose(query="60 mph to km/h")
# → {"initial_value": 60, "initial_unit": "mph", "target_unit": "km/h", "factors": [...]}

# Structured mode: weight-based dosing
# Problem: "5 mcg/kg/min for a 70 kg patient. Rate in mg/h?"
decompose(
    initial_unit="mcg/(kg*min)",
    target_unit="mg/h",
    known_quantities=[{"value": 70, "unit": "kg"}]
)
# → factors for kg cancellation, min→h, mcg→mg

# Structured mode: IV drip rate
# Problem: "1000 mL over 8 hours, 15 gtt/mL tubing. Rate in gtt/min?"
decompose(
    initial_unit="mL",
    target_unit="gtt/min",
    known_quantities=[
        {"value": 8, "unit": "h"},
        {"value": 15, "unit": "gtt/mL"}
    ]
)

# Structured mode: concentration-based infusion
# Problem: "Dopamine 5 mcg/kg/min for 80 kg patient. Drug is 400 mg in 250 mL. mL/h?"
decompose(
    initial_unit="mcg/(kg*min)",
    target_unit="mL/h",
    known_quantities=[
        {"value": 80, "unit": "kg"},
        {"value": 250, "unit": "mL"},
        {"value": 400, "unit": "mg"},
    ],
)
# → 400 mg placed in denominator (constraint solver), plus mcg→mg and min→h
#   bridging factors (auto-bridged). compute(initial_value=5, factors=...) == 15.0 mL/h

# Structured mode: dosing with count rate
# Problem: "25 mg/kg/day for 15 kg child, divided into 3 doses/day. mg per dose?"
# Note: express count as a rate (ea/d), not bare ea
decompose(
    initial_unit="mg/(kg*d)",
    target_unit="mg",
    known_quantities=[
        {"value": 15, "unit": "kg"},
        {"value": 3, "unit": "ea/d"},
    ],
)
# → compute(initial_value=25, factors=...) == 125.0 mg

# Chain with compute:
result = decompose(query="3 TB to GiB")
compute(
    initial_value=result.initial_value,
    initial_unit=result.initial_unit,
    factors=result.factors
)
```

---

## compute

Perform multi-step factor-label calculations with dimensional tracking.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `initial_value` | float | Yes | Starting numeric quantity |
| `initial_unit` | string | Yes | Starting unit string |
| `factors` | list[dict] | Yes | Conversion factor chain |
| `custom_units` | list[dict] | No | Inline unit definitions |
| `custom_edges` | list[dict] | No | Inline conversion edges |

**Factor dict schema:**

| Field | Type | Description |
|-------|------|-------------|
| `value` | float | Numeric coefficient (default: 1.0) |
| `numerator` | string | Numerator unit string |
| `denominator` | string | Denominator unit string (may include numeric prefix) |

### Response Schema

**Success: `ComputeResult`**

```json
{
  "quantity": 349.2,
  "unit": "mg/ea",
  "dimension": "mass/count",
  "steps": [
    {"factor": "154 lb", "dimension": "mass", "unit": "lb"},
    {"factor": "(1 kg / 2.205 lb)", "dimension": "mass", "unit": "kg"},
    {"factor": "(15 mg / kg*day)", "dimension": "mass/time", "unit": "mg/d"},
    {"factor": "(1 day / 3 ea)", "dimension": "mass/count", "unit": "mg/ea"}
  ]
}
```

### Examples

```python
# Weight-based dosing calculation
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

# IV drip rate
compute(
    initial_value=1000,
    initial_unit="mL",
    factors=[
        {"value": 15, "numerator": "drop", "denominator": "mL"},
        {"value": 1, "numerator": "1", "denominator": "8 hr"},
        {"value": 1, "numerator": "hr", "denominator": "60 min"},
    ],
    custom_units=[{"name": "drop", "dimension": "count", "aliases": ["gtt"]}]
)
# → {"quantity": 31.25, "unit": "gtt/min", ...}
```

---

## list_units

List available units, optionally filtered by dimension.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `dimension` | string | No | Filter by dimension name |

### Response Schema

**Success: `list[UnitInfo]`**

```json
[
  {
    "name": "meter",
    "shorthand": "m",
    "aliases": ["m"],
    "dimension": "length",
    "scalable": true
  },
  {
    "name": "foot",
    "shorthand": "ft",
    "aliases": ["ft", "feet"],
    "dimension": "length",
    "scalable": false
  }
]
```

### Examples

```python
# List all units
list_units()

# Filter by dimension
list_units(dimension="mass")
# → [{"name": "gram", ...}, {"name": "kilogram", ...}, ...]
```

---

## list_scales

List available scale prefixes.

### Parameters

None.

### Response Schema

**Success: `list[ScaleInfo]`**

```json
[
  {"name": "peta", "prefix": "P", "factor": 1e15},
  {"name": "tera", "prefix": "T", "factor": 1e12},
  {"name": "giga", "prefix": "G", "factor": 1e9},
  {"name": "mega", "prefix": "M", "factor": 1e6},
  {"name": "kilo", "prefix": "k", "factor": 1000.0},
  {"name": "gibi", "prefix": "Gi", "factor": 1073741824.0},
  {"name": "mebi", "prefix": "Mi", "factor": 1048576.0},
  {"name": "kibi", "prefix": "Ki", "factor": 1024.0}
]
```

---

## list_dimensions

List available physical dimensions.

### Parameters

None.

### Response Schema

**Success: `list[str]`**

```json
[
  "acceleration", "amount_of_substance", "angle", "angular_momentum",
  "area", "capacitance", "catalytic_activity", "charge", "conductance",
  "conductivity", "count", "current", "density", "dynamic_viscosity",
  "electric_field_strength", "energy", "entropy", "force", "frequency",
  "gravitation", "illuminance", "inductance", "information",
  "kinematic_viscosity", "length", "luminous_intensity", "magnetic_flux",
  "magnetic_flux_density", "magnetic_permeability", "mass", "molar_mass",
  "molar_volume", "momentum", "none", "permittivity", "power", "pressure",
  "ratio", "resistance", "resistivity", "solid_angle",
  "specific_heat_capacity", "temperature", "thermal_conductivity", "time",
  "velocity", "voltage", "volume"
]
```

---

## check_dimensions

Check if two units have compatible dimensions.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `unit_a` | string | Yes | First unit string |
| `unit_b` | string | Yes | Second unit string |

### Response Schema

**Success: `DimensionCheck`**

```json
{
  "compatible": true,
  "dimension_a": "mass",
  "dimension_b": "mass"
}
```

### Examples

```python
# Compatible units
check_dimensions(unit_a="kg", unit_b="lb")
# → {"compatible": true, "dimension_a": "mass", "dimension_b": "mass"}

# Incompatible units
check_dimensions(unit_a="kg", unit_b="m")
# → {"compatible": false, "dimension_a": "mass", "dimension_b": "length"}
```

---

## define_unit

Register a custom unit for the session.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | Yes | Canonical unit name |
| `dimension` | string | Yes | Dimension name (use `list_dimensions()`) |
| `aliases` | list[str] | No | Shorthand symbols |

### Response Schema

**Success: `UnitDefinitionResult`**

```json
{
  "success": true,
  "name": "slug",
  "dimension": "mass",
  "aliases": ["slug"],
  "message": "Unit 'slug' registered for session. Use define_conversion() to add conversion edges."
}
```

### Examples

```python
define_unit(name="slug", dimension="mass", aliases=["slug"])
define_unit(name="nautical_mile", dimension="length", aliases=["nmi", "NM"])
```

---

## define_conversion

Add a conversion edge between units.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `src` | string | Yes | Source unit name/alias |
| `dst` | string | Yes | Destination unit name/alias |
| `factor` | float | Yes | Conversion multiplier: `dst = src * factor` |

### Response Schema

**Success: `ConversionDefinitionResult`**

```json
{
  "success": true,
  "src": "slug",
  "dst": "kg",
  "factor": 14.5939,
  "message": "Conversion edge 'slug' -> 'kg' (factor=14.5939) added to session."
}
```

### Examples

```python
# After define_unit("slug", "mass", ["slug"])
define_conversion(src="slug", dst="kg", factor=14.5939)

# Now convert() can use the new unit
convert(value=1, from_unit="slug", to_unit="lb")
```

---

## list_constants

List available physical constants, optionally filtered by category.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `category` | string | No | Filter by category: `"exact"`, `"derived"`, `"measured"`, `"session"`, `"all"` |

### Response Schema

**Success: `list[ConstantInfo]`**

```json
[
  {
    "symbol": "c",
    "name": "speed of light in vacuum",
    "value": 299792458,
    "unit": "m/s",
    "dimension": "velocity",
    "uncertainty": null,
    "is_exact": true,
    "source": "CODATA 2022",
    "category": "exact"
  },
  {
    "symbol": "G",
    "name": "Newtonian constant of gravitation",
    "value": 6.6743e-11,
    "unit": "m³/(kg·s²)",
    "dimension": "gravitation",
    "uncertainty": 1.5e-15,
    "is_exact": false,
    "source": "CODATA 2022",
    "category": "measured"
  }
]
```

**Error: `ConstantError`**

```json
{
  "error": "Unknown category: 'invalid'",
  "error_type": "invalid_input",
  "parameter": "category",
  "hints": ["Valid categories: exact, derived, measured, session, all"]
}
```

### Categories

| Category | Description | Count |
|----------|-------------|-------|
| `exact` | SI defining constants (2019 redefinition) | 7 |
| `derived` | Derived from exact constants | 3 |
| `measured` | Experimentally measured (with uncertainty) | 7 |
| `session` | User-defined via `define_constant()` | varies |

### Examples

```python
# List all constants
list_constants()
# → [{"symbol": "c", ...}, {"symbol": "h", ...}, ...]

# Filter by category
list_constants(category="exact")
# → [{"symbol": "c", ...}, {"symbol": "h", ...}, ...] (7 exact constants)

# Session constants only
list_constants(category="session")
# → [] (empty until define_constant() is called)
```

---

## define_constant

Define a custom constant for the current session.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `symbol` | string | Yes | Short symbol (e.g., `"vₛ"`, `"Eg"`) |
| `name` | string | Yes | Full descriptive name |
| `value` | float | Yes | Numeric value in given units |
| `unit` | string | Yes | Unit string (e.g., `"m/s"`, `"J"`) |
| `uncertainty` | float | No | Standard uncertainty (None for exact) |
| `source` | string | No | Data source reference |

### Response Schema

**Success: `ConstantDefinitionResult`**

```json
{
  "success": true,
  "symbol": "vₛ",
  "name": "speed of sound in dry air at 20°C",
  "unit": "m/s",
  "uncertainty": null,
  "message": "Constant 'vₛ' registered for session."
}
```

**Error: `ConstantError`**

```json
{
  "error": "Symbol 'c' is already defined as 'speed of light in vacuum'",
  "error_type": "duplicate_symbol",
  "parameter": "symbol",
  "hints": ["Use a different symbol or use the built-in constant"]
}
```

### Error Types

| Error Type | Description |
|------------|-------------|
| `duplicate_symbol` | Symbol exists in built-in or session constants |
| `invalid_unit` | Unit string cannot be parsed |
| `invalid_value` | Value is NaN, Inf, or non-numeric |

### Examples

```python
# Define speed of sound
define_constant(
    symbol="vₛ",
    name="speed of sound in dry air at 20°C",
    value=343,
    unit="m/s"
)

# Define with uncertainty
define_constant(
    symbol="g_local",
    name="local gravitational acceleration",
    value=9.81,
    unit="m/s^2",
    uncertainty=0.01,
    source="measured on site"
)

# Now visible in session constants
list_constants(category="session")
# → [{"symbol": "vₛ", ...}, {"symbol": "g_local", ...}]
```

---

## reset_session

Clear all custom units, conversions, and constants.

### Parameters

None.

### Response Schema

**Success: `SessionResult`**

```json
{
  "success": true,
  "message": "Session reset. All custom units, conversions, and constants cleared."
}
```

---

## list_formulas

List registered domain formulas with their dimensional constraints.

### Parameters

None.

### Response Schema

**Success: `list[FormulaInfoResponse]`**

```json
[
  {
    "name": "bmi",
    "description": "Body Mass Index",
    "parameters": {
      "mass": "mass",
      "height": "length"
    }
  }
]
```

### Examples

```python
list_formulas()
# → [{"name": "bmi", "description": "Body Mass Index", "parameters": {"mass": "mass", "height": "length"}}]
```

---

## call_formula

Invoke a registered formula with dimensionally-validated inputs.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | Yes | Formula name (from `list_formulas()`) |
| `parameters` | dict[str, dict] | Yes | Parameter values (see format below) |

**Parameter value format:**

```json
{
  "mass": {"value": 70, "unit": "kg"},
  "height": {"value": 1.75, "unit": "m"},
  "factor": {"value": 2.5}
}
```

- Use `{"value": ..., "unit": "..."}` for dimensioned quantities
- Use `{"value": ...}` for dimensionless quantities

### Response Schema

**Success: `FormulaResult`**

```json
{
  "formula": "bmi",
  "quantity": 22.86,
  "unit": "kg/m²",
  "dimension": "derived(mass/length²)",
  "uncertainty": null
}
```

**Error: `FormulaError`**

```json
{
  "error": "Missing required parameter: 'height'",
  "error_type": "missing_parameter",
  "formula": "bmi",
  "parameter": "height",
  "expected": "length",
  "hints": ["Parameter 'height' expects dimension: length"]
}
```

### Error Types

| Error Type | Description |
|------------|-------------|
| `unknown_formula` | Formula name not found in registry |
| `missing_parameter` | Required parameter not provided |
| `invalid_parameter` | Parameter format incorrect or unit unknown |
| `dimension_mismatch` | Parameter has wrong dimension |
| `execution_error` | Formula raised an exception |

### Examples

```python
# Call BMI formula
call_formula(
    name="bmi",
    parameters={
        "mass": {"value": 70, "unit": "kg"},
        "height": {"value": 1.75, "unit": "m"}
    }
)
# → {"formula": "bmi", "quantity": 22.86, "unit": "kg/m²", ...}

# Dimensionless parameter
call_formula(
    name="scale_value",
    parameters={
        "x": {"value": 10, "unit": "m"},
        "factor": {"value": 2.5}
    }
)
# → {"formula": "scale_value", "quantity": 25.0, "unit": "m", ...}
```

### Registering Formulas

Formulas are registered in Python code using `@register_formula`:

```python
from ucon import Number, Dimension, enforce_dimensions
from ucon.tools.mcp.formulas import register_formula

@register_formula("bmi", description="Body Mass Index")
@enforce_dimensions
def bmi(
    mass: Number[Dimension.mass],
    height: Number[Dimension.length],
) -> Number:
    return mass / (height * height)
```

The `@enforce_dimensions` decorator enables runtime dimension checking. Parameter constraints are extracted automatically and exposed via `list_formulas()`.

---

## Error Types

All tools may return `ConversionError` with these error types:

| Error Type | Description | Example |
|------------|-------------|---------|
| `unknown_unit` | Unit string not recognized | `"kilgoram"` typo |
| `dimension_mismatch` | Units have incompatible dimensions | kg to m |
| `no_conversion_path` | No edge path between units | Custom unit without edge |
| `invalid_input` | Malformed parameter | Missing required field |
| `computation_error` | Runtime calculation failure | Division by zero |

### Error Response Schema

```json
{
  "error": "Human-readable error message",
  "error_type": "unknown_unit",
  "parameter": "from_unit",
  "step": 2,
  "likely_fix": "Did you mean 'kilogram'?",
  "hints": ["Check spelling", "Use list_units() to see available units"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Human-readable message |
| `error_type` | string | Machine-readable error category |
| `parameter` | string | Which parameter caused the error |
| `step` | int | For compute(), which factor step failed (0-indexed) |
| `likely_fix` | string | Suggested correction (typos, dimension swaps) |
| `hints` | list[str] | Additional guidance |

---

## Kind-of-Quantity (KOQ) Tools

These tools disambiguate physically distinct quantities that share the same dimensional signature.
For background, see [Kind-of-Quantity](https://docs.ucon.dev/architecture/kind-of-quantity).

---

## define_quantity_kind

Register a quantity kind for semantic disambiguation.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | Yes | Unique identifier (e.g., "reaction_gibbs_energy") |
| `dimension` | string | Yes | Dimension string (e.g., "energy/amount_of_substance" or "M·L²·T⁻²·N⁻¹") |
| `description` | string | No | Human-readable description |
| `aliases` | list[str] | No | Alternative names |
| `category` | string | No | Classification (default: "session") |
| `disambiguation_hints` | list[str] | No | Tips for distinguishing from similar kinds |

### Response Schema

**Success: `QuantityKindDefinitionResult`**

```json
{
  "success": true,
  "name": "reaction_gibbs_energy",
  "dimension": "energy/amount_of_substance",
  "vector_signature": "M·L²·T⁻²·N⁻¹",
  "category": "session",
  "message": "Quantity kind 'reaction_gibbs_energy' registered for session."
}
```

**Error: `KOQError`**

```json
{
  "error": "Quantity kind 'gibbs_energy' is already defined",
  "error_type": "duplicate_kind",
  "parameter": "name",
  "hints": ["Use a different name or use the built-in kind"]
}
```

### Examples

```python
# Define a thermodynamic quantity kind
define_quantity_kind(
    name="reaction_gibbs_energy",
    dimension="energy/amount_of_substance",
    description="Gibbs energy change for a chemical reaction at constant T,P",
    aliases=["delta_G_rxn"],
    disambiguation_hints=["Use ΔG = ΔH - TΔS formula"]
)

# Define entropy change (distinct from heat capacity, same dimension)
define_quantity_kind(
    name="entropy_change",
    dimension="energy/temperature",
    description="Change in entropy for a process",
    aliases=["delta_S"],
    category="thermodynamic"
)
```

---

## declare_computation

Declare computational intent before performing a calculation.

Establishes the expected quantity kind before using `compute()` or other calculation tools.
After computation, use `validate_result()` to verify the result matches the declaration.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `quantity_kind` | string | Yes | Name of quantity kind (from `define_quantity_kind`) |
| `expected_unit` | string | Yes | Expected unit for the result (e.g., "kJ/mol") |
| `context` | dict[str, str] | No | Optional context (e.g., `{"temperature": "298 K"}`) |

### Response Schema

**Success: `ComputationDeclaration`**

```json
{
  "declaration_id": "a1b2c3d4-...",
  "quantity_kind": "gibbs_energy",
  "expected_unit": "kJ/mol",
  "expected_dimension": "M·L²·T⁻²·N⁻¹",
  "status": "valid",
  "warnings": [],
  "compatible_kinds": ["enthalpy", "chemical_potential", "activation_energy"],
  "message": "Computation declared: expecting 'gibbs_energy' in kJ/mol"
}
```

**Error: `KOQError`**

```json
{
  "error": "Unknown quantity kind: 'gibs_energy'",
  "error_type": "unknown_kind",
  "parameter": "quantity_kind",
  "hints": [
    "Available kinds: gibbs_energy, enthalpy, entropy_change...",
    "Use define_quantity_kind() to register quantity kinds"
  ]
}
```

### Examples

```python
# Declare intent to compute Gibbs energy
declare_computation(
    quantity_kind="gibbs_energy",
    expected_unit="kJ/mol",
    context={"temperature": "298.15 K", "pressure": "1 bar"}
)

# Declare entropy calculation
declare_computation(
    quantity_kind="entropy_change",
    expected_unit="J/K"
)
```

---

## validate_result

Validate that a computed result matches the declared quantity kind.

Call this after `compute()` to verify dimensional and semantic consistency.
Uses the active declaration from `declare_computation()` if `declared_kind` is not specified.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `value` | float | Yes | The computed numeric value |
| `unit` | string | Yes | The result unit string |
| `declared_kind` | string | No | Kind to validate against (uses active declaration if None) |
| `reasoning` | string | No | Reasoning text for semantic consistency checking |

### Response Schema

**Success: `ValidationResult`**

```json
{
  "passed": true,
  "value": -228.6,
  "unit": "kJ/mol",
  "declared_kind": "gibbs_energy",
  "actual_dimension": "M·L²·T⁻²·N⁻¹",
  "expected_dimension": "M·L²·T⁻²·N⁻¹",
  "dimension_match": true,
  "semantic_warnings": [],
  "confidence": "high",
  "explanation": "Result validated as 'gibbs_energy'",
  "suggestions": []
}
```

**With semantic warnings:**

```json
{
  "passed": true,
  "value": -228.6,
  "unit": "kJ/mol",
  "declared_kind": "gibbs_energy",
  "actual_dimension": "M·L²·T⁻²·N⁻¹",
  "expected_dimension": "M·L²·T⁻²·N⁻¹",
  "dimension_match": true,
  "semantic_warnings": [
    "Reasoning mentions 'ΔH' which is associated with 'enthalpy', but declared kind is 'gibbs_energy'"
  ],
  "confidence": "medium",
  "explanation": "Dimension matches but reasoning may indicate different quantity",
  "suggestions": ["Review reasoning to ensure it matches the declared quantity kind"]
}
```

**Error: `KOQError`**

```json
{
  "error": "No active computation declaration",
  "error_type": "no_active_declaration",
  "parameter": null,
  "hints": [
    "Use declare_computation() before validate_result()",
    "Or specify declared_kind parameter"
  ]
}
```

### Examples

```python
# Validate using active declaration
validate_result(
    value=-228.6,
    unit="kJ/mol",
    reasoning="Calculated ΔG = ΔH - TΔS at 298 K"
)

# Validate with explicit kind
validate_result(
    value=91.5,
    unit="J/K",
    declared_kind="entropy_change",
    reasoning="Computed ΔS = Q/T for isothermal heat transfer"
)
```

---

## KOQ Error Types

| Error Type | Description |
|------------|-------------|
| `unknown_kind` | Quantity kind name not recognized |
| `duplicate_kind` | Attempting to redefine existing kind |
| `dimension_mismatch` | Result dimension doesn't match declared kind |
| `no_active_declaration` | `validate_result()` called without prior `declare_computation()` |
| `invalid_unit` | Unit string cannot be parsed |

---

## KOQ Workflow

The recommended workflow for KOQ-aware computations:

```python
# 1. Define the quantity kind (if not already defined)
define_quantity_kind(
    name="entropy_change",
    dimension="energy/temperature",
    description="Change in entropy for a thermodynamic process"
)

# 2. Declare computational intent
declare_computation(
    quantity_kind="entropy_change",
    expected_unit="J/K"
)

# 3. Perform calculation (using compute() or manually)
# ... calculation logic ...

# 4. Validate the result
validate_result(
    value=91.5,
    unit="J/K",
    reasoning="Calculated ΔS = Q/T = 25000 J / 273.15 K"
)
# → {"passed": true, "confidence": "high", ...}
```

This workflow catches errors where the numeric result and units are correct,
but the physical quantity is misidentified (e.g., computing heat capacity
when entropy change was intended).

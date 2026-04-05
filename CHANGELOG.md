# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-04-05

### Fixed

- `bmi` formula now normalizes inputs to kg/m before computing, producing correct kg/m² results regardless of input units (cm, inches, lb, etc.)
- `reynolds_number` formula no longer produces 1000× error when density is provided in `kg/m³`; inputs are normalized to coherent SI units before computing the dimensionless result
- `fib4` formula accepts dimensionless AST/ALT values (removes `Dimension.frequency` constraint that rejected clinical `U/L` units)
- `error_budget_remaining` formula reimplemented using standard SRE formulation: `1 - (error_rate / allowed_error_rate)` instead of `SLO - error_rate`

### Notes

- BMI and Reynolds number fixes follow the same normalization pattern already used by BSA, CrCl, and Tsiolkovsky — extract to canonical units via `.to()` before applying the formula
- The Reynolds number root cause is a scale prefix asymmetry in `Number` algebra when mixing prefix-decomposed units (`kg` = kilo × gram) with opaque derived units (`Pa`); normalizing to floats before computing avoids the issue at the formula layer
- FIB-4's AST/ALT parameters are now unconstrained (`Number`) like platelets, matching clinical usage where enzyme activity values are passed as raw numeric U/L counts

## [0.4.0] - 2026-04-05

### Added

- 30 built-in domain formulas across 6 domains, registered at server startup and immediately available via `list_formulas` / `call_formula`:
  - **Medical** (5): `bmi`, `bsa` (Du Bois), `creatinine_clearance` (Cockcroft-Gault), `fib4`, `mean_arterial_pressure`
  - **Engineering** (5): `reynolds_number`, `ohms_law_power`, `stress`, `darcy_weisbach`, `kinetic_energy`
  - **Chemistry** (5): `ideal_gas_pressure`, `molarity`, `dilution`, `moles_from_mass`, `gibbs_free_energy`
  - **Physics** (5): `gravitational_force`, `photon_energy`, `coulombs_law`, `projectile_range`, `schwarzschild_radius`
  - **SRE** (5): `availability`, `error_budget_remaining`, `mtbf`, `mttr`, `throughput`
  - **Aerospace** (5): `orbital_velocity`, `escape_velocity`, `orbital_period`, `tsiolkovsky_delta_v`, `thrust`

### Changed

- Formula registry restructured from single module (`formulas.py`) to package (`formulas/`)
  - `formulas/_registry.py` — registry internals
  - `formulas/{medical,engineering,chemistry,physics,sre,aerospace}.py` — domain modules
  - `formulas/__init__.py` — re-exports public API and triggers domain registration on import
  - Backward compatible: `from ucon.tools.mcp.formulas import register_formula` unchanged

### Notes

- Formulas exercise 24 dimensions as inputs or outputs: mass, length, time, temperature, pressure, velocity, density, dynamic_viscosity, force, area, volume, energy, power, voltage, resistance, frequency, charge, amount_of_substance, concentration, molar_mass, entropy, angle, information, and dimensionless
- Empirical formulas (BSA, Cockcroft-Gault, FIB-4, Tsiolkovsky) normalize inputs to canonical units before applying coefficients
- Physics and aerospace formulas consume CODATA 2022 constants (`G`, `h`, `c`, `ε₀`) from `ucon.constants`; uncertainty propagates to results automatically

## [0.3.2] - 2026-04-03

### Fixed

- `decompose` structured mode: constraint solver replaces greedy placement heuristic
  - Correctly handles concentration problems where quantities must be placed in both numerator and denominator (e.g., 250 mL in numerator, 400 mg in denominator)
  - Brute-force 2^N solver over sign assignments with Occam tiebreaker (fewest denominators) and literal unit name matching against initial unit factors
  - Falls back to greedy scorer for N > 10 quantities
- `decompose` structured mode: auto-bridging of residual unit mismatches
  - After quantity placement, detects and inserts scale conversion factors (e.g., mcg → mg, min → h) so the factor chain produces the correct numeric result
  - Handles both cancelling pairs (mcg⁺¹ · mg⁻¹) and surviving unit mismatches (min⁻¹ vs h⁻¹)
- `decompose` structured mode: bare-count diagnostic for dimensionless quantities
  - When `ea` (dimensionless count) is provided but cannot fill a dimensional gap, returns an actionable error suggesting rate forms (e.g., `ea/d`, `ea/h`, `ea/min`)
  - Quantities expressed as rates (e.g., `3 ea/d`) are handled correctly by the constraint solver
- `decompose` query mode: cross-basis conversions (CGS ↔ SI) no longer rejected as dimension mismatches (e.g., `Pa*s → poise`, `dyne → N`, `m²/s → stokes`)
- Fuzzy unit suggestions crashed on unknown units due to stale `_UNIT_REGISTRY` import path (`ucon.units` → `ucon.resolver`)
- Inline `slug` test replaced with `smoot` to avoid collision with built-in `slug` unit added in ucon 1.1.x

### Changed

- Minimum `ucon` dependency bumped from `>=1.0.0` to `>=1.1.2`
- Decompose eval suite expanded: `1 GB to MB`, `1e-9 m to nm`, `1 TiB to GiB` now tested directly (requires ucon 1.1.2 resolver fixes and binary prefix support)
- Structured mode eval tests added to live server eval script

## [0.3.1] - 2026-04-01

### Fixed

- `DimConstraint` reference in `mcp.schema` (#9)

## [0.3.0] - 2026-03-31

### Added

- `decompose` MCP tool for deterministic unit conversion path construction
  - Query mode: simple "X to Y" conversions (e.g., "500 mL to L")
  - Structured mode: multi-step dimensional analysis with known quantities
  - Returns factor chains consumable by `compute`
- `expected_unit` parameter on `compute` tool for result validation
- Dimension mismatch diagnostics with corrective hints
- Eval script and Makefile target (`eval-decompose-live`)

## [0.2.1] - 2026-03-25

### Added

- Affine conversion support in `define_conversion` tool
  - `offset` parameter for affine conversions (e.g., temperature scales)
  - Conversion formula: `dst = factor * src + offset`
  - `offset` field added to `ConversionDefinitionResult`
  - Inline `custom_edges` also support `offset`
  - Backward compatible: `offset` defaults to `0.0` (linear behavior)

### Changed

- Minimum `ucon` dependency bumped from `>=0.9.3` to `>=0.10.1` (requires `EdgeDef.offset`)
- Test imports migrated from `ucon.mcp` to `ucon.tools.mcp` (aligns with ucon 0.10.x namespace)

## [0.2.0] - 2026-03-11

### Added

- Kind-of-Quantity (KOQ) tools for semantic disambiguation of dimensionally degenerate quantities:
  - `define_quantity_kind` — Register custom quantity kinds per session
  - `declare_computation` — Declare expected quantity kind before computing
  - `validate_result` — Validate result dimensions and detect semantic conflicts in reasoning
- Semantic conflict detection: `validate_result` analyzes reasoning text for keyword conflicts (e.g., mentioning "ΔH" when declared kind is "gibbs_energy")
- `KOQError` response type with structured error information and hints
- New response types: `QuantityKindDefinitionResult`, `ComputationDeclaration`, `ValidationResult`

### Fixed

- Dimension vector comparison now uses canonical SI order (M, L, T, I, Θ, N, J), fixing false mismatches from ordering differences

### Notes

- KOQ tools address the "unit-correct, KOQ-wrong" error class where LLMs compute correct numeric values with correct units but misidentify the physical quantity
- See [Kind-of-Quantity](https://docs.ucon.dev/architecture/kind-of-quantity) for conceptual background

## [0.1.0] - 2026-02-28

### Fixed

- Documentation: Updated install instructions to `ucon-tools[mcp]`
- Documentation: Updated import paths from `ucon.mcp` to `ucon.tools.mcp`

### Added

- MCP server for AI agent integration (extracted from ucon v0.9.3)
  - `convert` tool with dimensional validation
  - `compute` tool for multi-step factor-label calculations
  - `check_dimensions` compatibility tool
  - `list_units`, `list_scales`, `list_dimensions` discovery tools
  - `list_constants`, `define_constant` for physical constants
  - `define_unit`, `define_conversion`, `reset_session` for runtime extension
  - `list_formulas`, `call_formula` for dimensionally-typed calculations
- Error suggestions with fuzzy matching and confidence tiers
- Session state persistence across tool calls
- `ucon-mcp` CLI entry point
- Documentation for MCP server setup and usage

### Notes

- Requires `ucon>=0.9.4` (namespace package support)
- MCP functionality requires Python 3.10+ (FastMCP dependency)
- Install via `pip install ucon-tools[mcp]`

<!-- Links -->
[0.4.1]: https://github.com/withtwoemms/ucon-tools/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/withtwoemms/ucon-tools/compare/0.3.2...0.4.0
[0.3.2]: https://github.com/withtwoemms/ucon-tools/compare/0.3.1...0.3.2
[0.3.1]: https://github.com/withtwoemms/ucon-tools/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/withtwoemms/ucon-tools/compare/0.2.1...0.3.0
[0.2.1]: https://github.com/withtwoemms/ucon-tools/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/withtwoemms/ucon-tools/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/withtwoemms/ucon-tools/releases/tag/0.1.0

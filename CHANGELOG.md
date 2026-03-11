# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
[Unreleased]: https://github.com/withtwoemms/ucon-tools/compare/0.2.0...HEAD
[0.2.0]: https://github.com/withtwoemms/ucon-tools/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/withtwoemms/ucon-tools/releases/tag/0.1.0

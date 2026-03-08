# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `decompose` MCP tool for parsing natural language quantity expressions
- `solve` MCP tool for solving unit conversion problems with step-by-step reasoning
- NER module for quantity extraction from natural language (`ucon.tools.mcp.ner`)
  - `TrainingDataset` and `TrainingExample` for managing training data
  - `EntityLabel` and `NERConfig` for model configuration
  - `evaluate` and `evaluate_model` for model evaluation
  - `normalize_unit_string` for natural language unit normalization (e.g., "mg per dose" → "mg/ea")
  - `ComponentNormalizer` for learned component mappings
- Eval scripts and Makefile targets (`eval-decompose-live`, `eval-nl-problems`, `eval-ollama`)

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
[Unreleased]: https://github.com/withtwoemms/ucon-tools/compare/0.1.0...HEAD
[0.1.0]: https://github.com/withtwoemms/ucon-tools/releases/tag/0.1.0

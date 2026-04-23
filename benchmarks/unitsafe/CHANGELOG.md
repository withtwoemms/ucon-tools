# Changelog

All notable changes to the UnitSafe benchmark will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-04-23

### Fixed

- nursing-011: expected unit corrected from `mg/kg` to `mg/kg/dose` to match
  problem text ("Convert to mg/kg/dose")
- geo-023: expected unit corrected from `g/g` to `dimensionless` — the answer
  is a dimensionless ratio, not a unit-bearing quantity

## [0.1.0] - 2026-04-23

Initial public release.

### Added

- 500 metrological reasoning problems across 13 scientific domains
- 376 conversion problems (produce a correct numeric answer with units)
- 124 must-fail problems (62 dimension mismatch, 62 KOQ mismatch)
- 10 kind-of-quantity degeneracy clusters testing discrimination between
  physically distinct quantities with identical SI dimensions
- 4 difficulty tiers (single-step through physical reasoning)
- JSON Schema for problem validation (`schema/unitsafe_schema.json`)
- HuggingFace dataset card (`README.md`) with loading examples,
  evaluation protocol, and recommended metrics
- CI workflow for schema validation and HuggingFace publishing
- Benchmark runner (`run.py`) for evaluating models on UnitSafe problems
- Claude, Ollama, and Claude Code model backends via `backend:model`
  CLI spec
- Format-agnostic judge model for structured answer extraction
- Optional MCP tool-augmented evaluation (`--tools`, `--mcp-url`)
- Scoring: numerical tolerance, unit normalisation, refusal detection
- Filtering by difficulty tier, domain, KOQ cluster, and must-fail status
- Concurrent evaluation with configurable parallelism (`-j`)
- Summary metrics: overall/conversion/refusal accuracy, KOQ discrimination
  score, per-tier and per-cluster breakdowns

[Unreleased]: https://github.com/withtwoemms/ucon-tools/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/withtwoemms/ucon-tools/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/withtwoemms/ucon-tools/releases/tag/v0.1.0

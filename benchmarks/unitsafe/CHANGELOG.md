# Changelog

All notable changes to the UnitSafe benchmark will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-22

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

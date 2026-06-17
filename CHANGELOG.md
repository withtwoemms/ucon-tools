# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2026-06-16

Closes remaining gaps from the ucon v2.0 full-adoption plan and adopts
ucon v2.1.x capabilities (kind-threaded arithmetic, `FormulaRegistry`
preservation in `Graph.copy()`).

### Fixed

- **Empty-lattice bug in `DefaultSessionState`.** The base lattice was
  initialized as `KindLattice()` (empty) when no `base_lattice` argument
  was supplied. The 26 built-in kinds from `comprehensive.ucon.toml` were
  invisible to session operations. Now defaults to `active_kinds()`.
- **`define_quantity_kind` now handles built-in kind names gracefully.**
  Registering a kind whose name already exists in the built-in lattice
  (e.g. `gibbs_energy`) now succeeds by registering the
  `QuantityKindInfo` wrapper in the session dict without re-adding to the
  lattice.  Previously this raised an uncaught `NameCollision`.
- **`define_quantity_kind` duplicate check was dead code.** The
  `get_quantity_kind(name)` call omitted the `session_kinds` argument, so
  the built-in check always returned `None`. Now passes the session dict.

### Added

- **`FormulaRegistry` wired into session state.** `DefaultSessionState`
  now carries a `_base_registry` / `_formula_registry` pair with the same
  copy-on-first-access pattern as `KindLattice`. The `SessionState`
  protocol gains `get_formula_registry()`.
- **`formulas=` passed to `use_system()` in `dispatched()`.** The
  session's formula registry is now active during tool execution, enabling
  kind-threaded arithmetic to find `KindFormula` entries.
- **Structured error handling for v2.1.0 kind-arithmetic exceptions.**
  `KindMismatch`, `FormulaNotFound`, and `JoinRefused` are now caught in
  `convert()` and `call_formula()`, producing structured `ConversionError`
  / `FormulaError` responses with `error_type` and actionable hints.

### Changed

- **Dependency floor raised to `ucon>=2.1.1`.** Required for
  kind-threaded `Number` arithmetic, `FormulaNotFound` / `KindMismatch`
  exceptions, `Graph.copy()` formula-registry preservation, and the
  division-warning verb fix.
- **`using_conversion_graph` removed from `check_dimensions()`.** The
  ambient graph is now pinned by `@_dispatched_tool` via `use_system()`;
  the explicit `using_conversion_graph(graph)` call was redundant.
  Remaining `using_conversion_graph` usage is limited to inline-graph
  overrides for `custom_units` / `custom_edges` parameters.

## [0.6.0] - 2026-06-15

Compatibility work spanning ucon v2.0.0a1 through v2.0.0a3.

ucon v2.0.0a3 retired the `get_basis_graph()` context global from
`ucon.basis.graph`; the basis graph is now reachable only through the
active `UnitSystem` (`active_system().basis_graph`). The earlier a1/a2
wave removed `UnitSystem.from_globals()`, the `.conversions` alias, and
the `ucon._loader` module. The changes below adapt the MCP server and
its test suite to these removals; no change to the ucon-tools public API
(tool signatures, response shapes, and bundle semantics are unchanged).

### Fixed

- **`ProcessBase.from_globals()` migrated from `UnitSystem.from_globals()`
  to `active_system()`.** ucon v2.0.0a2 removed the `from_globals()`
  class method from `UnitSystem` as part of the v2.0 deprecation
  cleanup. Every MCP tool call funnels through `ProcessBase.from_globals()`
  at dispatcher construction time, so the entire test suite (506 tests)
  was raising `AttributeError: type object 'UnitSystem' has no attribute
  'from_globals'`. The call site now uses `active_system()`, the typed
  accessor that returns the `UnitSystem` from the active `ActiveContext`.
- **All `.conversions` reach-through sites migrated to `.conversion_graph`.**
  ucon v2.0.0a2 dropped the deprecated `conversions` alias on
  `UnitSystem`. Three source sites in `server.py` and one each in
  `value_types.py` docstring, `process_base.py` docstring, and
  `session.py` docstring were updated. Five test files were updated
  correspondingly.
- **`DefaultSessionState.get_unit_system()` no longer references the
  removed `ucon._loader` module.** As of ucon v1.12.0 the registries
  (`get_units`, `get_constants`) and the basis-graph helpers
  (`get_basis_graph`, `get_default_basis`) that this method previously
  reached for via deferred imports have been deleted. Every MCP tool
  call funnels through this method to build the effective
  `UnitSystem` for the request, so against ucon 1.12.x every tool was
  raising `ModuleNotFoundError: No module named 'ucon._loader'` at
  resolve time. The body now snapshots from the canonical entry point
  and overrides only the `conversion_graph` field with the
  session-owned graph. The five previous private-surface imports
  collapse to one public one.
- **`DefaultSessionState.get_unit_system()` migrated from
  `ucon.active()` to `ucon.active_system()` for ucon v2.0.0a1.** The
  v2.0 substrate work (`ActiveContext` per v2.0 §3.4) repointed the
  `_active` ContextVar at a frozen dataclass bundling
  `system + formulas + kinds + strict`, so the previous
  `live = active()` snapshot started raising
  `AttributeError: 'ActiveContext' object has no attribute 'basis'`
  at the first field access on every dispatched MCP tool — the entire
  test suite failed at `policy.resolve(...)`. The call site now uses
  `active_system()`, the typed accessor introduced in v2.0.0a1 that
  returns the `UnitSystem` field of the active context.

### Changed

- **Dependency floor bumped to `ucon>=2.0.1`** (from `>=2.0.0a1`).
  v2.0.1 fixes the gray/sievert/rad_dose/rem dimension assignment
  (`energy` → `specific_energy`), enabling kinded `Number` construction
  for `absorbed_dose` and `dose_equivalent` quantity kinds.
- **All test files migrated from `UnitSystem.from_globals()` to
  `active_system()`.** Six test modules updated: `test_dispatch.py`,
  `test_overlay.py`, `test_process_base.py`, `test_value_types.py`,
  `test_server_dispatch_wiring.py`. Each adds
  `from ucon.system import active_system` alongside the existing
  `UnitSystem` import.
- **`tests/ucon/tools/mcp/system/test_overlay.py::_system()` adapted
  to use `active_system()`.** The fixture previously relied on
  `UnitSystem.from_globals()` wrapped in `dataclasses.replace(...)` to
  produce identity-distinct values; it now wraps `active_system()`
  instead.
- **`process_base.from_globals` docstring** updated to describe the
  unit system as sourced from `active_system()` rather than
  `UnitSystem.from_globals()`.
- **`formulas` field renamed to `formula_tools`** on `CapabilityBundle`,
  `EffectiveCapabilities`, and `ProcessBase`. Clears the `formulas`
  name for the distinct `kind_formulas` concept. All test call sites
  updated.
- **`strict` field added to `TierConfig` and `EffectiveCapabilities`.**
  Controls source-unit resolution mode (`strict=True` enforces
  identity-based resolution via `UnitDefinitionMismatch`). The
  dispatcher stamps `eff.strict` from the tier config, and
  `dispatched()` passes it into `use_system()`.

### Added

- **`PackageResolver` protocol** (`ucon.tools.mcp.system.resolver`).
  Single-method interface (`load(package_id) → UnitSystem`) for
  resolving bundle-declared `unit_packages` into `UnitSystem`
  fragments. Overlay policies accept an optional resolver and compose
  bundle packages into the base system via `UnitSystem.extend_many()`.
  Replaces `_reject_bundle_unit_system_content()` with the more
  nuanced `_compose_bundle_system()`.
- **Session-level `KindLattice` management.** `DefaultSessionState`
  gains `get_kind_lattice()` with copy-on-first-access semantics.
  The lattice is copied from the base on first access, preventing
  cross-session contamination. `reset()` clears the session lattice.
  The `SessionState` protocol adds the method.
- **`KindLattice` wiring in `define_quantity_kind`.** User-defined
  quantity kinds now register a real `ucon.kinds.Kind` on the
  session's `KindLattice`, not just the MCP-level `QuantityKindInfo`
  wire type. The `dispatched()` context passes `kinds=` into
  `use_system()` so ucon's `ActiveContext` sees session kinds.
- **`restrict_system` tool.** Restricts the active system to named
  units or dimensions and returns a summary. Added to `CORE_BUNDLE`.
- **`diff_systems` tool.** Compares the session system against the
  process-base, reporting added/removed/redefined units, dimensions,
  conversions, and constants.
- **`check_compatibility` tool.** Tests whether the session system
  composes with the process-base without conflict.
- **`PRO_BUNDLE`** in the catalog, carrying `diff_systems` and
  `check_compatibility`.
- **`FREE` tier removed.** `PREVIEW` (leased, operator-curated, no
  mutation) covers the free offering at mcp.ucon.dev. The `FREE`
  `TierConfig` and its `TIER_CONFIGS` entry have been deleted.

## [0.5.3] - 2026-05-17

### Fixed

- **`validate_result` semantic warnings no longer false-positive on
  ordinary prose.** `check_semantic_conflicts` previously used plain
  substring containment against the `SEMANTIC_KEYWORDS` table, which
  caused two-character symbol keywords like `Ea` (activation_energy)
  to match inside any English word containing the letter pair "ea" —
  `headline`, `Read`, `each`, `treat`, `team`, `feature`. Any
  `reasoning` string passed to `validate_result` could trip a spurious
  "Reasoning mentions 'Ea'…" warning regardless of actual chemistry
  content. The matcher now uses lookaround-anchored regex
  (`(?<![A-Za-z]) … (?![A-Za-z])`, case-insensitive, pre-compiled at
  module load) so letter-mid-word hits are rejected while legitimate
  neighbours — punctuation, whitespace, digits, and unicode glyphs
  (`Δ`, `μ`, `τ`, `=`) — still anchor a match. The early-exit path
  ("declared kind is mentioned, suppress cross-warnings") uses the
  same word-boundary rule, so formula-context reasoning like
  `"Standard enthalpy of formation; ΔH ≈ ΔG at this T"` continues to
  silence cross-warnings under a declared `enthalpy` kind.

### Added

- `tests/ucon/tools/mcp/test_koq.py::TestValidateResult` — seven
  regression pins for the regex word-boundary contract:
  `test_headline_does_not_trip_Ea`, `test_Read_does_not_trip_Ea`,
  `test_each_does_not_trip_Ea` (false-positive class);
  `test_Ea_standalone_still_warns`, `test_enthalpy_word_still_warns`,
  `test_ENTHALPY_caps_case_flex_preserved` (true-positive +
  case-insensitivity preserved);
  `test_declared_kind_mention_silences_cross_warnings` (early-exit
  path).
- **Response capability hints across the `define_*` surface.** Three
  `define_*` tools now append a one-sentence capability hint to their
  success `message`, matching the convention already shipping on
  `define_unit` and `extend_basis`. The hint names the primary
  follow-on tool the caller should reach for next, shortening the
  discovery loop from "register, list, guess, retry" to "register,
  immediately call X":
  - `define_constant` → `"Use list_constants() to retrieve its
    metadata or compute() to apply its value in factor chains."`
  - `define_conversion` → `"Use convert() to apply this edge directly
    or as part of a multi-hop traversal."`
  - `define_quantity_kind` → `"Use declare_computation() to gate a
    calculation by this kind, then validate_result() to check the
    output."`
- **Regression pins** for every hint, including the two
  pre-existing reference patterns:
  - `test_server.py::TestSessionTools::test_define_unit_message_contains_capability_hint`
  - `test_server.py::TestAffineConversion::test_define_conversion_message_contains_capability_hint`
  - `test_constants.py::TestDefineConstant::test_define_message_contains_capability_hint`
  - `test_koq.py::TestDefineQuantityKind::test_define_message_contains_capability_hint`
  - `test_koq.py::TestExtendBasis::test_extend_basis_message_contains_capability_hint`

## [0.5.2] - 2026-05-15

### Changed

- **`_parse_dimension_to_vector` now delegates to ucon's core
  `parse_dimension`.** The MCP layer previously carried its own
  duplicate dimension grammar that only handled named dimensions, a
  hand-rolled "compound" sub-grammar, and pure vector-notation strings.
  Several bare-symbol forms the core parser already accepts were
  rejected at the MCP boundary: `M^1`, `M¹`, `L^2`, `L¹`, `L^3`, `L³`,
  and compound expressions mixing styles like `M*L/T^2`. The pure
  vector-notation fast path is preserved (and its guard tightened to
  exclude arithmetic operators), so canonical inputs like `M·L²·T⁻²`
  still short-circuit without re-parsing.
- **Fixes mis-parse of `M·L/T²`.** The vector-notation fast path
  previously swallowed `/` together with `·` and produced an incorrect
  signature with the denominator attached to the wrong factor. The
  tightened guard now routes such mixed-glyph compound expressions
  through the core parser, yielding the correct `M·L·T⁻²`.
- **Extended-basis dimensions resolve via try-each-basis.** When the
  default SI parse fails, the helper retries against each registered
  runtime basis in declaration order before returning `None`.

## [0.5.1] - 2026-05-15

Surfaces ucon 1.8.3's first-class `Unit.scalable` property through the
MCP tool surface. Prefix-on-non-scalable parses now produce a dedicated
diagnostic instead of the generic `unknown_unit`, `define_unit` accepts
the `scalable=` flag, and `convert` / `compute` / `decompose` gained
opt-in scalability metadata.

### Added

- **`define_unit(..., scalable: bool = True)`** — the session-level
  unit registration tool now exposes the `Unit.scalable` field added
  in ucon 1.8.3. Callers can register opt-out leaf units (e.g. count
  tokens, logarithmic units) at runtime; the resolver refuses prefix
  attachment to them at parse time.
- **`UnitDefinitionResult.scalable: bool`** (always-on). Every
  successful `define_unit` echoes the resolved scalability, so callers
  can read back the flag they set (or confirm the default).
- **`source_scalable` / `target_scalable` on `ConversionResult`,
  `ComputeResult`, `DecomposeResult`** (opt-in, default `None`).
  Populated when the tool call sets `include_scalability=True`. Bare
  `Unit` operands report the leaf's `scalable` value; composite
  `UnitProduct` operands report `None` to signal "scalability is a
  per-factor question at the leaf, not a single top-level answer."
- **`include_scalability: bool = False`** parameter on `convert`,
  `compute`, and `decompose`. Default-off keeps the steady-state
  response compact for the common case where the caller doesn't need
  this metadata.
- **`non_scalable_unit` error classification.** When the ucon
  resolver rejects a prefix decomposition because the base unit has
  opted out of scalability (`Unit.scalable=False`), the MCP
  `resolve_unit` choke point now produces a structured
  `ConversionError(error_type="non_scalable_unit", ...)` instead of
  the generic `unknown_unit` — the base symbol *is* recognized, only
  the prefix attachment is at fault. The error carries:
  - `got` — the attempted token (e.g. `"meach"`)
  - `expected` / `likely_fix` — the base unit name (e.g. `"each"`)
  - `hints` — two-line guidance explaining the `scalable=False` gate
    and naming the prefix to drop
  - `step` — preserved for multi-step `compute` factor chains so the
    offending factor index is unambiguous
- `ucon.tools.mcp.suggestions.build_non_scalable_error(exc, parameter,
  step=None)` — exported builder consumed by `resolve_unit`.
- `tests/ucon/tools/mcp/test_non_scalable_error.py` (16 tests) —
  pins the contract at three layers: the `build_non_scalable_error`
  builder shape, the `resolve_unit` classification (including
  regression guards for `flarble` → `unknown_unit` and `km` /
  bare `each` happy paths), and propagation through the public
  `convert` and `compute` tools with `step`-index preservation.
- `tests/ucon/tools/mcp/test_scalability_metadata.py` (11 tests) —
  pins the always-on `UnitDefinitionResult.scalable` contract and the
  opt-in gating semantics for `convert`, `compute`, and `decompose`
  (both query and structured modes), including the `UnitProduct → None`
  case for composite operands.

### Changed

- **Bumped minimum `ucon` to 1.8.3** (was 1.8.2). Picks up
  `Unit.scalable`, `NonScalableError`, the resolver-level prefix gate,
  TOML round-trip for the new field, and the computing-event family
  in the catalog (`flop`, `op`, `instruction`, `cycle`, `request`,
  `event`, all `scalable=True`).
- **Removed the consumer-side `SCALABLE_UNITS` allowlist.** Scalability
  is now read from `Unit.scalable` at the source — the MCP surface no
  longer duplicates the policy.
- **`resolve_unit` `except` ordering.** `NonScalableError` is caught
  before `UnknownUnitError` (it's a subclass), so the more specific
  diagnostic wins for prefix-on-non-scalable inputs without disturbing
  the existing `unknown_unit` path.
- **`ConversionError.error_type` documented value set.** Now
  `"unknown_unit"`, `"non_scalable_unit"`, `"dimension_mismatch"`,
  `"no_conversion_path"`, `"parse_error"`.

## [0.5.0] - 2026-05-14

Ships the v1.8 `UnitSystem` substrate through the MCP tool surface and
factors the server so a single binary can run as two operational
profiles under tier-driven dispatch. Every tool call now routes
through an explicit capability-resolution step before invocation.

### Added

- **Tiered capability framework (`ucon.tools.mcp.system`).** Two
  profiles ship: **STANDARD** (Type A — per-session mutable
  `UnitSystem`, default) and **PREVIEW** (Type B — operator-pinned
  read-only sessions with lease-bounded bundles). Both reduce to
  *process base + operator overlays + optional session overlay*
  composed through `OverlayPolicy.resolve(...)` and dispatched via
  `with use(...)` from ucon 1.8. New public value types:
  - `ProcessBase` — frozen
    `(unit_system, tools, formulas, catalog)`. Default constructor
    `ProcessBase.from_globals()` preserves v0.4.x behaviour.
  - `CapabilityBundle` — frozen
    `(name, version, provenance, unit_packages, constants, tools,
    formulas, expires_at, restrictions)`. `restrictions` is reserved
    for v2 and rejected at activation.
  - `EffectiveCapabilities` — frozen output of
    `OverlayPolicy.resolve(...)`.
  - `SessionOverlay` Protocol — per-session delta consumed by
    `OperatorOverlayPolicy` when `tier_config.mutation_allowed`.
  - `OverlayPolicy` Protocol with two concretes:
    `SessionOverlayPolicy` (STANDARD) and `OperatorOverlayPolicy`
    (PREVIEW).
  - `CallerIdentity` — `(tier, principal, roles=frozenset())`;
    `roles` is the v0.5.x deferral seam.
  - `TierConfig` — `(name, eligible_bundles, default_lease,
    max_lease, overlay_policy, mutation_allowed)`. Two values ship:
    `PREVIEW` and `STANDARD`.
  - `ActiveBundle` — activation wrapper
    `(bundle, tier, activated_at, expires_at, activator,
    lease_clamped_from)`.
  - `OperatorState` — single mutable surface; `RLock`-guarded.
    Methods: `activate`, `deactivate`, `deactivate_versioned`,
    `active_for`, `reap_expired`.
  - `BundleCatalog` Protocol, `StaticCatalog`, and `DEFAULT_CATALOG`
    containing exactly `CORE_BUNDLE`.
  - `Clock` Protocol, `SystemClock`, `FixedClock`.
  - `AuditSink` Protocol, `StderrJsonSink`, `AuditRecord`.
- **Operator entry points** — `activate_bundle(...)` and
  `deactivate_bundle(...)`. Both keyword-only, version-pinned,
  lease-clamped. `deactivate_bundle` is idempotent on a no-op path.
- **Dispatch wiring.** Every tool call resolves
  `EffectiveCapabilities` for the caller's tier, runs
  `operator_state.reap_expired(now)` once per request, gates with
  `CapabilityNotAvailable` if `request.tool not in eff.tools`, and
  executes under `with use(eff.unit_system)`. A `Dispatcher`
  constructed in the FastMCP lifespan hook is the single conduit for
  capability requests; the pattern is applied uniformly across
  `convert` and the remaining tool surface.
- **Startup hooks.** `--system` / `UCON_SYSTEM` selects a named
  process-base configuration (TOML); `--profile` / `UCON_PROFILE`
  selects `preview` vs `standard` as the default tier when no
  transport claim is available; `--tier-header` overrides the
  `X-Ucon-Tier` header name (placeholder until v0.5.x authenticated
  transport binding).
- **`extend_basis` registers a parent ↔ extended embedding pair**
  in the active `BasisGraph` via the new ucon
  `BasisTransform.append_components_embedding(parent, extended)`.
  Composing a unit defined on the extended basis (e.g. `USD`) with a
  unit on the parent (e.g. `s`) now lifts through `unify` instead of
  raising `BasisMismatch`. The reverse projection (extended →
  parent) is registered too and raises `LossyProjection` when a
  non-zero added component would be dropped — the correct
  unification behavior. Closes ucon#247 on the consumer side.
- `tests/ucon/tools/mcp/system/test_startup.py` — coverage for the
  new `--system` / `--profile` / `--tier-header` resolution paths.
- `TestCrossBasisArithmeticAfterExtend` in
  `tests/ucon/tools/mcp/test_extended_basis_dimensions.py` — three
  regressions for §8.1 (Phase 2.5 `compute` over `USD·s`,
  Phase 2.1 `declare_computation` over `USD/year`, SI-only
  no-regression).

### Changed

- **Bumped minimum `ucon` to 1.8.2** (was 1.7.0). Picks up the
  v1.8 `UnitSystem` value type, the
  `conversions` → `conversion_graph` API correction, and
  `BasisTransform.append_components_embedding` — all consumed by
  this release.
- **`using_graph` → `using_conversion_graph` migration** across the
  one import and 13 call sites in `ucon/tools/mcp/server.py`.
- **`SessionState.get_graph` / `set_graph` / `reset` route through
  `SessionOverlayPolicy`.** The Protocol surface and
  `DefaultSessionState` attribute names are unchanged; internals
  move.
- **Tool registry declarations** carry a
  `capabilities: tuple[str, ...]` field consumed by the dispatch
  "is the tool in `eff.tools`?" check.

### Fixed

- **Cross-basis composition after `extend_basis` no longer raises
  `BasisMismatch`.** The MCP tool surface now registers the parent
  ↔ extended embedding at basis-creation time, so the algebraic
  path through `multiply_via` / `divide_via` finds a clean
  projection in the active `BasisGraph`. Requires the
  corresponding ucon 1.8.2 helper.

### Compatibility

- Default startup with no flags is **STANDARD tier** with a process
  base constructed via `ProcessBase.from_globals()` — preserving
  v0.4.x observable behaviour for existing deployments.
- No tool signature gains a required parameter. Existing evals pass
  without consumer-side changes.

## [0.4.8] - 2026-05-10

### Changed

- **Bumped minimum `ucon` to 1.7.0.** Picks up the value-keyed
  `Dimension` algebra cache fix that resolves the Python 3.13 id-reuse
  hazard in `parse_dimension`.
- **Migrated off the deprecated `get_unit_by_name` symbol.** All eight
  call sites across `server.py`, `suggestions.py`, `formulas/medical.py`,
  `formulas/engineering.py`, `tests/.../test_builtin_formulas.py`, and
  `benchmarks/unitsafe/run.py` now import `parse_unit` from `ucon`.
  Behaviour is unchanged — `parse_unit` is the new name for the existing
  `get_unit_by_name` callable, which is scheduled for removal in
  ucon v2.0.

## [0.4.7] - 2026-05-06

### Added

- **`extend_basis` Phase 2 — session-scoped dimensions are real.** The
  session-aware dimension adapter introduced as non-functional groundwork
  in 0.4.6 is now wired through the tool surface. `extend_basis` graduates
  from informational-only to creating ucon `Basis` and `Dimension` objects
  that participate in the rest of the MCP toolchain for the lifetime of
  the session. Each `additional_components[*]` entry materializes a
  runtime `Dimension` that downstream tools can resolve by name or symbol.
  Components are surfaced through eight call sites that previously hard-
  coded the SI seven:
  - `define_unit` — accepts session dimensions; bypasses `UnitDef`
    materialization and constructs `Unit` directly when the dimension
    came from an extended basis
  - `list_units(dimension=...)` — filter validates against
    built-in ∪ session dimensions
  - `list_dimensions()` — now session-scoped; takes optional `Context`
    and includes dimensions created via `extend_basis`
  - `define_quantity_kind` — dimension parsing is session-aware, so KOQs
    can be declared over extended-basis dimensions
  - `list_quantity_kinds(dimension=...)` — filter is session-aware
  - `_parse_dimension_to_vector` and `_normalize_dimension_vector` —
    accept extended-basis symbols and append them after the SI canonical
    block in declaration order
  - `build_unknown_dimension_error` — suggestion pool includes session
    dimensions, so typos resolve against extended bases too
  - `_get_dimension_vector` — second pass over basis components beyond
    the SI seven so signatures render their full extended shape

- **Dimension parser papercuts closed.** `_parse_dimension_to_vector` now
  accepts forms previously rejected:
  - bare base symbols (`"M"`, `"L"`, and any extended symbol)
  - compound expressions (`"mass/time"`, `"mass*length/time^2"`)
  - dimensionless aliases (`""`, `"1"`, `"dimensionless"`)
  - `luminous_intensity` as a synonym for `luminosity`
  - `information` (mapped to `B`, the built-in SI extension)

- `tests/ucon/tools/mcp/test_extended_basis_dimensions.py` — 348-line
  fixture suite covering session-dimension registration, KOQ declaration
  over extended bases, suggestion-pool behaviour for unknown extended
  dimensions, dimension-parser acceptance of bare symbols and compound
  expressions, and signature rendering for components beyond the SI seven

### Changed

- `ExtendedBasisInfo` records carry `runtime_basis: Basis` and
  `runtime_dimensions: tuple[Dimension, ...]` fields, promoting the
  metadata record to a bridge between MCP-level descriptions and ucon-core
  basis/dimension objects. The `(Phase 1: informational only)` qualifier
  is removed from `extend_basis` response messages; the message now lists
  the new dimension names that became available.
- `_format_exponent(symbol, exp)` consolidates the unicode superscript
  branching that previously appeared inline in three call sites; symbol-
  agnostic so any extended-basis symbol renders correctly.
- ucon dependency lower bound: `ucon>=1.6.4a1` → `ucon>=1.6.5`.

### Fixed

- `_normalize_dimension_vector` previously hardcoded the SI symbol regex
  `[MLTIΘNJ]`, silently dropping extended-basis symbols when normalizing
  vector strings. The symbol set is now drawn from the session's
  registered bases with longer-symbol-first matching to disambiguate
  multi-character extended symbols from the SI seven.

## [0.4.6] - 2026-05-04

### Added

- [UnitSafe](https://huggingface.co/datasets/radiativity/UnitSafe) benchmark
  runner (`benchmarks/unitsafe/run.py`) for evaluating models on 500
  metrological reasoning problems
- UnitSafe section in README and MCP server guide with evaluation examples
- CHANGELOG gate in CI now scopes to sub-project changelogs
  (`benchmarks/unitsafe/CHANGELOG.md`) when only sub-project files change

### Added (non-functional)

- **Foundation for `extend_basis` Phase 2.** Internal session-aware dimension
  adapter layer that collapses eight scattered "what dimensions exist?" lookups
  into one extensible seam. No user-visible behavior change yet — the
  wire-through to `define_unit`, `list_units`, `list_dimensions`,
  `define_quantity_kind`, `list_quantity_kinds`,
  `_parse_dimension_to_vector`, `_normalize_dimension_vector`, and
  `build_unknown_dimension_error` is pending. Concretely:
  - `SessionState.get_session_dimensions()` protocol method + matching
    `DefaultSessionState` implementation, with a `_session_dimensions` dict
    cleared on `reset()`
  - `ExtendedBasisInfo.runtime_basis` and `runtime_dimensions` fields,
    promoting the metadata record to a bridge between MCP-level descriptions
    and ucon-core `Basis` / `Dimension` objects
  - `_all_known_dimensions(session)` helper — single source of truth for
    built-in ∪ session-created dimensions
  - `_format_exponent(symbol, exp)` helper — symbol-agnostic unicode
    superscript rendering (no longer hardcoded to SI symbols)
  - `_parse_compound_dimension(expr, known_vectors, extra_symbols)` helper —
    composes single-symbol bases through `/`, `*`, `^N` with extended-symbol
    canonical ordering
- `MANIFEST.in` to exclude benchmarks, docs, tests, scripts, and CI
  config from sdist
- `glama.json` metadata file for [Glama](https://glama.ai) MCP server registry

### Fixed

- replaces codecov badge in accordance with recent repo ownership handover
- **Typo suggestions deduplicate by target Unit.** `_suggest_units` previously
  returned multiple aliases of the same unit (e.g. `meter`, `metre`, `metres`)
  as separate fuzzy-match candidates. With ucon 1.6.4 adding plural aliases,
  the top matches for typos like `meater` were three synonyms of `meter` with
  near-identical similarity scores, defeating the 0.1 gap criterion that
  guards against ambiguous suggestions. The fuzzy-match pool is now widened
  from 3 to 5 raw candidates and collapsed by `Unit` identity (preserving
  the highest-scoring alias per cluster) before the gap and absolute-score
  thresholds run. No public API change; thresholds and scoring are unchanged.

## [0.4.5] - 2026-04-15

### Added

- **Formula output simplification.** `call_formula` now auto-simplifies
  compound output units to their named SI equivalents when the conversion
  factor is exactly 1.0 (e.g. `kg·m/s²` → `N`, `kg·m²/s²` → `J`,
  `kg·m²/s³` → `W`).

- **Cross-basis formula input tests.** Formulas now accept non-default-scale
  SI inputs (g, cm, mN) and — with ucon v1.6.3's cross-basis coercion —
  CGS-basis inputs (dyne, erg, poise) that are automatically coerced to SI
  before the formula body runs.

- **Left-to-right associativity tests** for the `convert` tool
  (`TestConvertLeftToRightAssociativity`, 5 tests):
  - `m/s*kg` parses as `(m/s)·kg`, not `m/(s·kg)`
  - `m/s*kg` ≠ `m/(s*kg)` (dimension mismatch)
  - `J/mol*K` ≠ `J/(mol*K)` — parentheses required for multi-term denominators
  - Chained division `mg/kg/day` identity
  - Parenthesized denominator `J/(mol*K)` identity

- **Constant unit integrity tests** (`TestConstantUnitIntegrity`, 3 tests):
  - `G` has unit `m³·kg⁻¹·s⁻²` (not `m³·kg⁻¹·s²`)
  - `R` has unit `J·mol⁻¹·K⁻¹` (not `J·mol⁻¹·K¹`)
  - `σ` has unit `W·m⁻²·K⁻⁴` (not `W·m⁻²·K⁴`)
  - Guards against parser associativity regressions in `ucon`

- **Decompose associativity roundtrip tests** (3 tests in tier 4):
  - `m/s*kg` → `m*kg/s` identity
  - `J/(mol*K)` identity with parenthesized denominator
  - `mg/kg/day` chained division identity

### Changed

- Minimum `ucon` dependency bumped from `>=1.6.0` to `>=1.6.3a1`
  - Required for cross-basis coercion in `@enforce_dimensions`

## [0.4.4] - 2026-04-13

### Fixed

- 12 constant-dependent formulas now call `.to_base()` on all dimensioned
  inputs before computation, eliminating scale-mismatch bugs when users
  provide non-base-SI units (km, kJ, cm³, etc.):
  - **Physics**: `gravitational_force`, `photon_energy`, `coulombs_law`,
    `projectile_range`, `schwarzschild_radius`
  - **Aerospace**: `orbital_velocity`, `escape_velocity`, `orbital_period`,
    `thrust`
  - **Chemistry**: `ideal_gas_pressure`, `gibbs_free_energy`
  - **Engineering**: `darcy_weisbach`, `kinetic_energy`
- `tsiolkovsky_delta_v` normalized from `.to(units.kilogram)` to `.to_base()`
  for consistency with the new pattern

### Notes

- Root cause: formulas extracted raw magnitudes from user-supplied units and
  combined them with physical constants defined in SI base units (G in
  m³/(kg·s²), ε₀ in F/m, etc.). Non-base inputs produced results off by
  the scale factor raised to the formula's power law.
- `Number.to_base()` has been available since ucon v1.5.0. It converts
  algebraically without consulting the ConversionGraph.
- Pure-ratio formulas (`molarity`, `dilution`, `stress`, `ohms_law_power`,
  `moles_from_mass`, SRE formulas) are unaffected — scale factors cancel.

## [0.4.3] - 2026-04-13

### Changed

- Minimum `ucon` dependency bumped from `>=1.5.0a1` to `>=1.6.0`
- Three formulas now consume `standard_gravity` (`gₙ`, exact) from
  `ucon.constants` instead of hardcoding `9.80665 m/s²`:
  - **Engineering**: `darcy_weisbach`
  - **Physics**: `projectile_range`
  - **Aerospace**: `tsiolkovsky_delta_v`
  - Numerically identical — `gₙ` is defined exact at 9.80665 m/s²
  - Aligns with the pattern used by other formulas that consume CODATA constants
    (`G`, `h`, `c`, `ε₀`)

## [0.4.2] - 2026-04-10

### Changed

- Minimum `ucon` dependency bumped from `>=1.1.2` to `>=1.5.0a1`
  - Required for 9 new physical constants added in ucon 1.5.0: `gₙ` (exact),
    `Eₕ`, `Ry`, `a₀`, `ℏ/Eₕ`, `mP`, `lP`, `tP`, `TP` (measured, CODATA 2022)
- Constant count assertions updated to reflect expanded constant catalog
  (8 exact, 3 derived, 15 measured = 26 total; was 7/3/7 = 17)

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
[Unreleased]: https://github.com/withtwoemms/ucon-tools/compare/0.6.0...HEAD
[0.6.0]: https://github.com/withtwoemms/ucon-tools/compare/0.5.3...0.6.0
[0.5.3]: https://github.com/withtwoemms/ucon-tools/compare/0.5.2...0.5.3
[0.5.2]: https://github.com/withtwoemms/ucon-tools/compare/0.5.1...0.5.2
[0.5.1]: https://github.com/withtwoemms/ucon-tools/compare/0.5.0...0.5.1
[0.5.0]: https://github.com/withtwoemms/ucon-tools/compare/0.4.8...0.5.0
[0.4.8]: https://github.com/withtwoemms/ucon-tools/compare/0.4.7...0.4.8
[0.4.7]: https://github.com/withtwoemms/ucon-tools/compare/0.4.6...0.4.7
[0.4.6]: https://github.com/withtwoemms/ucon-tools/compare/0.4.5...0.4.6
[0.4.5]: https://github.com/withtwoemms/ucon-tools/compare/0.4.4...0.4.5
[0.4.4]: https://github.com/withtwoemms/ucon-tools/compare/0.4.3...0.4.4
[0.4.3]: https://github.com/withtwoemms/ucon-tools/compare/0.4.2...0.4.3
[0.4.2]: https://github.com/withtwoemms/ucon-tools/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/withtwoemms/ucon-tools/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/withtwoemms/ucon-tools/compare/0.3.2...0.4.0
[0.3.2]: https://github.com/withtwoemms/ucon-tools/compare/0.3.1...0.3.2
[0.3.1]: https://github.com/withtwoemms/ucon-tools/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/withtwoemms/ucon-tools/compare/0.2.1...0.3.0
[0.2.1]: https://github.com/withtwoemms/ucon-tools/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/withtwoemms/ucon-tools/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/withtwoemms/ucon-tools/releases/tag/0.1.0

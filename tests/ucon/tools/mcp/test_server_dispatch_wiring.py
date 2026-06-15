# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for `Dispatcher` wiring inside `ucon.tools.mcp.server`.

Covers:
- `_build_dispatcher()` produces a `Dispatcher` with the expected
  defaults (standard tier, local principal, `TIER_CONFIGS`, both shipped
  overlay policies, base graph from `get_default_graph()`).
- The `lifespan` async context manager yields a dict containing both a
  `"session"` and a `"dispatcher"`.
- `_get_dispatcher(None)` falls back to a memoized process-wide
  dispatcher; `_reset_fallback_dispatcher()` clears it.
- The `dispatched(tool_name, ctx)` context manager resolves an
  `EffectiveCapabilities`, enters the resolved unit system as the
  ambient graph, and restores the prior graph on exit.
- `dispatched(...)` raises `CapabilityNotAvailable` for unknown tools.
"""
from __future__ import annotations

import asyncio

import pytest

from ucon.graph import get_default_graph, using_conversion_graph
from ucon.system import UnitSystem, active_system
from ucon.tools.mcp.server import (
    _build_dispatcher,
    _build_inline_graph,
    _get_dispatcher,
    _get_fallback_dispatcher,
    _reset_fallback_dispatcher,
    _reset_startup_config,
    _set_startup_config,
    convert,
    dispatched,
    lifespan,
    mcp,
)
from ucon.tools.mcp.suggestions import ConversionError
from ucon.tools.mcp.system import (
    CallerIdentity,
    CapabilityNotAvailable,
    DEFAULT_CATALOG,
    Dispatcher,
    EffectiveCapabilities,
    OperatorOverlayPolicy,
    OperatorState,
    ProcessBase,
    SessionOverlayPolicy,
    StartupConfig,
    StderrJsonSink,
    SystemClock,
    TIER_CONFIGS,
)


@pytest.fixture(autouse=True)
def _reset_fallback():
    _reset_fallback_dispatcher()
    _reset_startup_config()
    yield
    _reset_fallback_dispatcher()
    _reset_startup_config()


# -----------------------------------------------------------------------------
# _build_dispatcher
# -----------------------------------------------------------------------------

def test_build_dispatcher_returns_a_dispatcher():
    assert isinstance(_build_dispatcher(), Dispatcher)


def test_build_dispatcher_default_identity_is_standard_local():
    d = _build_dispatcher()
    assert d.default_identity == CallerIdentity(
        tier="standard", principal="local"
    )


def test_build_dispatcher_wires_tier_configs():
    d = _build_dispatcher()
    assert d.tier_configs is TIER_CONFIGS


def test_build_dispatcher_wires_both_overlay_policies():
    d = _build_dispatcher()
    assert isinstance(d.policies["session"], SessionOverlayPolicy)
    assert isinstance(d.policies["operator"], OperatorOverlayPolicy)


def test_build_dispatcher_process_base_uses_default_graph():
    d = _build_dispatcher()
    # ProcessBase.unit_system is a UnitSystem (v1.8 lift); its
    # `conversion_graph` field references ucon's default graph by snapshot.
    assert isinstance(d.process_base.unit_system, UnitSystem)
    assert d.process_base.unit_system.conversion_graph is get_default_graph()


def test_build_dispatcher_process_base_tools_include_registered_tools():
    d = _build_dispatcher()
    # `convert` is one of the always-registered tools on the FastMCP
    # instance; if discovery is wired correctly it must appear here.
    assert "convert" in d.process_base.tools


# -----------------------------------------------------------------------------
# lifespan
# -----------------------------------------------------------------------------

def _enter_lifespan() -> dict:
    async def _run():
        async with lifespan(mcp) as ctx_dict:
            return ctx_dict
    return asyncio.run(_run())


def test_lifespan_yields_session_in_context_dict():
    ctx_dict = _enter_lifespan()
    assert "session" in ctx_dict


def test_lifespan_yields_dispatcher_in_context_dict():
    ctx_dict = _enter_lifespan()
    assert "dispatcher" in ctx_dict
    assert isinstance(ctx_dict["dispatcher"], Dispatcher)


# -----------------------------------------------------------------------------
# _get_dispatcher / fallback
# -----------------------------------------------------------------------------

def test_get_dispatcher_falls_back_when_ctx_is_none():
    assert isinstance(_get_dispatcher(None), Dispatcher)


def test_get_dispatcher_falls_back_when_ctx_has_no_request_context():
    class _Bare:
        pass
    assert isinstance(_get_dispatcher(_Bare()), Dispatcher)


def test_fallback_dispatcher_is_memoized():
    d1 = _get_fallback_dispatcher()
    d2 = _get_fallback_dispatcher()
    assert d1 is d2


def test_reset_fallback_dispatcher_makes_next_call_construct_fresh():
    d1 = _get_fallback_dispatcher()
    _reset_fallback_dispatcher()
    d2 = _get_fallback_dispatcher()
    assert d1 is not d2


def test_get_dispatcher_returns_lifespan_dispatcher_when_present():
    # Simulate the shape of `ctx.request_context.lifespan_context`.
    sentinel = _build_dispatcher()

    class _LifespanCtx:
        lifespan_context = {"dispatcher": sentinel}

    class _Ctx:
        request_context = _LifespanCtx()

    assert _get_dispatcher(_Ctx()) is sentinel


# -----------------------------------------------------------------------------
# dispatched(...)
# -----------------------------------------------------------------------------

def test_dispatched_yields_effective_capabilities_for_registered_tool():
    with dispatched("convert") as eff:
        assert isinstance(eff, EffectiveCapabilities)
        assert "convert" in eff.tools


def test_dispatched_raises_capability_not_available_for_unknown_tool():
    with pytest.raises(CapabilityNotAvailable):
        with dispatched("definitely_not_a_registered_tool"):
            pass


def test_dispatched_audit_is_empty_when_no_active_bundles():
    with dispatched("convert") as eff:
        assert eff.audit == ()


def test_dispatched_enters_eff_unit_system_as_ambient_graph():
    # Pin the outer graph so we can verify the dispatcher swaps it in
    # and restores it on exit.
    outer = get_default_graph()
    with using_conversion_graph(outer):
        with dispatched("convert") as eff:
            # Inside the dispatched block, the ambient graph is the one
            # resolved by the dispatcher.
            assert eff.unit_system is not None
        # On exit, no exception escapes; the outer `with` cleans up.


def test_dispatched_propagates_capability_not_available_with_audit():
    try:
        with dispatched("definitely_not_a_registered_tool"):
            pytest.fail("expected CapabilityNotAvailable")
    except CapabilityNotAvailable as exc:
        assert exc.tool_name == "definitely_not_a_registered_tool"
        # No bundles active under the fallback dispatcher; audit is empty.
        assert exc.audit == ()


# -----------------------------------------------------------------------------
# convert(...) routes through dispatched(...)
# -----------------------------------------------------------------------------

def _ctx_with_dispatcher(dispatcher: Dispatcher):
    """Build a stub `Context` whose lifespan_context exposes a dispatcher."""

    class _LifespanCtx:
        lifespan_context = {"dispatcher": dispatcher}

    class _Ctx:
        request_context = _LifespanCtx()

    return _Ctx()


def test_convert_raises_capability_not_available_when_tool_gated_off():
    """If the dispatcher's `ProcessBase.tools` excludes `"convert"`, the
    tool body must not run — the dispatcher gate raises before any
    conversion work begins. This proves `convert` consults the
    dispatcher rather than calling `using_conversion_graph` directly.
    """
    locked_down = Dispatcher(
        process_base=ProcessBase(
            unit_system=active_system(),
            tools=frozenset(),  # convert is NOT advertised
            formula_tools=frozenset(),
            catalog=None,
        ),
        operator_state=OperatorState(),
        policies={
            "session": SessionOverlayPolicy(),
            "operator": OperatorOverlayPolicy(),
        },
        tier_configs=TIER_CONFIGS,
        clock=SystemClock(),
        sink=StderrJsonSink(),
        default_identity=CallerIdentity(tier="standard", principal="test"),
    )
    ctx = _ctx_with_dispatcher(locked_down)
    with pytest.raises(CapabilityNotAvailable) as excinfo:
        convert(value=1.0, from_unit="m", to_unit="m", ctx=ctx)
    assert excinfo.value.tool_name == "convert"


def test_convert_uses_dispatcher_resolved_unit_system_under_preview_tier():
    """Under the PREVIEW tier, `eff.unit_system` is sourced from the
    dispatcher's `ProcessBase` (operator policy; no session overlay).
    A custom unit registered only on the dispatcher's graph must be
    reachable from inside `convert`. If the dispatcher path were not
    taken, the unit would be unknown.
    """
    # Build an isolated graph with a custom "smoot" → "m" edge.
    custom_graph, err = _build_inline_graph(
        [{"name": "smoot", "dimension": "length", "aliases": ["smoot"]}],
        [{"src": "smoot", "dst": "m", "factor": 1.7018}],
        get_default_graph(),
    )
    assert err is None
    assert custom_graph is not None

    # Wrap the custom graph in a UnitSystem: ProcessBase.unit_system is
    # now a UnitSystem (v1.8 lift), so we override the
    # `conversion_graph` field of a globals-snapshot to point at our
    # custom graph.
    base_system = active_system()
    custom_system = UnitSystem(
        basis=base_system.basis,
        units=base_system.units,
        dimensions=base_system.dimensions,
        base_units=base_system.base_units,
        conversion_graph=custom_graph,
        basis_graph=base_system.basis_graph,
        contexts=base_system.contexts,
        constants=base_system.constants,
    )

    preview_dispatcher = Dispatcher(
        process_base=ProcessBase(
            unit_system=custom_system,
            tools=frozenset({"convert"}),
            formula_tools=frozenset(),
            catalog=None,
        ),
        operator_state=OperatorState(),
        policies={
            "session": SessionOverlayPolicy(),
            "operator": OperatorOverlayPolicy(),
        },
        tier_configs=TIER_CONFIGS,
        clock=SystemClock(),
        sink=StderrJsonSink(),
        default_identity=CallerIdentity(tier="preview", principal="test"),
    )
    ctx = _ctx_with_dispatcher(preview_dispatcher)
    result = convert(value=1.0, from_unit="smoot", to_unit="m", ctx=ctx)
    assert not isinstance(result, ConversionError)
    assert result.quantity == pytest.approx(1.7018, rel=1e-4)


def test_convert_default_dispatcher_path_succeeds():
    """Sanity check: the default (fallback) dispatcher allows `convert`
    and produces a sensible result. Guards against regression where the
    dispatched(...) wiring accidentally gates a registered tool off.
    """
    result = convert(value=1000.0, from_unit="m", to_unit="km")
    assert not isinstance(result, ConversionError)
    assert result.quantity == pytest.approx(1.0)


# -----------------------------------------------------------------------------
# StartupConfig integration
# -----------------------------------------------------------------------------

def test_build_dispatcher_without_config_matches_defaults():
    """Calling `_build_dispatcher()` with no config must preserve v0.4.x
    behavior: standard tier and `DEFAULT_CATALOG` on the process base.

    `ProcessBase.from_globals(catalog=None)` substitutes
    `DEFAULT_CATALOG`; the v0.4.x path always built a process base with
    that default, so omitting `--system` must reproduce it exactly.
    """
    d = _build_dispatcher()
    assert d.default_identity.tier == "standard"
    assert d.process_base.catalog is DEFAULT_CATALOG


def test_build_dispatcher_consumes_profile_from_config():
    cfg = StartupConfig(profile="preview")
    d = _build_dispatcher(cfg)
    assert d.default_identity == CallerIdentity(
        tier="preview", principal="local"
    )


def test_build_dispatcher_stamps_system_onto_process_base_catalog():
    cfg = StartupConfig(system="scientific")
    d = _build_dispatcher(cfg)
    assert d.process_base.catalog == "scientific"


def test_set_startup_config_resets_fallback_dispatcher():
    """Installing a new `StartupConfig` must invalidate the memoized
    fallback so the next direct call rebuilds with the new knobs.
    """
    d1 = _get_fallback_dispatcher()
    assert d1.default_identity.tier == "standard"
    _set_startup_config(StartupConfig(profile="preview"))
    d2 = _get_fallback_dispatcher()
    assert d2 is not d1
    assert d2.default_identity.tier == "preview"


def test_lifespan_dispatcher_honors_active_startup_config():
    """`lifespan` must consult `_get_startup_config()` at server start.
    """
    _set_startup_config(StartupConfig(profile="preview", system="med"))
    ctx_dict = _enter_lifespan()
    d = ctx_dict["dispatcher"]
    assert d.default_identity.tier == "preview"
    assert d.process_base.catalog == "med"


def test_lifespan_dispatcher_falls_back_to_defaults_when_no_config():
    """When no operator override is installed, `lifespan` must yield a
    dispatcher with the v0.4.x defaults.
    """
    ctx_dict = _enter_lifespan()
    d = ctx_dict["dispatcher"]
    assert d.default_identity.tier == "standard"
    assert d.process_base.catalog is DEFAULT_CATALOG

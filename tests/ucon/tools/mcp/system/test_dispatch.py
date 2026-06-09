# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for `ucon.tools.mcp.system.dispatch`.

Invariants under test (the *pure* dispatcher, not server-bound):

- Resolution flow: identity → tier_config → policy → reap → active_for
  → resolve → gate.
- `reap_expired` runs once per request; one `"expire"` AuditRecord per
  reaped bundle, with the original activator preserved.
- Gate: `tool not in eff.tools` raises `CapabilityNotAvailable` and
  carries `eff.audit`.
- Session-overlay drop: a tier with `mutation_allowed=False` ignores any
  caller-supplied overlay (PREVIEW behavior).
- Default identity fallback: `prepare(tool)` without `identity=` uses
  the constructor-injected default.
- Forward-compat: `CallerIdentity.roles` is not consulted (a
  non-default roles set produces identical behavior).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ucon.system import UnitSystem, active_system
from ucon.tools.mcp.system import (
    ActiveBundle,
    CapabilityBundle,
    CapabilityNotAvailable,
    CallerIdentity,
    CollectingSink,
    Dispatcher,
    FixedClock,
    OperatorOverlayPolicy,
    OperatorState,
    PREVIEW,
    ProcessBase,
    SessionOverlayPolicy,
    STANDARD,
    TIER_CONFIGS,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_dispatcher(
    *,
    process_base: ProcessBase | None = None,
    operator_state: OperatorState | None = None,
    clock: FixedClock | None = None,
    sink: CollectingSink | None = None,
    default_tier: str = "standard",
    default_principal: str = "test-principal",
    default_roles: frozenset[str] = frozenset(),
) -> Dispatcher:
    return Dispatcher(
        process_base=process_base or ProcessBase(
            unit_system=active_system(),
            tools=frozenset({"convert"}),
            formulas=frozenset({"bmi"}),
            catalog=None,
        ),
        operator_state=operator_state or OperatorState(),
        policies={
            "session": SessionOverlayPolicy(),
            "operator": OperatorOverlayPolicy(),
        },
        tier_configs=TIER_CONFIGS,
        clock=clock or FixedClock(T0),
        sink=sink or CollectingSink(),
        default_identity=CallerIdentity(
            tier=default_tier,
            principal=default_principal,
            roles=default_roles,
        ),
    )


def _bundle(
    name: str = "extras",
    version: str = "1.0",
    tools: frozenset[str] = frozenset(),
    formula_tools: frozenset[str] = frozenset(),
    provenance: str = "test",
) -> CapabilityBundle:
    return CapabilityBundle(
        name=name,
        version=version,
        provenance=provenance,
        tools=tools,
        formula_tools=formula_tools,
    )


def _active(
    bundle: CapabilityBundle,
    *,
    tier: str = "standard",
    activator: str = "alice",
    activated_at: datetime = T0,
    expires_at: datetime | None = None,
    lease_clamped_from: datetime | None = None,
) -> ActiveBundle:
    return ActiveBundle(
        bundle=bundle,
        tier=tier,
        activated_at=activated_at,
        expires_at=expires_at,
        activator=activator,
        lease_clamped_from=lease_clamped_from,
    )


# -----------------------------------------------------------------------------
# Happy path
# -----------------------------------------------------------------------------

def test_prepare_returns_effective_capabilities_for_base_tool():
    base_system = active_system()
    base = ProcessBase(
        unit_system=base_system,
        tools=frozenset({"convert"}),
        formula_tools=frozenset({"bmi"}),
        catalog=None,
    )
    dispatcher = _make_dispatcher(process_base=base)

    eff = dispatcher.prepare("convert")

    assert eff.unit_system is base_system
    assert eff.tools == frozenset({"convert"})
    assert eff.formula_tools == frozenset({"bmi"})
    assert eff.audit == ()


def test_prepare_uses_default_identity_when_none_provided():
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1", tools=frozenset({"t1"})),
        tier="standard",
    ))
    dispatcher = _make_dispatcher(operator_state=state)
    # Default tier is "standard"; gate accepts the bundle's tool.
    eff = dispatcher.prepare("t1")
    assert "t1" in eff.tools
    assert eff.audit == (("b1", "1.0"),)


def test_prepare_uses_explicit_identity_over_default():
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1", tools=frozenset({"t1"})),
        tier="preview",
    ))
    dispatcher = _make_dispatcher(
        operator_state=state,
        default_tier="standard",  # default would see no preview bundles
    )
    eff = dispatcher.prepare(
        "t1",
        identity=CallerIdentity(tier="preview", principal="bob"),
    )
    assert "t1" in eff.tools


# -----------------------------------------------------------------------------
# Gate: CapabilityNotAvailable
# -----------------------------------------------------------------------------

def test_prepare_raises_capability_not_available_for_unknown_tool():
    dispatcher = _make_dispatcher()
    with pytest.raises(CapabilityNotAvailable) as exc_info:
        dispatcher.prepare("nonexistent_tool")
    assert exc_info.value.tool_name == "nonexistent_tool"
    assert exc_info.value.audit == ()


def test_capability_not_available_carries_bundle_audit():
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1", version="1.0", tools=frozenset({"only_t1"})),
        tier="standard",
    ))
    state.activate(_active(
        _bundle(name="b2", version="2.0", tools=frozenset({"only_t2"})),
        tier="standard",
    ))
    dispatcher = _make_dispatcher(operator_state=state)
    with pytest.raises(CapabilityNotAvailable) as exc_info:
        dispatcher.prepare("not_in_any_bundle")
    # Audit reflects both active bundles.
    assert set(exc_info.value.audit) == {("b1", "1.0"), ("b2", "2.0")}


# -----------------------------------------------------------------------------
# Reaping + audit emission
# -----------------------------------------------------------------------------

def test_prepare_reaps_expired_bundles_and_emits_audit():
    sink = CollectingSink()
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1", tools=frozenset({"t1"}), provenance="prov-b1"),
        tier="standard",
        activator="alice",
        expires_at=T0 - timedelta(seconds=1),  # already expired
    ))
    dispatcher = _make_dispatcher(operator_state=state, sink=sink)

    # Calling prepare on a base tool still works; the bundle is reaped
    # before resolution so its tools are not in eff.
    eff = dispatcher.prepare("convert")
    assert "t1" not in eff.tools

    # Exactly one expire record, with the original activator preserved.
    assert len(sink.records) == 1
    record = sink.records[0]
    assert record.event == "expire"
    assert record.bundle_name == "b1"
    assert record.activator == "alice"
    assert record.bundle_provenance == "prov-b1"
    assert record.timestamp == T0


def test_prepare_reaps_only_once_per_call():
    sink = CollectingSink()
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1"),
        tier="standard",
        expires_at=T0 - timedelta(seconds=1),
    ))
    dispatcher = _make_dispatcher(operator_state=state, sink=sink)
    dispatcher.prepare("convert")
    # Second prepare: the bundle has already been reaped; no new record.
    dispatcher.prepare("convert")
    assert len(sink.records) == 1


def test_prepare_does_not_emit_expire_for_unexpired_bundles():
    sink = CollectingSink()
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1", tools=frozenset({"t1"})),
        tier="standard",
        expires_at=T0 + timedelta(hours=1),  # in the future
    ))
    dispatcher = _make_dispatcher(operator_state=state, sink=sink)
    eff = dispatcher.prepare("t1")
    assert "t1" in eff.tools
    assert sink.records == []


def test_prepare_does_not_emit_expire_for_indefinite_bundles():
    sink = CollectingSink()
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1", tools=frozenset({"t1"})),
        tier="standard",
        expires_at=None,
    ))
    dispatcher = _make_dispatcher(operator_state=state, sink=sink)
    dispatcher.prepare("t1")
    assert sink.records == []


# -----------------------------------------------------------------------------
# Composition with active bundles
# -----------------------------------------------------------------------------

def test_active_bundle_tools_appear_in_effective_tools():
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b1", tools=frozenset({"t1", "t2"})),
        tier="standard",
    ))
    dispatcher = _make_dispatcher(operator_state=state)
    eff = dispatcher.prepare("t1")
    assert eff.tools >= {"convert", "t1", "t2"}


def test_active_for_filters_by_tier():
    state = OperatorState()
    state.activate(_active(
        _bundle(name="b_std", tools=frozenset({"t_std"})),
        tier="standard",
    ))
    state.activate(_active(
        _bundle(name="b_pre", tools=frozenset({"t_pre"})),
        tier="preview",
    ))
    dispatcher = _make_dispatcher(operator_state=state)
    # Standard sees only its own bundle's tool.
    eff = dispatcher.prepare("t_std")
    assert "t_std" in eff.tools
    assert "t_pre" not in eff.tools


# -----------------------------------------------------------------------------
# Session-overlay handling per tier
# -----------------------------------------------------------------------------

class _StubOverlay:
    def __init__(self, unit_system, empty=False):
        self._unit_system = unit_system
        self._empty = empty

    def is_empty(self):
        return self._empty

    def get_unit_system(self):
        return self._unit_system


def test_standard_tier_consults_session_overlay():
    overlay_system = active_system()
    overlay = _StubOverlay(overlay_system, empty=False)
    dispatcher = _make_dispatcher(default_tier="standard")
    eff = dispatcher.prepare("convert", session_overlay=overlay)
    assert eff.unit_system is overlay_system


def test_preview_tier_drops_caller_session_overlay():
    # PREVIEW.mutation_allowed is False, so any caller-supplied overlay
    # must be ignored (rather than reach OperatorOverlayPolicy and raise
    # SessionMutationRejected).
    process_system = active_system()
    base = ProcessBase(
        unit_system=process_system,
        tools=frozenset({"convert"}),
        formula_tools=frozenset(),
        catalog=None,
    )
    dispatcher = _make_dispatcher(
        process_base=base,
        default_tier="preview",
    )
    overlay = _StubOverlay(active_system(), empty=False)
    eff = dispatcher.prepare("convert", session_overlay=overlay)
    # Effective unit_system is the process base, not the overlay.
    assert eff.unit_system is process_system


# -----------------------------------------------------------------------------
# Forward-compat: roles are not consulted by dispatch
# -----------------------------------------------------------------------------

def test_dispatch_does_not_consult_roles():
    """`CallerIdentity.roles` is reserved for future role-based
    dispatch; current read sites use `tier` exclusively. A non-default
    roles set must produce identical dispatch behavior to an empty
    roles set."""
    sink_a = CollectingSink()
    sink_b = CollectingSink()
    dispatcher_a = _make_dispatcher(sink=sink_a, default_roles=frozenset())
    dispatcher_b = _make_dispatcher(
        sink=sink_b, default_roles=frozenset({"any-role"})
    )

    eff_a = dispatcher_a.prepare("convert")
    eff_b = dispatcher_b.prepare("convert")

    assert eff_a == eff_b
    assert sink_a.records == sink_b.records


# -----------------------------------------------------------------------------
# Configuration errors
# -----------------------------------------------------------------------------

def test_unknown_tier_raises_key_error():
    dispatcher = _make_dispatcher(default_tier="ghost")
    with pytest.raises(KeyError):
        dispatcher.prepare("convert")


def test_unknown_overlay_policy_raises_key_error():
    # Construct a dispatcher whose tier names a missing policy.
    dispatcher = Dispatcher(
        process_base=ProcessBase(
            unit_system=active_system(),
            tools=frozenset({"convert"}),
            formulas=frozenset(),
            catalog=None,
        ),
        operator_state=OperatorState(),
        policies={"session": SessionOverlayPolicy()},  # no "operator"
        tier_configs=TIER_CONFIGS,
        clock=FixedClock(T0),
        sink=CollectingSink(),
        default_identity=CallerIdentity(tier="preview", principal="x"),
    )
    with pytest.raises(KeyError):
        dispatcher.prepare("convert")

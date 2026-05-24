# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for `ucon.tools.mcp.system.overlay`.

Invariants under test:

- `SessionOverlayPolicy` produces a mutable session overlay rooted on
  the process base; mutations do not leak across sessions.
- `OperatorOverlayPolicy` rejects a non-empty `session_overlay` parameter
  with `SessionMutationRejected`.
- Tools/formulas compose as pointwise unions across base and active
  bundles; audit is a tuple of `(name, version)` per active bundle.
- Carve-out: non-empty `bundle.unit_packages` or `bundle.constants`
  raises `NotImplementedError` at resolve time (composition not yet
  implemented).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from ucon.system import UnitSystem
from ucon.tools.mcp.session import DefaultSessionState
from ucon.tools.mcp.system import (
    CapabilityBundle,
    EffectiveCapabilities,
    OperatorOverlayPolicy,
    OverlayPolicy,
    SessionMutationRejected,
    SessionOverlay,
    SessionOverlayPolicy,
    SessionStateOverlay,
)


# -----------------------------------------------------------------------------
# Test doubles
# -----------------------------------------------------------------------------

def _system() -> UnitSystem:
    """Build a fresh ``UnitSystem`` for use as a `base` sentinel.

    Identity matters in these tests (we assert ``eff.unit_system is X``).
    As of ucon v1.12, ``UnitSystem.from_globals()`` returns the cached
    active system (same identity across calls), so we ``replace(...)``
    it to mint a distinct value per invocation while preserving content.
    """
    return replace(UnitSystem.from_globals())


class _StubOverlay:
    """Minimal `SessionOverlay` test double."""

    def __init__(
        self,
        unit_system: UnitSystem | None = None,
        empty: bool = True,
    ) -> None:
        self._unit_system = unit_system if unit_system is not None else _system()
        self._empty = empty

    def is_empty(self) -> bool:
        return self._empty

    def get_unit_system(self) -> UnitSystem:
        return self._unit_system


def _bundle(
    name: str = "core",
    version: str = "1.0",
    tools: frozenset[str] = frozenset(),
    formulas: frozenset[str] = frozenset(),
) -> CapabilityBundle:
    return CapabilityBundle(
        name=name,
        version=version,
        tools=tools,
        formulas=formulas,
    )


# -----------------------------------------------------------------------------
# Protocol conformance
# -----------------------------------------------------------------------------

def test_session_overlay_policy_satisfies_overlay_policy_protocol():
    assert isinstance(SessionOverlayPolicy(), OverlayPolicy)


def test_operator_overlay_policy_satisfies_overlay_policy_protocol():
    assert isinstance(OperatorOverlayPolicy(), OverlayPolicy)


def test_stub_overlay_satisfies_session_overlay_protocol():
    assert isinstance(_StubOverlay(), SessionOverlay)


def test_session_state_overlay_satisfies_session_overlay_protocol():
    state = DefaultSessionState()
    overlay = SessionStateOverlay(session=state)
    assert isinstance(overlay, SessionOverlay)


# -----------------------------------------------------------------------------
# SessionOverlayPolicy.resolve
# -----------------------------------------------------------------------------

def test_session_policy_uses_base_when_no_overlay():
    base = _system()
    policy = SessionOverlayPolicy()
    eff = policy.resolve(
        base=base,
        base_tools=frozenset({"convert"}),
        base_formulas=frozenset({"bmi"}),
        active_bundles=(),
        session_overlay=None,
    )
    assert eff.unit_system is base
    assert eff.tools == frozenset({"convert"})
    assert eff.formulas == frozenset({"bmi"})
    assert eff.audit == ()


def test_session_policy_uses_overlay_unit_system_when_provided():
    base = _system()
    overlay_system = _system()
    overlay = _StubOverlay(unit_system=overlay_system, empty=False)
    policy = SessionOverlayPolicy()
    eff = policy.resolve(
        base=base,
        base_tools=frozenset(),
        base_formulas=frozenset(),
        active_bundles=(),
        session_overlay=overlay,
    )
    assert eff.unit_system is overlay_system


def test_session_policy_unions_tools_and_formulas_across_bundles():
    policy = SessionOverlayPolicy()
    b1 = _bundle(
        name="b1",
        tools=frozenset({"t1"}),
        formulas=frozenset({"f1"}),
    )
    b2 = _bundle(
        name="b2",
        tools=frozenset({"t2"}),
        formulas=frozenset({"f2"}),
    )
    eff = policy.resolve(
        base=_system(),
        base_tools=frozenset({"convert"}),
        base_formulas=frozenset({"bmi"}),
        active_bundles=(b1, b2),
        session_overlay=None,
    )
    assert eff.tools == frozenset({"convert", "t1", "t2"})
    assert eff.formulas == frozenset({"bmi", "f1", "f2"})


def test_session_policy_audit_preserves_bundle_order():
    policy = SessionOverlayPolicy()
    b1 = _bundle(name="b1", version="1.0")
    b2 = _bundle(name="b2", version="2.0")
    eff = policy.resolve(
        base=_system(),
        base_tools=frozenset(),
        base_formulas=frozenset(),
        active_bundles=(b1, b2),
        session_overlay=None,
    )
    assert eff.audit == (("b1", "1.0"), ("b2", "2.0"))


def test_session_policy_does_not_leak_across_independent_overlays():
    base = _system()
    policy = SessionOverlayPolicy()
    a = _StubOverlay(empty=False)
    b = _StubOverlay(empty=False)
    eff_a = policy.resolve(
        base=base, base_tools=frozenset(), base_formulas=frozenset(),
        active_bundles=(), session_overlay=a,
    )
    eff_b = policy.resolve(
        base=base, base_tools=frozenset(), base_formulas=frozenset(),
        active_bundles=(), session_overlay=b,
    )
    assert eff_a.unit_system is not eff_b.unit_system


# -----------------------------------------------------------------------------
# OperatorOverlayPolicy.resolve
# -----------------------------------------------------------------------------

def test_operator_policy_accepts_none_session_overlay():
    base = _system()
    policy = OperatorOverlayPolicy()
    eff = policy.resolve(
        base=base,
        base_tools=frozenset({"convert"}),
        base_formulas=frozenset(),
        active_bundles=(),
        session_overlay=None,
    )
    assert eff.unit_system is base
    assert eff.tools == frozenset({"convert"})


def test_operator_policy_accepts_empty_session_overlay():
    base = _system()
    policy = OperatorOverlayPolicy()
    eff = policy.resolve(
        base=base,
        base_tools=frozenset(),
        base_formulas=frozenset(),
        active_bundles=(),
        session_overlay=_StubOverlay(empty=True),
    )
    # Operator policy ignores the overlay; unit_system is the base.
    assert eff.unit_system is base


def test_operator_policy_rejects_non_empty_session_overlay():
    policy = OperatorOverlayPolicy()
    with pytest.raises(SessionMutationRejected):
        policy.resolve(
            base=_system(),
            base_tools=frozenset(),
            base_formulas=frozenset(),
            active_bundles=(),
            session_overlay=_StubOverlay(empty=False),
        )


def test_operator_policy_unions_tools_and_formulas_across_bundles():
    policy = OperatorOverlayPolicy()
    b1 = _bundle(tools=frozenset({"t1"}), formulas=frozenset({"f1"}))
    eff = policy.resolve(
        base=_system(),
        base_tools=frozenset({"convert"}),
        base_formulas=frozenset({"bmi"}),
        active_bundles=(b1,),
        session_overlay=None,
    )
    assert eff.tools == frozenset({"convert", "t1"})
    assert eff.formulas == frozenset({"bmi", "f1"})


def test_operator_policy_audit_includes_each_active_bundle():
    policy = OperatorOverlayPolicy()
    b1 = _bundle(name="b1", version="1.0")
    b2 = _bundle(name="b2", version="2.0")
    eff = policy.resolve(
        base=_system(),
        base_tools=frozenset(),
        base_formulas=frozenset(),
        active_bundles=(b1, b2),
        session_overlay=None,
    )
    assert eff.audit == (("b1", "1.0"), ("b2", "2.0"))


# -----------------------------------------------------------------------------
# Carve-out: bundle unit-system content rejected
# -----------------------------------------------------------------------------

def test_bundle_with_unit_packages_rejected_by_session_policy():
    bundle = CapabilityBundle(
        name="future",
        version="1.0",
        unit_packages=("ucon-pkg-currency",),
    )
    policy = SessionOverlayPolicy()
    with pytest.raises(NotImplementedError):
        policy.resolve(
            base=_system(),
            base_tools=frozenset(),
            base_formulas=frozenset(),
            active_bundles=(bundle,),
            session_overlay=None,
        )


def test_bundle_with_constants_rejected_by_operator_policy():
    # The policy only inspects truthiness of `constants`; a placeholder
    # avoids coupling this test to the real `Constant` constructor.
    bundle = CapabilityBundle(
        name="future",
        version="1.0",
        constants={"my_const": object()},
    )
    policy = OperatorOverlayPolicy()
    with pytest.raises(NotImplementedError):
        policy.resolve(
            base=_system(),
            base_tools=frozenset(),
            base_formulas=frozenset(),
            active_bundles=(bundle,),
            session_overlay=None,
        )


# -----------------------------------------------------------------------------
# SessionStateOverlay adapter
# -----------------------------------------------------------------------------

def test_session_state_overlay_empty_for_fresh_session():
    state = DefaultSessionState()
    overlay = SessionStateOverlay(session=state)
    assert overlay.is_empty() is True


def test_session_state_overlay_non_empty_when_quantity_kind_registered():
    from ucon.tools.mcp.koq import QuantityKindInfo

    state = DefaultSessionState()
    state.register_quantity_kind(
        QuantityKindInfo(
            name="custom",
            dimension_name="length",
            dimension_vector="L",
            description="",
            aliases=(),
            category="session",
            disambiguation_hints=(),
        )
    )
    overlay = SessionStateOverlay(session=state)
    assert overlay.is_empty() is False


def test_session_state_overlay_get_unit_system_returns_session_graph():
    state = DefaultSessionState()
    overlay = SessionStateOverlay(session=state)
    # The overlay now returns a UnitSystem; its `conversions` field
    # is the session's mutable graph by reference.
    assert overlay.get_unit_system().conversions is state.get_graph()


def test_session_state_overlay_wired_through_session_policy():
    state = DefaultSessionState()
    overlay = SessionStateOverlay(session=state)
    base = _system()
    policy = SessionOverlayPolicy()
    eff = policy.resolve(
        base=base,
        base_tools=frozenset({"convert"}),
        base_formulas=frozenset(),
        active_bundles=(),
        session_overlay=overlay,
    )
    # Effective unit_system carries the session's mutable graph, not
    # the process base.
    assert eff.unit_system.conversions is state.get_graph()
    assert isinstance(eff, EffectiveCapabilities)

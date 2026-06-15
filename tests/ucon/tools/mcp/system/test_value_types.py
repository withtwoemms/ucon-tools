# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for the value types in `ucon.tools.mcp.system.value_types`.

Covers: `CapabilityBundle`, `ActiveBundle`, `EffectiveCapabilities`,
`TierConfig`, `CallerIdentity`, and the `PREVIEW` / `STANDARD` instances.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from ucon.system import UnitSystem, active_system
from ucon.tools.mcp.system import (
    ActiveBundle,
    CallerIdentity,
    CapabilityBundle,
    EffectiveCapabilities,
    PREVIEW,
    STANDARD,
    TIER_CONFIGS,
    TierConfig,
)


# -----------------------------------------------------------------------------
# CapabilityBundle
# -----------------------------------------------------------------------------

def test_capability_bundle_minimal_construction():
    b = CapabilityBundle(name="core", version="1.0")
    assert b.name == "core"
    assert b.version == "1.0"
    assert b.provenance == ""
    assert b.unit_packages == ()
    assert b.constants == {}
    assert b.tools == frozenset()
    assert b.formula_tools == frozenset()
    assert b.expires_at is None
    assert b.restrictions == ()


def test_capability_bundle_is_frozen():
    b = CapabilityBundle(name="core", version="1.0")
    with pytest.raises(FrozenInstanceError):
        b.name = "other"  # type: ignore[misc]


def test_capability_bundle_equality():
    a = CapabilityBundle(name="x", version="1", tools=frozenset({"a", "b"}))
    b = CapabilityBundle(name="x", version="1", tools=frozenset({"b", "a"}))
    assert a == b


def test_capability_bundle_tools_are_frozenset():
    b = CapabilityBundle(name="x", version="1", tools=frozenset({"a"}))
    assert isinstance(b.tools, frozenset)


def test_capability_bundle_formulas_are_frozenset():
    b = CapabilityBundle(name="x", version="1", formula_tools=frozenset({"bmi"}))
    assert isinstance(b.formula_tools, frozenset)


def test_capability_bundle_restrictions_default_empty_tuple():
    b = CapabilityBundle(name="x", version="1")
    assert b.restrictions == ()


def test_capability_bundle_restrictions_preserved_as_tuple():
    b = CapabilityBundle(name="x", version="1", restrictions=("a", "b"))
    assert b.restrictions == ("a", "b")


# -----------------------------------------------------------------------------
# ActiveBundle
# -----------------------------------------------------------------------------

def test_active_bundle_construction():
    bundle = CapabilityBundle(name="core", version="1.0")
    now = datetime(2026, 5, 13, tzinfo=timezone.utc)
    ab = ActiveBundle(
        bundle=bundle,
        tier="preview",
        activated_at=now,
        expires_at=now + timedelta(hours=24),
        activator="ops/test",
    )
    assert ab.bundle is bundle
    assert ab.tier == "preview"
    assert ab.activated_at == now
    assert ab.expires_at == now + timedelta(hours=24)
    assert ab.activator == "ops/test"
    assert ab.lease_clamped_from is None


def test_active_bundle_is_frozen():
    bundle = CapabilityBundle(name="core", version="1.0")
    now = datetime(2026, 5, 13, tzinfo=timezone.utc)
    ab = ActiveBundle(
        bundle=bundle, tier="preview", activated_at=now,
        expires_at=now, activator="ops",
    )
    with pytest.raises(FrozenInstanceError):
        ab.tier = "standard"  # type: ignore[misc]


def test_active_bundle_records_lease_clamping():
    bundle = CapabilityBundle(name="core", version="1.0")
    now = datetime(2026, 5, 13, tzinfo=timezone.utc)
    requested = now + timedelta(days=30)
    granted = now + timedelta(days=7)
    ab = ActiveBundle(
        bundle=bundle, tier="preview", activated_at=now,
        expires_at=granted, activator="ops",
        lease_clamped_from=requested,
    )
    assert ab.expires_at == granted
    assert ab.lease_clamped_from == requested


# -----------------------------------------------------------------------------
# EffectiveCapabilities
# -----------------------------------------------------------------------------

def test_effective_capabilities_construction():
    sys = active_system()
    eff = EffectiveCapabilities(
        unit_system=sys,
        tools=frozenset({"convert"}),
        formula_tools=frozenset({"bmi"}),
        audit=(("core", "1.0"),),
    )
    assert eff.unit_system is sys
    assert eff.tools == frozenset({"convert"})
    assert eff.formula_tools == frozenset({"bmi"})
    assert eff.audit == (("core", "1.0"),)


def test_effective_capabilities_is_frozen():
    sys = active_system()
    eff = EffectiveCapabilities(unit_system=sys)
    with pytest.raises(FrozenInstanceError):
        eff.tools = frozenset()  # type: ignore[misc]


def test_effective_capabilities_defaults():
    sys = active_system()
    eff = EffectiveCapabilities(unit_system=sys)
    assert eff.tools == frozenset()
    assert eff.formula_tools == frozenset()
    assert eff.audit == ()


# -----------------------------------------------------------------------------
# TierConfig + PREVIEW + STANDARD
# -----------------------------------------------------------------------------

def test_preview_tier_config_values():
    assert PREVIEW.name == "preview"
    assert PREVIEW.eligible_bundles == frozenset({"core"})
    assert PREVIEW.default_lease == timedelta(hours=24)
    assert PREVIEW.max_lease == timedelta(days=7)
    assert PREVIEW.overlay_policy == "operator"
    assert PREVIEW.mutation_allowed is False


def test_standard_tier_config_values():
    assert STANDARD.name == "standard"
    assert STANDARD.eligible_bundles is None
    assert STANDARD.default_lease is None
    assert STANDARD.max_lease is None
    assert STANDARD.overlay_policy == "session"
    assert STANDARD.mutation_allowed is True


def test_tier_configs_map_has_both_tiers():
    assert TIER_CONFIGS["preview"] is PREVIEW
    assert TIER_CONFIGS["standard"] is STANDARD
    assert set(TIER_CONFIGS.keys()) == {"preview", "standard"}


def test_tier_config_is_frozen():
    with pytest.raises(FrozenInstanceError):
        PREVIEW.mutation_allowed = True  # type: ignore[misc]


# -----------------------------------------------------------------------------
# CallerIdentity
# -----------------------------------------------------------------------------

def test_caller_identity_minimal_construction():
    ci = CallerIdentity(tier="preview", principal="user-123")
    assert ci.tier == "preview"
    assert ci.principal == "user-123"
    assert ci.roles == frozenset()


def test_caller_identity_with_roles():
    ci = CallerIdentity(
        tier="standard",
        principal="user-456",
        roles=frozenset({"admin", "operator"}),
    )
    assert ci.roles == frozenset({"admin", "operator"})


def test_caller_identity_is_frozen():
    ci = CallerIdentity(tier="preview", principal="x")
    with pytest.raises(FrozenInstanceError):
        ci.principal = "y"  # type: ignore[misc]


def test_roles_participate_in_value_equality():
    """The `roles` field participates in `CallerIdentity` value
    equality: two identities with the same `(tier, principal)` are
    equal only when `roles` also match. Whether the dispatcher consults
    `roles` is a separate concern asserted at the dispatch layer.
    """
    a = CallerIdentity(tier="preview", principal="x")
    b = CallerIdentity(tier="preview", principal="x", roles=frozenset({"any"}))
    # Value-type equality respects all fields; roles differ → not equal.
    assert a != b
    # But omitting roles defaults to frozenset() — the dispatch deferral
    # is enforced at the dispatch site, not via type-level equality.
    a2 = CallerIdentity(tier="preview", principal="x")
    assert a == a2

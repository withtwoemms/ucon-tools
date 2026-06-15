# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for `ucon.tools.mcp.system.operator` activation entry points.

Invariants under test:

- **PREVIEW.** `activate_bundle("core", "1.0", requested_lease=None)` →
  `expires_at = now + 24h`. `requested_lease=14d` → clamped to 7d with
  `lease_clamped_from = now + 14d`.
- **STANDARD.** `activate_bundle("core", "1.0", requested_lease=None)` →
  `expires_at = None` (indefinite).
- **PREVIEW eligibility.** `activate_bundle("future-bundle", ...)` under
  PREVIEW raises `CapabilityTierError`.
- **STANDARD eligibility.** Same call under STANDARD succeeds if the
  bundle is in the catalog (wildcard `eligible_bundles=None`).
- **Idempotent deactivate.** `deactivate_bundle` on an inactive
  `(tier, name)` returns `None`; no audit record emitted.
- **Version-pinned deactivate.** Mismatched version raises
  `BundleVersionMismatch`; the active set is unchanged; no audit
  record emitted.
- **Audit.** One audit record per `activate` / `deactivate` event; no
  record on idempotent no-op `deactivate_bundle`.
- **Restrictions.** Non-empty `CapabilityBundle.restrictions` raises
  `NotImplementedError` at activation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ucon.tools.mcp.system import (
    BundleNotFound,
    BundleVersionMismatch,
    BundleVersionNotFound,
    CapabilityBundle,
    CapabilityTierError,
    CollectingSink,
    OperatorState,
    PREVIEW,
    STANDARD,
    StaticCatalog,
    TierConfig,
    activate_bundle,
    deactivate_bundle,
)


T0 = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)


def _catalog_with(*bundles: CapabilityBundle) -> StaticCatalog:
    return StaticCatalog({(b.name, b.version): b for b in bundles})


def _core() -> CapabilityBundle:
    return CapabilityBundle(
        name="core",
        version="1.0",
        provenance="test:core",
        tools=frozenset({"convert"}),
        formula_tools=frozenset({"bmi"}),
    )


# -----------------------------------------------------------------------------
# Activation — lease resolution
# -----------------------------------------------------------------------------

def test_preview_default_lease_24h():
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=None,
    )
    assert ab.expires_at == T0 + timedelta(hours=24)
    assert ab.lease_clamped_from is None
    assert state.active_for("preview", T0) == (ab,)


def test_preview_requested_lease_clamped_to_max_7d():
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=timedelta(days=14),
    )
    assert ab.expires_at == T0 + timedelta(days=7)
    assert ab.lease_clamped_from == T0 + timedelta(days=14)


def test_preview_requested_lease_below_max_not_clamped():
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=timedelta(days=3),
    )
    assert ab.expires_at == T0 + timedelta(days=3)
    assert ab.lease_clamped_from is None


def test_standard_default_lease_indefinite():
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=STANDARD,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=None,
    )
    assert ab.expires_at is None
    assert ab.lease_clamped_from is None


def test_standard_requested_lease_not_clamped_when_max_lease_none():
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=STANDARD,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=timedelta(days=365),
    )
    assert ab.expires_at == T0 + timedelta(days=365)
    assert ab.lease_clamped_from is None


def test_bundle_intrinsic_expiry_clamps_indefinite_lease():
    bundle_expiry = T0 + timedelta(days=2)
    bundle = CapabilityBundle(
        name="core",
        version="1.0",
        expires_at=bundle_expiry,
    )
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(bundle),
        tier_config=STANDARD,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=None,
    )
    # Indefinite lease yields bundle.expires_at directly; this is not a
    # clamp of an operator-requested lease.
    assert ab.expires_at == bundle_expiry
    assert ab.lease_clamped_from is None


def test_bundle_intrinsic_expiry_clamps_finite_lease():
    bundle_expiry = T0 + timedelta(days=1)
    bundle = CapabilityBundle(
        name="core",
        version="1.0",
        expires_at=bundle_expiry,
    )
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(bundle),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=timedelta(days=3),
    )
    assert ab.expires_at == bundle_expiry
    assert ab.lease_clamped_from == T0 + timedelta(days=3)


# -----------------------------------------------------------------------------
# Activation — eligibility
# -----------------------------------------------------------------------------

def test_preview_rejects_non_eligible_bundle():
    future = CapabilityBundle(name="future-bundle", version="1.0")
    state = OperatorState()
    sink = CollectingSink()
    with pytest.raises(CapabilityTierError):
        activate_bundle(
            operator_state=state,
            catalog=_catalog_with(future),
            tier_config=PREVIEW,
            bundle_name="future-bundle",
            bundle_version="1.0",
            activator="ops/test",
            now=T0,
            sink=sink,
        )
    # No state mutation, no audit emission.
    assert state.snapshot() == ()
    assert sink.records == []


def test_standard_wildcard_accepts_any_catalog_bundle():
    future = CapabilityBundle(name="future-bundle", version="1.0")
    state = OperatorState()
    sink = CollectingSink()
    ab = activate_bundle(
        operator_state=state,
        catalog=_catalog_with(future),
        tier_config=STANDARD,
        bundle_name="future-bundle",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
    )
    assert ab.bundle is future
    assert state.active_for("standard", T0) == (ab,)


def test_activation_propagates_bundle_not_found():
    state = OperatorState()
    sink = CollectingSink()
    with pytest.raises(BundleNotFound):
        activate_bundle(
            operator_state=state,
            catalog=_catalog_with(_core()),
            tier_config=STANDARD,
            bundle_name="absent",
            bundle_version="1.0",
            activator="ops/test",
            now=T0,
            sink=sink,
        )
    assert sink.records == []


def test_activation_propagates_bundle_version_not_found():
    state = OperatorState()
    sink = CollectingSink()
    with pytest.raises(BundleVersionNotFound):
        activate_bundle(
            operator_state=state,
            catalog=_catalog_with(_core()),
            tier_config=STANDARD,
            bundle_name="core",
            bundle_version="9.9",
            activator="ops/test",
            now=T0,
            sink=sink,
        )
    assert sink.records == []


# -----------------------------------------------------------------------------
# Activation — forward-compat restrictions
# -----------------------------------------------------------------------------

def test_non_empty_restrictions_rejected_at_activation():
    restricted = CapabilityBundle(
        name="core",
        version="1.0",
        restrictions=("no-mutation",),
    )
    state = OperatorState()
    sink = CollectingSink()
    with pytest.raises(NotImplementedError):
        activate_bundle(
            operator_state=state,
            catalog=_catalog_with(restricted),
            tier_config=STANDARD,
            bundle_name="core",
            bundle_version="1.0",
            activator="ops/test",
            now=T0,
            sink=sink,
        )
    assert state.snapshot() == ()
    assert sink.records == []


# -----------------------------------------------------------------------------
# Activation — audit emission
# -----------------------------------------------------------------------------

def test_activation_emits_one_activate_audit_record():
    state = OperatorState()
    sink = CollectingSink()
    activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/2026-05-13",
        now=T0,
        sink=sink,
    )
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.event == "activate"
    assert rec.tier == "preview"
    assert rec.bundle_name == "core"
    assert rec.bundle_version == "1.0"
    assert rec.bundle_provenance == "test:core"
    assert rec.activator == "ops/2026-05-13"
    assert rec.timestamp == T0
    assert rec.expires_at == T0 + timedelta(hours=24)
    assert rec.lease_clamped_from is None


def test_clamped_activation_audit_records_lease_clamped_from():
    state = OperatorState()
    sink = CollectingSink()
    activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
        requested_lease=timedelta(days=14),
    )
    rec = sink.records[0]
    assert rec.lease_clamped_from == T0 + timedelta(days=14)
    assert rec.expires_at == T0 + timedelta(days=7)


# -----------------------------------------------------------------------------
# Deactivation
# -----------------------------------------------------------------------------

def test_deactivate_active_bundle_returns_removed_and_emits_audit():
    state = OperatorState()
    sink = CollectingSink()
    activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/activator",
        now=T0,
        sink=sink,
    )
    sink.records.clear()

    removed = deactivate_bundle(
        operator_state=state,
        tier_config=PREVIEW,
        bundle_name="core",
        activator="ops/deactivator",
        now=T0 + timedelta(hours=1),
        sink=sink,
    )
    assert removed is not None
    assert removed.bundle.name == "core"
    assert state.active_for("preview", T0 + timedelta(hours=1)) == ()
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.event == "deactivate"
    assert rec.tier == "preview"
    assert rec.bundle_name == "core"
    assert rec.activator == "ops/deactivator"
    assert rec.timestamp == T0 + timedelta(hours=1)


def test_deactivate_inactive_returns_none_and_emits_no_audit():
    state = OperatorState()
    sink = CollectingSink()
    removed = deactivate_bundle(
        operator_state=state,
        tier_config=PREVIEW,
        bundle_name="core",
        activator="ops/test",
        now=T0,
        sink=sink,
    )
    assert removed is None
    assert sink.records == []


def test_deactivate_versioned_match_removes_and_emits_audit():
    state = OperatorState()
    sink = CollectingSink()
    activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
    )
    sink.records.clear()

    removed = deactivate_bundle(
        operator_state=state,
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
    )
    assert removed is not None
    assert len(sink.records) == 1
    assert sink.records[0].event == "deactivate"


def test_deactivate_versioned_mismatch_raises_and_preserves_active():
    state = OperatorState()
    sink = CollectingSink()
    activate_bundle(
        operator_state=state,
        catalog=_catalog_with(_core()),
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
    )
    sink.records.clear()

    with pytest.raises(BundleVersionMismatch):
        deactivate_bundle(
            operator_state=state,
            tier_config=PREVIEW,
            bundle_name="core",
            bundle_version="0.9",
            activator="ops/test",
            now=T0,
            sink=sink,
        )
    # Active set unchanged.
    assert len(state.active_for("preview", T0)) == 1
    # No audit emission on mismatch.
    assert sink.records == []


def test_deactivate_versioned_inactive_returns_none_no_audit():
    state = OperatorState()
    sink = CollectingSink()
    removed = deactivate_bundle(
        operator_state=state,
        tier_config=PREVIEW,
        bundle_name="core",
        bundle_version="1.0",
        activator="ops/test",
        now=T0,
        sink=sink,
    )
    assert removed is None
    assert sink.records == []

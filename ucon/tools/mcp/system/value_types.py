# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.tools.mcp.system.value_types
=================================

Frozen value types backing the capability framework: `CapabilityBundle`,
`ActiveBundle`, `EffectiveCapabilities`, `TierConfig`, `CallerIdentity`.

Pure values. No I/O. No coupling to dispatch, audit, or operator state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ucon.constants import Constant
    from ucon.system import UnitSystem


@dataclass(frozen=True)
class CapabilityBundle:
    """A bundle of capabilities granted to a tier.

    Bundles compose via overlay policies into `EffectiveCapabilities`. The
    bundle itself is a pure value with no I/O and no behavior beyond
    equality and access.

    Attributes
    ----------
    name : str
        Bundle identifier, unique within a catalog.
    version : str
        Version string. Bundles are pinned by `(name, version)`.
    provenance : str
        Free-form text describing where this bundle came from (build
        manifest, operator schedule, etc.). Surfaces in audit records.
    unit_packages : tuple[str, ...]
        Identifiers of unit packages this bundle contributes to the
        effective unit system.
    constants : Mapping[str, Constant]
        Named constants this bundle contributes.
    tools : frozenset[str]
        Tool capabilities this bundle grants. Set semantics: composition
        is union; no implied ordering.
    formula_tools : frozenset[str]
        Formula names accessible via ``call_formula``. Explicit agent
        invocations gated by the capability framework.
    kind_formulas : tuple[str, ...]
        ``KindFormula`` names contributed to arithmetic dispatch.
        Implicit behavior — multiplying two ``Number`` values may
        consult these. Distinct from ``formula_tools`` because the
        security model gates them differently.
    expires_at : datetime | None
        Intrinsic bundle expiry. `None` means no intrinsic expiry; the
        activation lease still bounds the bundle's active lifetime.
    restrictions : tuple[str, ...]
        Reserved for future negative-composition support (capability
        denial). Inert today: activation raises `NotImplementedError`
        if non-empty.
    """

    name: str
    version: str
    provenance: str = ""
    unit_packages: tuple[str, ...] = ()
    constants: Mapping[str, "Constant"] = field(default_factory=dict)
    tools: frozenset[str] = field(default_factory=frozenset)
    formula_tools: frozenset[str] = field(default_factory=frozenset)
    kind_formulas: tuple[str, ...] = ()
    expires_at: datetime | None = None
    restrictions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActiveBundle:
    """An activated bundle: bundle + tier + lease window.

    Produced by `activate_bundle(...)`. Stored in `OperatorState`. The
    activation lease is clamped at activation time; `expires_at` already
    reflects the clamp, while `lease_clamped_from` carries the original
    requested expiry when a clamp occurred (otherwise `None`).
    """

    bundle: CapabilityBundle
    tier: str
    activated_at: datetime
    expires_at: datetime | None
    activator: str
    lease_clamped_from: datetime | None = None


@dataclass(frozen=True)
class EffectiveCapabilities:
    """The composed result of process base + operator overlays + session.

    Produced by `OverlayPolicy.resolve(...)` per request. Pure value.

    ``unit_system`` is the v1.8 :class:`~ucon.system.UnitSystem` value;
    callers route through ``with use(eff.unit_system):`` to make the
    dispatcher-resolved system the active one. The underlying
    :class:`~ucon.graph.ConversionGraph` is reachable via
    ``eff.unit_system.conversion_graph`` for code paths that still
    operate at graph granularity (e.g., inline-graph composition).
    """

    unit_system: "UnitSystem"
    tools: frozenset[str] = field(default_factory=frozenset)
    formula_tools: frozenset[str] = field(default_factory=frozenset)
    kind_formulas: tuple[str, ...] = ()
    audit: tuple[Any, ...] = ()


@dataclass(frozen=True)
class TierConfig:
    """Static configuration for one tier (PREVIEW or STANDARD).

    `eligible_bundles=None` is the wildcard: every catalog entry is
    eligible. `default_lease=None` / `max_lease=None` mean indefinite
    leases (no clamping). `overlay_policy` is the key into a
    policy-lookup table populated by the policy module.
    """

    name: str
    eligible_bundles: frozenset[str] | None
    default_lease: timedelta | None
    max_lease: timedelta | None
    overlay_policy: str
    mutation_allowed: bool


PREVIEW = TierConfig(
    name="preview",
    eligible_bundles=frozenset({"core"}),
    default_lease=timedelta(hours=24),
    max_lease=timedelta(days=7),
    overlay_policy="operator",
    mutation_allowed=False,
)


STANDARD = TierConfig(
    name="standard",
    eligible_bundles=None,
    default_lease=None,
    max_lease=None,
    overlay_policy="session",
    mutation_allowed=True,
)


TIER_CONFIGS: Mapping[str, TierConfig] = {
    PREVIEW.name: PREVIEW,
    STANDARD.name: STANDARD,
}


@dataclass(frozen=True)
class CallerIdentity:
    """The identity of a caller making a tool request.

    `roles` is present on the value type for forward-compat but is not
    consulted by dispatch today (every read site uses the tier). A
    future release will bind `roles` from authenticated transport
    claims and consult it in `activate_bundle`-style flows.
    """

    tier: str
    principal: str
    roles: frozenset[str] = field(default_factory=frozenset)

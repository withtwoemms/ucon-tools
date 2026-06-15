# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.tools.mcp.system.dispatch
==============================

Pure tier-driven dispatcher: a single seam isolated from FastMCP
request plumbing.

`Dispatcher.prepare(...)` performs one request's worth of work:

1. Pick `tier_config` from the request's `CallerIdentity` (or the
   constructor-injected default).
2. Reap any bundles whose lease has expired and emit one `"expire"`
   `AuditRecord` per reaped bundle.
3. Snapshot the tier's active bundles at `clock.now()`.
4. Drop `session_overlay` for tiers that disallow mutation
   (`tier_config.mutation_allowed is False`).
5. Resolve `EffectiveCapabilities` via the tier's `OverlayPolicy`.
6. Gate `tool_name` against `eff.tools`; raise `CapabilityNotAvailable`
   *before* the caller can invoke any tool code.

Server-side wiring (FastMCP `@mcp.tool()` registrations, the
`with use(eff.unit_system):` window, identity extraction from transport
headers) is intentionally out of scope here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from ucon.tools.mcp.system.audit import AuditRecord, AuditSink
from ucon.tools.mcp.system.clock import Clock
from ucon.tools.mcp.system.operator_state import OperatorState
from ucon.tools.mcp.system.overlay import OverlayPolicy, SessionOverlay
from ucon.tools.mcp.system.process_base import ProcessBase
from ucon.tools.mcp.system.value_types import (
    ActiveBundle,
    CallerIdentity,
    EffectiveCapabilities,
    TierConfig,
)


class CapabilityNotAvailable(LookupError):
    """A request named a tool that is not in the resolved
    `EffectiveCapabilities.tools` for the caller's tier.

    Raised by `Dispatcher.prepare(...)` before any tool body runs so the
    caller can fail fast with provenance (`eff.audit`) attached.
    """

    def __init__(
        self,
        tool_name: str,
        audit: tuple,
    ) -> None:
        super().__init__(
            f"tool {tool_name!r} not available under the resolved "
            f"capabilities (audit={audit!r})"
        )
        self.tool_name = tool_name
        self.audit = audit


def _expire_record(active_bundle: ActiveBundle, now) -> AuditRecord:
    """Build the `"expire"` `AuditRecord` for a reaped bundle.

    `activator` is preserved from the original activation so the audit
    stream attributes the lifecycle event to the same principal that
    started it (per `AuditRecord.activator` docstring).
    """
    return AuditRecord(
        event="expire",
        tier=active_bundle.tier,
        bundle_name=active_bundle.bundle.name,
        bundle_version=active_bundle.bundle.version,
        bundle_provenance=active_bundle.bundle.provenance,
        activator=active_bundle.activator,
        timestamp=now,
        expires_at=active_bundle.expires_at,
        lease_clamped_from=active_bundle.lease_clamped_from,
    )


@dataclass(frozen=True)
class Dispatcher:
    """Pure tier-driven dispatcher.

    Composes a `ProcessBase`, an `OperatorState`, a tier→policy mapping,
    a `Clock`, and an `AuditSink` into one callable seam. `prepare(...)`
    returns the resolved `EffectiveCapabilities`; the caller is
    responsible for `with use(eff.unit_system):` and the actual tool
    invocation.

    Attributes
    ----------
    process_base : ProcessBase
        The per-process foundation (base graph, base tools/formulas,
        catalog).
    operator_state : OperatorState
        The shared, mutable, thread-safe activation registry.
    policies : Mapping[str, OverlayPolicy]
        Keyed by `TierConfig.overlay_policy` (the policy *name*, e.g.,
        `"session"` or `"operator"`). The dispatcher looks up the
        request's policy at `prepare(...)` time.
    tier_configs : Mapping[str, TierConfig]
        Keyed by tier name. Typically `TIER_CONFIGS`.
    clock : Clock
        Source of the single `now` timestamp used for reaping and audit.
    sink : AuditSink
        Destination for `"expire"` records emitted by `reap_expired`.
    default_identity : CallerIdentity
        Used when `prepare(...)` is called without an explicit identity.
        Constructor-injected so transport-level identity extraction can
        live outside this module.
    """

    process_base: ProcessBase
    operator_state: OperatorState
    policies: Mapping[str, OverlayPolicy]
    tier_configs: Mapping[str, TierConfig]
    clock: Clock
    sink: AuditSink
    default_identity: CallerIdentity

    def prepare(
        self,
        tool_name: str,
        *,
        identity: CallerIdentity | None = None,
        session_overlay: SessionOverlay | None = None,
    ) -> EffectiveCapabilities:
        """Resolve `EffectiveCapabilities` for one request and gate
        `tool_name`.

        Parameters
        ----------
        tool_name : str
            The tool the caller intends to invoke. Checked against
            `eff.tools` before this method returns.
        identity : CallerIdentity, optional
            Per-request caller identity. Defaults to
            `self.default_identity`.
        session_overlay : SessionOverlay, optional
            Caller-supplied per-session overlay. Forced to `None` for
            tiers whose `TierConfig.mutation_allowed` is `False`
            (e.g., PREVIEW).

        Returns
        -------
        EffectiveCapabilities
            The resolved capability view. The caller enters
            `with use(eff.unit_system):` and invokes the tool.

        Raises
        ------
        KeyError
            `identity.tier` is unknown, or its `overlay_policy` is not
            in `self.policies`. These are configuration errors, not
            per-request failures.
        CapabilityNotAvailable
            `tool_name` is not in `eff.tools` for the resolved policy.
        SessionMutationRejected
            Raised by `OperatorOverlayPolicy.resolve` when a non-empty
            session overlay reaches a no-mutation tier. (Should not
            occur here because we drop overlays for such tiers; surfaces
            only if a tier mis-configures `mutation_allowed`.)
        """
        identity = identity if identity is not None else self.default_identity
        tier_config = self.tier_configs[identity.tier]
        policy = self.policies[tier_config.overlay_policy]
        now = self.clock.now()

        for expired in self.operator_state.reap_expired(now):
            self.sink.emit(_expire_record(expired, now))

        active = self.operator_state.active_for(identity.tier, now)
        active_bundles = tuple(ab.bundle for ab in active)

        effective_overlay = (
            session_overlay if tier_config.mutation_allowed else None
        )

        eff = policy.resolve(
            base=self.process_base.unit_system,
            base_tools=self.process_base.tools,
            base_formulas=self.process_base.formula_tools,
            active_bundles=active_bundles,
            session_overlay=effective_overlay,
        )
        eff = replace(eff, strict=tier_config.strict)

        if tool_name not in eff.tools:
            raise CapabilityNotAvailable(tool_name, eff.audit)

        return eff

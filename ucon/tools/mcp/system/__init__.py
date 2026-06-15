# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.tools.mcp.system
=====================

Capability framework: process base, capability bundles, tier
configuration, operator state, overlay policies, and the tier-driven
dispatcher.
"""
from __future__ import annotations

from ucon.tools.mcp.system.audit import (
    AuditRecord,
    AuditSink,
    CollectingSink,
    StderrJsonSink,
)
from ucon.tools.mcp.system.clock import Clock, FixedClock, SystemClock
from ucon.tools.mcp.system.dispatch import (
    CapabilityNotAvailable,
    Dispatcher,
)
from ucon.tools.mcp.system.catalog import (
    BundleCatalog,
    BundleNotFound,
    BundleVersionNotFound,
    CORE_BUNDLE,
    DEFAULT_CATALOG,
    StaticCatalog,
)
from ucon.tools.mcp.system.operator import (
    CapabilityTierError,
    activate_bundle,
    deactivate_bundle,
)
from ucon.tools.mcp.system.operator_state import (
    BundleVersionMismatch,
    OperatorState,
)
from ucon.tools.mcp.system.overlay import (
    OperatorOverlayPolicy,
    OverlayPolicy,
    SessionMutationRejected,
    SessionOverlay,
    SessionOverlayPolicy,
    SessionStateOverlay,
)
from ucon.tools.mcp.system.process_base import ProcessBase
from ucon.tools.mcp.system.resolver import PackageResolver
from ucon.tools.mcp.system.startup import (
    ENV_PROFILE,
    ENV_SYSTEM,
    StartupConfig,
)
from ucon.tools.mcp.system.value_types import (
    ActiveBundle,
    CallerIdentity,
    CapabilityBundle,
    EffectiveCapabilities,
    PREVIEW,
    STANDARD,
    TIER_CONFIGS,
    TierConfig,
)

__all__ = [
    "ActiveBundle",
    "AuditRecord",
    "AuditSink",
    "BundleCatalog",
    "BundleNotFound",
    "BundleVersionMismatch",
    "BundleVersionNotFound",
    "CORE_BUNDLE",
    "CallerIdentity",
    "CapabilityBundle",
    "CapabilityNotAvailable",
    "CapabilityTierError",
    "Clock",
    "CollectingSink",
    "DEFAULT_CATALOG",
    "Dispatcher",
    "ENV_PROFILE",
    "ENV_SYSTEM",
    "EffectiveCapabilities",
    "FixedClock",
    "OperatorOverlayPolicy",
    "OperatorState",
    "PackageResolver",
    "OverlayPolicy",
    "PREVIEW",
    "ProcessBase",
    "STANDARD",
    "SessionMutationRejected",
    "SessionOverlay",
    "SessionOverlayPolicy",
    "SessionStateOverlay",
    "StartupConfig",
    "StaticCatalog",
    "StderrJsonSink",
    "SystemClock",
    "TIER_CONFIGS",
    "TierConfig",
    "activate_bundle",
    "deactivate_bundle",
]

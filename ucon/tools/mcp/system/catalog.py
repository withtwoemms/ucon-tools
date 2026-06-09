# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.tools.mcp.system.catalog
=============================

`BundleCatalog` — the namespace of known bundles. Ships a single
concrete implementation (`StaticCatalog`) and a single populated catalog
(`DEFAULT_CATALOG`) containing exactly `CORE_BUNDLE`.
"""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from ucon.tools.mcp.system.value_types import CapabilityBundle


class BundleNotFound(LookupError):
    """No bundle with this `name` exists in the catalog."""


class BundleVersionNotFound(LookupError):
    """A bundle with this `name` exists, but not at this `version`."""


@runtime_checkable
class BundleCatalog(Protocol):
    """The namespace of known bundles.

    Catalogs are lookup-only: they do not own state, lifetime, or
    activation. Activation lives in `OperatorState` and is driven
    through `activate_bundle(...)`.
    """

    def get(self, name: str, version: str) -> CapabilityBundle:
        """Return the bundle pinned by `(name, version)`.

        Raises
        ------
        BundleNotFound
            If no bundle with this name is in the catalog.
        BundleVersionNotFound
            If a bundle with this name exists but not at this version.
        """
        ...


class StaticCatalog:
    """A `BundleCatalog` backed by an immutable `(name, version) → bundle` map.

    Constructed once at process startup. Lookups are pure.
    """

    def __init__(self, bundles: Mapping[tuple[str, str], CapabilityBundle]) -> None:
        # Defensive copy: callers should not be able to mutate the catalog
        # after construction.
        self._bundles: dict[tuple[str, str], CapabilityBundle] = dict(bundles)

    def get(self, name: str, version: str) -> CapabilityBundle:
        if (name, version) in self._bundles:
            return self._bundles[(name, version)]
        # Differentiate "name absent" from "name present, version absent".
        if any(n == name for (n, _v) in self._bundles):
            raise BundleVersionNotFound(
                f"bundle {name!r} found, but not at version {version!r}"
            )
        raise BundleNotFound(f"bundle {name!r} not in catalog")


# -----------------------------------------------------------------------------
# Built-in bundle and catalog
# -----------------------------------------------------------------------------

# The read-only tool roster shipped in the core bundle. Mutating tools
# (`define_unit`, `define_conversion`, `define_constant`,
# `define_quantity_kind`, `extend_basis`, `reset_session`) are
# deliberately excluded; future split-per-concern bundles will host
# them once their composition story is settled.
_CORE_TOOLS: frozenset[str] = frozenset({
    "convert",
    "compute",
    "decompose",
    "list_units",
    "list_scales",
    "list_dimensions",
    "check_dimensions",
    "list_constants",
    "declare_computation",
    "validate_result",
    "list_quantity_kinds",
    "list_extended_bases",
    "list_formulas",
    "call_formula",
})


# CORE_BUNDLE.formula_tools is a curated subset of universally applicable
# formulas accessible via call_formula. Domain-specific formula sets
# (aerospace, chemistry, medical, etc.) are reserved for separate bundles.
_CORE_FORMULA_TOOLS: frozenset[str] = frozenset({"bmi", "fib4"})


CORE_BUNDLE: CapabilityBundle = CapabilityBundle(
    name="core",
    version="1.0",
    provenance="ucon-tools built-in",
    unit_packages=(),
    constants={},
    tools=_CORE_TOOLS,
    formula_tools=_CORE_FORMULA_TOOLS,
    kind_formulas=(),
    expires_at=None,
)


DEFAULT_CATALOG: BundleCatalog = StaticCatalog({(CORE_BUNDLE.name, CORE_BUNDLE.version): CORE_BUNDLE})

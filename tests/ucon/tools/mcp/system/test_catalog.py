# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for `ucon.tools.mcp.system.catalog`.

Invariants under test:
- `DEFAULT_CATALOG.get("core", "1.0")` returns `CORE_BUNDLE`.
- `DEFAULT_CATALOG.get("absent", "1.0")` raises `BundleNotFound`.
- `DEFAULT_CATALOG.get("core", "9.9")` raises `BundleVersionNotFound`.
- Every name in `CORE_BUNDLE.formula_tools` exists in the formula registry.
- None of `define_unit`, `define_conversion`, `define_constant`,
  `define_quantity_kind`, `extend_basis`, `reset_session` appear in
  `CORE_BUNDLE.tools`.
"""
from __future__ import annotations

import pytest

from ucon.tools.mcp.formulas import list_formulas
from ucon.tools.mcp.system import (
    BundleCatalog,
    BundleNotFound,
    BundleVersionNotFound,
    CORE_BUNDLE,
    CapabilityBundle,
    DEFAULT_CATALOG,
    StaticCatalog,
)


# -----------------------------------------------------------------------------
# Protocol conformance
# -----------------------------------------------------------------------------

def test_static_catalog_is_a_bundle_catalog():
    assert isinstance(StaticCatalog({}), BundleCatalog)


def test_default_catalog_is_a_bundle_catalog():
    assert isinstance(DEFAULT_CATALOG, BundleCatalog)


# -----------------------------------------------------------------------------
# DEFAULT_CATALOG lookup semantics
# -----------------------------------------------------------------------------

def test_default_catalog_get_core_returns_core_bundle():
    assert DEFAULT_CATALOG.get("core", "1.0") is CORE_BUNDLE


def test_default_catalog_get_absent_raises_bundle_not_found():
    with pytest.raises(BundleNotFound):
        DEFAULT_CATALOG.get("absent", "1.0")


def test_default_catalog_get_wrong_version_raises_version_not_found():
    with pytest.raises(BundleVersionNotFound):
        DEFAULT_CATALOG.get("core", "9.9")


# -----------------------------------------------------------------------------
# StaticCatalog generic behavior
# -----------------------------------------------------------------------------

def test_static_catalog_returns_pinned_bundle():
    b1 = CapabilityBundle(name="x", version="1.0")
    b2 = CapabilityBundle(name="x", version="2.0")
    cat = StaticCatalog({("x", "1.0"): b1, ("x", "2.0"): b2})
    assert cat.get("x", "1.0") is b1
    assert cat.get("x", "2.0") is b2


def test_static_catalog_distinguishes_missing_name_from_missing_version():
    b = CapabilityBundle(name="x", version="1.0")
    cat = StaticCatalog({("x", "1.0"): b})
    with pytest.raises(BundleNotFound):
        cat.get("y", "1.0")
    with pytest.raises(BundleVersionNotFound):
        cat.get("x", "2.0")


def test_static_catalog_is_immutable_post_construction():
    b = CapabilityBundle(name="x", version="1.0")
    mapping = {("x", "1.0"): b}
    cat = StaticCatalog(mapping)
    mapping[("y", "1.0")] = CapabilityBundle(name="y", version="1.0")
    with pytest.raises(BundleNotFound):
        cat.get("y", "1.0")


# -----------------------------------------------------------------------------
# CORE_BUNDLE invariants
# -----------------------------------------------------------------------------

def test_core_bundle_metadata():
    assert CORE_BUNDLE.name == "core"
    assert CORE_BUNDLE.version == "1.0"
    assert CORE_BUNDLE.provenance == "ucon-tools built-in"
    assert CORE_BUNDLE.expires_at is None
    assert CORE_BUNDLE.restrictions == ()


def test_core_bundle_formulas_match_registry():
    """Every name in CORE_BUNDLE.formula_tools must exist in the formula registry."""
    registry_names = {info.name for info in list_formulas()}
    for fname in CORE_BUNDLE.formula_tools:
        assert fname in registry_names, (
            f"CORE_BUNDLE advertises formula {fname!r} not in the registry"
        )


def test_core_bundle_excludes_mutating_tools():
    """The six mutating tools must not appear in CORE_BUNDLE.tools."""
    mutating = {
        "define_unit",
        "define_conversion",
        "define_constant",
        "define_quantity_kind",
        "extend_basis",
        "reset_session",
    }
    intersection = CORE_BUNDLE.tools & mutating
    assert intersection == frozenset(), (
        f"CORE_BUNDLE.tools contains mutating tools: {intersection}"
    )


def test_core_bundle_contains_expected_read_only_tools():
    """The read-only tool roster must all be present in CORE."""
    expected = frozenset({
        "convert", "compute", "decompose",
        "list_units", "list_scales", "list_dimensions",
        "check_dimensions", "list_constants",
        "declare_computation", "validate_result",
        "list_quantity_kinds", "list_extended_bases",
        "list_formulas", "call_formula",
        "restrict_system",
    })
    assert CORE_BUNDLE.tools == expected


# -----------------------------------------------------------------------------
# ProcessBase.from_globals integration with catalog
# -----------------------------------------------------------------------------

def test_process_base_from_globals_defaults_catalog_to_default():
    from ucon.tools.mcp.system import ProcessBase
    pb = ProcessBase.from_globals()
    assert pb.catalog is DEFAULT_CATALOG

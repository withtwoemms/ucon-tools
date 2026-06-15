# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.tools.mcp.system.resolver
==============================

`PackageResolver` protocol and its filesystem-backed implementation.

A resolver loads a named package identifier into a `UnitSystem` that can
be composed with the process base via `UnitSystem.extend(...)`. The
resolver is optional: when `None`, any bundle declaring `unit_packages`
will fail loudly at resolve time (preserving the v0.5.x behaviour).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ucon.system import UnitSystem


@runtime_checkable
class PackageResolver(Protocol):
    """Resolves a package identifier to a `UnitSystem` fragment.

    The returned system contains only the units, conversions, and
    constants contributed by that package. Overlay composition merges
    these fragments into the process base via `extend_many`.
    """

    def load(self, package_id: str) -> "UnitSystem":
        """Load a package and return its `UnitSystem` representation.

        Parameters
        ----------
        package_id : str
            Identifier of the package to load (e.g., a TOML filename
            stem, a catalog key, or a URL depending on implementation).

        Returns
        -------
        UnitSystem
            The system fragment contributed by the package.

        Raises
        ------
        PackageLoadError
            If the package cannot be loaded (missing file, parse error,
            unsatisfied dependency, etc.).
        """
        ...

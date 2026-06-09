# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.tools.mcp.system.process_base
==================================

`ProcessBase` is the frozen value owning the per-process foundation of the
MCP server: the base unit system, the advertised tool roster, the registered
formulas, and the bundle catalog. It is built once at process startup and
referenced by `OverlayPolicy.resolve(...)` on every request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ucon.system import UnitSystem, active_system
from ucon.tools.mcp.formulas import list_formulas
from ucon.tools.mcp.system.catalog import DEFAULT_CATALOG


@dataclass(frozen=True)
class ProcessBase:
    """Per-process foundation: base unit system, tools, formulas, catalog.

    Pinned at startup. Composed bottom-up with operator overlays and (in
    STANDARD tier) session overlays via `OverlayPolicy.resolve(...)`.

    Attributes
    ----------
    unit_system : UnitSystem
        The base unit system for the process. Owns the v1.8
        :class:`~ucon.system.UnitSystem` (basis, registries,
        conversion graph, basis graph, constants). Dispatch activates
        this system with ``with use(eff.unit_system):`` and reaches
        through to the underlying graph via
        ``eff.unit_system.conversion_graph`` where needed.
    tools : frozenset[str]
        Names of MCP tools advertised by this process. Dispatch gates each
        request by `request.tool in effective.tools`.
    formula_tools : frozenset[str]
        Names of registered domain formulas accessible via
        ``call_formula``. Mirrors the formula registry at
        process-startup snapshot time.
    catalog : Any
        The `BundleCatalog` (Protocol) of known bundles. Typed as `Any`
        because `BundleCatalog` is a Protocol — any structurally
        conforming object is accepted; `DEFAULT_CATALOG` is the default.
    """

    unit_system: "UnitSystem"
    tools: frozenset[str] = field(default_factory=frozenset)
    formula_tools: frozenset[str] = field(default_factory=frozenset)
    catalog: Any = None

    @classmethod
    def from_globals(
        cls,
        *,
        unit_system: "UnitSystem | None" = None,
        tools: frozenset[str] | None = None,
        formulas: frozenset[str] | None = None,
        catalog: Any = None,
    ) -> "ProcessBase":
        """Build a `ProcessBase` from the active unit system.

        Defaults each field by introspecting the running process:

        - `unit_system`: ``active_system()`` — returns the active
          ``UnitSystem`` from the ``ActiveContext`` ContextVar.
        - `tools`: names of every `@mcp.tool()` registered on the
          module-level `FastMCP` instance in `ucon.tools.mcp.server`.
        - `formula_tools`: names returned by the formula registry's
          `list_formulas()`.
        - `catalog`: defaults to `DEFAULT_CATALOG`.

        Any explicit keyword overrides the corresponding default. The
        method has no side effects; it produces a fresh frozen value.
        """
        if unit_system is None:
            unit_system = active_system()
        if tools is None:
            tools = _discover_registered_tools()
        if formulas is None:
            formulas = _discover_registered_formulas()
        if catalog is None:
            catalog = DEFAULT_CATALOG
        return cls(
            unit_system=unit_system,
            tools=tools,
            formula_tools=formulas,
            catalog=catalog,
        )


def _discover_registered_tools() -> frozenset[str]:
    """Names of `@mcp.tool()`-decorated functions on the server's FastMCP.

    Walks the FastMCP tool-manager state. The tool manager's exposed
    attribute is `_tool_manager` in current `mcp.server.fastmcp`; access
    via the public listing if the private form moves.
    """
    from ucon.tools.mcp.server import mcp

    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:
        return frozenset()
    tools_attr = getattr(manager, "_tools", None)
    if isinstance(tools_attr, dict):
        return frozenset(tools_attr.keys())
    return frozenset()


def _discover_registered_formulas() -> frozenset[str]:
    """Names of formulas registered via `@register_formula`."""
    return frozenset(info.name for info in list_formulas())

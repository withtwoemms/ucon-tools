# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.mcp.session
================

Injectable session state for MCP tools.

Provides session persistence across tool calls using FastMCP's lifespan context.
ContextVar-based isolation doesn't work for MCP because each tool call runs in
a separate async task. The lifespan context persists for the server's lifetime
and is accessible to all tools via Context injection.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ucon.constants import Constant
    from ucon.graph import ConversionGraph
    from ucon.tools.mcp.koq import ComputationDeclaration, ExtendedBasisInfo, QuantityKindInfo


@runtime_checkable
class SessionState(Protocol):
    """Protocol for injectable MCP session state.

    Allows dependency injection of session management for testing
    and custom implementations.

    Concurrency Model
    -----------------
    MCP protocol is request-response: client waits for each response before
    the next request. Tool calls are sequential by protocol design, so no
    locks are needed. Session state modifications are single-writer.
    """

    def get_graph(self) -> "ConversionGraph":
        """Get the session's conversion graph."""
        ...

    def get_constants(self) -> dict[str, "Constant"]:
        """Get the session's custom constants."""
        ...

    def get_quantity_kinds(self) -> dict[str, "QuantityKindInfo"]:
        """Get the session's custom quantity kinds."""
        ...

    def register_quantity_kind(self, kind: "QuantityKindInfo") -> None:
        """Register a quantity kind for this session."""
        ...

    def get_active_computation(self) -> "ComputationDeclaration | None":
        """Get the active computation declaration, if any."""
        ...

    def set_active_computation(self, decl: "ComputationDeclaration | None") -> None:
        """Set or clear the active computation declaration."""
        ...

    def get_extended_bases(self) -> dict[str, "ExtendedBasisInfo"]:
        """Get the session's extended bases."""
        ...

    def register_extended_basis(self, basis: "ExtendedBasisInfo") -> None:
        """Register an extended basis for this session."""
        ...

    def reset(self) -> None:
        """Reset session to default state."""
        ...


class DefaultSessionState:
    """Default session state implementation.

    Maintains a single conversion graph, constants dict, quantity kinds,
    and active computation declaration for the lifetime of the MCP server session.

    Parameters
    ----------
    base_graph : ConversionGraph | None
        Optional base graph to copy from. If None, uses get_default_graph().

    Examples
    --------
    >>> session = DefaultSessionState()
    >>> graph = session.get_graph()
    >>> graph.register_unit(custom_unit)
    >>> # Unit persists across subsequent get_graph() calls
    >>> graph2 = session.get_graph()
    >>> assert graph is graph2  # Same instance
    """

    def __init__(self, base_graph: "ConversionGraph | None" = None):
        self._base_graph = base_graph
        self._graph: "ConversionGraph | None" = None
        self._constants: dict[str, "Constant"] = {}
        self._quantity_kinds: dict[str, "QuantityKindInfo"] = {}
        self._active_computation: "ComputationDeclaration | None" = None
        self._extended_bases: dict[str, "ExtendedBasisInfo"] = {}

    def get_graph(self) -> "ConversionGraph":
        """Get or create the session graph.

        Returns a copy of the base graph on first access, then reuses
        the session graph for subsequent calls.
        """
        if self._graph is None:
            from ucon.graph import get_default_graph
            base = self._base_graph or get_default_graph()
            self._graph = base.copy()
        return self._graph

    def get_constants(self) -> dict[str, "Constant"]:
        """Get the session's custom constants dictionary."""
        return self._constants

    def get_quantity_kinds(self) -> dict[str, "QuantityKindInfo"]:
        """Get the session's custom quantity kinds dictionary."""
        return self._quantity_kinds

    def register_quantity_kind(self, kind: "QuantityKindInfo") -> None:
        """Register a quantity kind for this session.

        Parameters
        ----------
        kind : QuantityKindInfo
            The quantity kind to register.
        """
        self._quantity_kinds[kind.name] = kind

    def get_active_computation(self) -> "ComputationDeclaration | None":
        """Get the active computation declaration, if any."""
        return self._active_computation

    def set_active_computation(self, decl: "ComputationDeclaration | None") -> None:
        """Set or clear the active computation declaration.

        Parameters
        ----------
        decl : ComputationDeclaration | None
            The declaration to set, or None to clear.
        """
        self._active_computation = decl

    def get_extended_bases(self) -> dict[str, "ExtendedBasisInfo"]:
        """Get the session's extended bases dictionary."""
        return self._extended_bases

    def register_extended_basis(self, basis: "ExtendedBasisInfo") -> None:
        """Register an extended basis for this session.

        Parameters
        ----------
        basis : ExtendedBasisInfo
            The extended basis to register.
        """
        self._extended_bases[basis.name] = basis

    def reset(self) -> None:
        """Reset session to default state.

        Creates a fresh copy of the base graph and clears all session state.
        """
        from ucon.graph import get_default_graph
        base = self._base_graph or get_default_graph()
        self._graph = base.copy()
        self._constants = {}
        self._quantity_kinds = {}
        self._active_computation = None
        self._extended_bases = {}

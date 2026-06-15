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
    from ucon.dimension import Dimension
    from ucon.graph import ConversionGraph
    from ucon.kinds import KindLattice
    from ucon.system import UnitSystem
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

    def get_unit_system(self) -> "UnitSystem":
        """Get the session's :class:`~ucon.system.UnitSystem`.

        The returned system wraps :meth:`get_graph` as its
        ``conversion_graph``; reach-through paths (basis graph,
        constants, contexts) read from the surrounding globals via
        ``active_system()``-style snapshotting.
        """
        ...

    def get_constants(self) -> dict[str, "Constant"]:
        """Get the session's custom constants."""
        ...

    def get_quantity_kinds(self) -> dict[str, "QuantityKindInfo"]:
        """Get the session's custom quantity kinds."""
        ...

    def get_kind_lattice(self) -> "KindLattice":
        """Get the session's KindLattice (copy-on-first-access).

        Returns the session's mutable kind lattice, which may contain
        kinds registered via ``define_quantity_kind``. The lattice is
        copied from the base on first access to avoid cross-session
        contamination.
        """
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

    def get_session_dimensions(self) -> dict[str, "Dimension"]:
        """Get dimensions created from extended bases."""
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

    def __init__(
        self,
        base_graph: "ConversionGraph | None" = None,
        base_lattice: "KindLattice | None" = None,
    ):
        # Capture the default graph eagerly so subsequent `reset()` calls
        # restore to the same base regardless of any active ambient
        # `using_conversion_graph` context (which `get_default_graph()`
        # honors when consulted later).
        if base_graph is None:
            from ucon.graph import get_default_graph
            base_graph = get_default_graph()
        self._base_graph: "ConversionGraph" = base_graph
        if base_lattice is None:
            from ucon.kinds import KindLattice
            base_lattice = KindLattice()
        self._base_lattice: "KindLattice" = base_lattice
        self._graph: "ConversionGraph | None" = None
        self._kind_lattice: "KindLattice | None" = None
        self._constants: dict[str, "Constant"] = {}
        self._quantity_kinds: dict[str, "QuantityKindInfo"] = {}
        self._active_computation: "ComputationDeclaration | None" = None
        self._extended_bases: dict[str, "ExtendedBasisInfo"] = {}
        self._session_dimensions: dict[str, "Dimension"] = {}

    def get_graph(self) -> "ConversionGraph":
        """Get or create the session graph.

        Returns a copy of the base graph on first access, then reuses
        the session graph for subsequent calls.
        """
        if self._graph is None:
            self._graph = self._base_graph.copy()
        return self._graph

    def get_unit_system(self) -> "UnitSystem":
        """Build a :class:`~ucon.system.UnitSystem` over the session graph.

        The returned ``UnitSystem``'s ``conversions`` field is the
        session's mutable graph (``self.get_graph()``); the other
        registries (``units``, ``dimensions``, ``basis``,
        ``base_units``, ``basis_graph``, ``contexts``, ``constants``)
        are snapshotted from the ambient globals on each call.

        Constructing fresh on each call keeps the value consistent with
        in-place mutation of the session graph and with future
        session-owned registries; the inner dicts are shared by
        reference, so a long-lived ``UnitSystem`` captured by ``use(...)``
        still observes subsequent session mutations.
        """
        # Deferred imports: `ucon.system` and friends sit above
        # `ucon.tools.mcp.session` in the import DAG when imported
        # via the MCP server.
        #
        # As of ucon v1.12.0 the registries are reachable from the
        # active ``UnitSystem`` rather than the deleted
        # ``ucon._loader`` module. As of ucon v2.0.0a1 the ``_active``
        # ContextVar carries an ``ActiveContext`` payload, so we use
        # ``active_system()`` to obtain the live ``UnitSystem`` and
        # override only the conversion graph with the session-owned
        # one.
        from ucon import active_system
        from ucon.system import UnitSystem

        graph = self.get_graph()
        live = active_system()
        return UnitSystem(
            basis=live.basis,
            units=live.units,
            dimensions=live.dimensions,
            base_units=live.base_units,
            conversion_graph=graph,
            basis_graph=live.basis_graph,
            contexts=getattr(graph, "_contexts", {}),
            constants=live.constants,
        )

    def get_constants(self) -> dict[str, "Constant"]:
        """Get the session's custom constants dictionary."""
        return self._constants

    def get_kind_lattice(self) -> "KindLattice":
        """Get or create the session's KindLattice (copy-on-first-access).

        Returns a copy of the base lattice on first access, then reuses
        the session lattice for subsequent calls. Prevents cross-session
        contamination while allowing per-session Kind registration.
        """
        if self._kind_lattice is None:
            self._kind_lattice = self._base_lattice.copy()
        return self._kind_lattice

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

    def get_session_dimensions(self) -> dict[str, "Dimension"]:
        """Get the session's dimensions created from extended bases."""
        return self._session_dimensions

    def reset(self) -> None:
        """Reset session to default state.

        Creates a fresh copy of the base graph and clears all session state.
        """
        self._graph = self._base_graph.copy()
        self._kind_lattice = None
        self._constants = {}
        self._quantity_kinds = {}
        self._active_computation = None
        self._extended_bases = {}
        self._session_dimensions = {}

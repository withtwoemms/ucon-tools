# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
ucon.tools.mcp.koq
==================

Kind-of-Quantity (KOQ) types for MCP tools.

Provides disambiguation for dimensionally degenerate physical quantities
(e.g., enthalpy vs Gibbs energy, both energy/amount_of_substance).

Quantity kinds are defined on-demand per session via define_quantity_kind(),
following the same pattern as custom unit creation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from ucon.basis import Basis
    from ucon.dimension import Dimension


# -----------------------------------------------------------------------------
# Core Types
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantityKindInfo:
    """Metadata for a physical quantity kind.

    Quantity kinds disambiguate between physically distinct quantities
    that share the same dimensional signature.

    Parameters
    ----------
    name : str
        Unique identifier (e.g., "gibbs_energy").
    dimension_name : str
        Human-readable dimension description (e.g., "energy/amount_of_substance").
    dimension_vector : str
        Dimensional signature in SI base units (e.g., "M·L²·T⁻²·N⁻¹").
    description : str
        Human-readable description of the quantity.
    aliases : tuple[str, ...]
        Alternative names for the quantity kind.
    category : str
        Classification (e.g., "thermodynamic", "mechanical", "chemical").
    disambiguation_hints : tuple[str, ...]
        Hints for distinguishing this kind from similar quantities.
    """

    name: str
    dimension_name: str
    dimension_vector: str
    description: str
    aliases: tuple[str, ...] = ()
    category: str = "general"
    disambiguation_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComputationContext:
    """Context information for a declared computation.

    Stores additional context that may help with semantic validation.
    """

    temperature: str | None = None
    pressure: str | None = None
    system: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ExtendedBasisInfo:
    """Metadata for an extended dimensional basis.

    Extended bases add semantic components to the standard SI basis,
    allowing finer-grained distinction between quantity kinds.

    Parameters
    ----------
    name : str
        Unique identifier for the basis.
    base : str
        The base system this extends (e.g., "SI", "CGS").
    components : tuple[str, ...]
        All components in the extended basis.
    additional_components : tuple[tuple[str, str, str], ...]
        Additional components as (name, symbol, description) tuples.
    runtime_basis : Basis | None
        Materialized ucon `Basis` object for the extended basis (Phase 2).
    runtime_dimensions : tuple[Dimension, ...]
        Materialized `Dimension` objects, one per additional component (Phase 2).
    """

    name: str
    base: str
    components: tuple[str, ...]
    additional_components: tuple[tuple[str, str, str], ...] = ()
    runtime_basis: "Basis | None" = None
    runtime_dimensions: tuple["Dimension", ...] = ()


# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------


class QuantityKindDefinitionResult(BaseModel):
    """Result of defining a custom quantity kind."""

    success: bool
    name: str
    dimension: str
    vector_signature: str
    category: str
    message: str


class ComputationDeclaration(BaseModel):
    """Result of declaring a computation with expected quantity kind."""

    declaration_id: str
    quantity_kind: str
    expected_unit: str
    expected_dimension: str
    status: str  # "valid", "warning"
    warnings: list[str] = []
    compatible_kinds: list[str] = []
    message: str


class ValidationResult(BaseModel):
    """Result of validating a computed result against a declared kind."""

    passed: bool
    value: float
    unit: str
    declared_kind: str
    actual_dimension: str
    expected_dimension: str
    dimension_match: bool
    semantic_warnings: list[str] = []
    confidence: str  # "high", "medium", "low"
    explanation: str
    suggestions: list[str] = []


class ExtendedBasisResult(BaseModel):
    """Result of creating an extended dimensional basis."""

    success: bool
    name: str
    base: str
    components: list[str]
    message: str


class KOQError(BaseModel):
    """Error from KOQ operations."""

    error: str
    error_type: str  # "unknown_kind", "dimension_mismatch", "no_active_declaration", "duplicate_kind"
    parameter: str | None = None
    hints: list[str] = []


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


def get_quantity_kind(
    name: str,
    session_kinds: dict[str, QuantityKindInfo] | None = None,
) -> QuantityKindInfo | None:
    """Look up a quantity kind by name or alias.

    Parameters
    ----------
    name : str
        The name or alias to look up.
    session_kinds : dict[str, QuantityKindInfo] | None
        Session-defined kinds to search.

    Returns
    -------
    QuantityKindInfo | None
        The matching kind, or None if not found.
    """
    if not session_kinds:
        return None

    # Check by name
    if name in session_kinds:
        return session_kinds[name]

    # Check aliases
    for kind in session_kinds.values():
        if name in kind.aliases:
            return kind

    return None


def get_kinds_by_dimension(
    dimension_vector: str,
    session_kinds: dict[str, QuantityKindInfo] | None = None,
) -> list[QuantityKindInfo]:
    """Get all quantity kinds with a given dimension vector.

    Parameters
    ----------
    dimension_vector : str
        The dimensional signature to match.
    session_kinds : dict[str, QuantityKindInfo] | None
        Session-defined kinds to search.

    Returns
    -------
    list[QuantityKindInfo]
        All matching quantity kinds.
    """
    if not session_kinds:
        return []

    return [
        kind for kind in session_kinds.values()
        if kind.dimension_vector == dimension_vector
    ]


# -----------------------------------------------------------------------------
# Semantic Keywords for Validation
# -----------------------------------------------------------------------------

# Keywords that suggest specific quantity kinds (used for semantic validation)
SEMANTIC_KEYWORDS: dict[str, set[str]] = {
    "enthalpy": {"enthalpy", "ΔH", "delta H", "heat of", "combustion", "formation", "reaction enthalpy"},
    "gibbs_energy": {"gibbs", "ΔG", "delta G", "free energy", "spontaneous", "equilibrium constant"},
    "helmholtz_energy": {"helmholtz", "ΔA", "delta A", "constant volume free"},
    "chemical_potential": {"chemical potential", "μ", "partial molar"},
    "entropy_change": {"entropy", "ΔS", "delta S", "disorder"},
    "activation_energy": {"activation", "Ea", "arrhenius", "rate constant", "kinetics"},
    "bond_energy": {"bond", "dissociation", "BDE", "bond strength"},
    "internal_energy": {"internal energy", "ΔU", "delta U", "constant volume"},
    "work": {"work", "force", "displacement", "W ="},
    "torque": {"torque", "moment", "rotational", "τ"},
    "heat": {"heat", "thermal", "q =", "calorimeter"},
}


def check_semantic_conflicts(
    declared_kind: str,
    reasoning: str,
) -> list[str]:
    """Check if reasoning text conflicts with declared quantity kind.

    The check is context-aware: if the declared kind's keywords are present
    in the reasoning (e.g., "ΔG" for gibbs_energy), mentions of related
    quantities like "ΔH" are likely describing a formula, not confusion.
    Warnings are only generated when the declared kind's keywords are absent
    but conflicting keywords are present.

    Parameters
    ----------
    declared_kind : str
        The declared quantity kind name.
    reasoning : str
        The reasoning text to analyze.

    Returns
    -------
    list[str]
        Warning messages for any detected conflicts.
    """
    if not reasoning:
        return []

    reasoning_lower = reasoning.lower()

    # Check if the declared kind's keywords are present
    declared_keywords = SEMANTIC_KEYWORDS.get(declared_kind, set())
    declared_kind_mentioned = any(
        keyword.lower() in reasoning_lower for keyword in declared_keywords
    )

    # If the declared kind is explicitly mentioned, be lenient about related terms
    # (user is likely describing a formula involving multiple quantities)
    if declared_kind_mentioned:
        return []

    warnings = []
    for kind_name, keywords in SEMANTIC_KEYWORDS.items():
        if kind_name == declared_kind:
            continue

        for keyword in keywords:
            if keyword.lower() in reasoning_lower:
                warnings.append(
                    f"Reasoning mentions '{keyword}' which is associated with "
                    f"'{kind_name}', but declared kind is '{declared_kind}'"
                )
                break  # One warning per conflicting kind

    return warnings

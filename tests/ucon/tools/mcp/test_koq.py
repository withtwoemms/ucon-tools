# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for KOQ (Kind-of-Quantity) MCP tools.

Tests the KOQ tool functions directly without running the full MCP server.
These tests are skipped if the mcp package is not installed.

Quantity kinds are defined on-demand per session, following the same
pattern as custom unit creation.
"""

import unittest


class TestDefineQuantityKind(unittest.TestCase):
    """Test the define_quantity_kind tool."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                define_quantity_kind,
                _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import (
                QuantityKindDefinitionResult,
                KOQError,
            )
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.QuantityKindDefinitionResult = QuantityKindDefinitionResult
            cls.KOQError = KOQError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def test_define_custom_kind_success(self):
        """Test defining a custom quantity kind successfully."""
        result = self.define_quantity_kind(
            name="reaction_enthalpy",
            dimension="energy/amount_of_substance",
            description="Enthalpy change for a chemical reaction",
            aliases=["delta_H_rxn"],
            category="thermodynamic",
            disambiguation_hints=["Use for heat at constant pressure"],
        )
        self.assertIsInstance(result, self.QuantityKindDefinitionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.name, "reaction_enthalpy")
        self.assertEqual(result.dimension, "energy/amount_of_substance")
        self.assertEqual(result.vector_signature, "M·L²·T⁻²·N⁻¹")
        self.assertEqual(result.category, "thermodynamic")

    def test_define_kind_with_vector_notation(self):
        """Test defining a kind using vector notation for dimension."""
        result = self.define_quantity_kind(
            name="custom_energy_kind",
            dimension="M·L²·T⁻²",
            description="Custom energy quantity",
        )
        self.assertIsInstance(result, self.QuantityKindDefinitionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.vector_signature, "M·L²·T⁻²")

    def test_duplicate_session_name_rejected(self):
        """Test that duplicate session kind name is rejected."""
        # Define first
        self.define_quantity_kind(
            name="my_kind",
            dimension="energy",
            description="First definition",
        )
        # Try to define again
        result = self.define_quantity_kind(
            name="my_kind",
            dimension="energy",
            description="Second definition",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "duplicate_kind")

    def test_invalid_dimension_rejected(self):
        """Test that invalid dimension string is rejected."""
        result = self.define_quantity_kind(
            name="bad_kind",
            dimension="not_a_dimension",
            description="Bad dimension",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "invalid_dimension")


class TestDeclareComputation(unittest.TestCase):
    """Test the declare_computation tool."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                define_quantity_kind,
                declare_computation,
                _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import (
                ComputationDeclaration,
                KOQError,
            )
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls.declare_computation = staticmethod(declare_computation)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.ComputationDeclaration = ComputationDeclaration
            cls.KOQError = KOQError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def _define_thermodynamic_kinds(self):
        """Helper to define common thermodynamic kinds for testing."""
        self.define_quantity_kind(
            name="gibbs_energy",
            dimension="energy/amount_of_substance",
            description="Gibbs free energy",
            category="thermodynamic",
        )
        self.define_quantity_kind(
            name="enthalpy",
            dimension="energy/amount_of_substance",
            description="Enthalpy",
            category="thermodynamic",
        )
        self.define_quantity_kind(
            name="helmholtz_energy",
            dimension="energy/amount_of_substance",
            description="Helmholtz free energy",
            category="thermodynamic",
        )

    def test_declare_session_kind_success(self):
        """Test declaring computation with session-defined kind."""
        self._define_thermodynamic_kinds()

        result = self.declare_computation(
            quantity_kind="gibbs_energy",
            expected_unit="kJ/mol",
        )
        self.assertIsInstance(result, self.ComputationDeclaration)
        self.assertEqual(result.quantity_kind, "gibbs_energy")
        self.assertEqual(result.expected_unit, "kJ/mol")
        self.assertIsNotNone(result.declaration_id)

    def test_declare_with_context(self):
        """Test declaring computation with context information."""
        self._define_thermodynamic_kinds()

        result = self.declare_computation(
            quantity_kind="enthalpy",
            expected_unit="J/mol",
            context={"temperature": "298 K", "pressure": "1 bar"},
        )
        self.assertIsInstance(result, self.ComputationDeclaration)
        self.assertEqual(result.quantity_kind, "enthalpy")

    def test_declares_compatible_kinds_warning(self):
        """Test that declaration warns about compatible kinds."""
        self._define_thermodynamic_kinds()

        result = self.declare_computation(
            quantity_kind="gibbs_energy",
            expected_unit="kJ/mol",
        )
        self.assertIsInstance(result, self.ComputationDeclaration)
        # Should warn about enthalpy, helmholtz_energy (same dimension)
        self.assertGreater(len(result.compatible_kinds), 0)
        self.assertIn("enthalpy", result.compatible_kinds)

    def test_unknown_kind_rejected(self):
        """Test that unknown quantity kind is rejected."""
        result = self.declare_computation(
            quantity_kind="nonexistent_kind",
            expected_unit="J",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "unknown_kind")

    def test_invalid_unit_rejected(self):
        """Test that invalid expected_unit is rejected."""
        self._define_thermodynamic_kinds()

        result = self.declare_computation(
            quantity_kind="enthalpy",
            expected_unit="not_a_unit",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "invalid_unit")

    def test_status_warning_with_compatible_kinds(self):
        """Test that status is 'warning' when compatible kinds exist."""
        self._define_thermodynamic_kinds()

        result = self.declare_computation(
            quantity_kind="gibbs_energy",
            expected_unit="kJ/mol",
        )
        self.assertIsInstance(result, self.ComputationDeclaration)
        # Should have warning status due to compatible kinds
        self.assertEqual(result.status, "warning")


class TestValidateResult(unittest.TestCase):
    """Test the validate_result tool."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                define_quantity_kind,
                declare_computation,
                validate_result,
                _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import (
                ValidationResult,
                KOQError,
            )
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls.declare_computation = staticmethod(declare_computation)
            cls.validate_result = staticmethod(validate_result)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.ValidationResult = ValidationResult
            cls.KOQError = KOQError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def _define_thermodynamic_kinds(self):
        """Helper to define common thermodynamic kinds for testing."""
        self.define_quantity_kind(
            name="gibbs_energy",
            dimension="energy/amount_of_substance",
            description="Gibbs free energy",
            category="thermodynamic",
        )
        self.define_quantity_kind(
            name="enthalpy",
            dimension="energy/amount_of_substance",
            description="Enthalpy",
            category="thermodynamic",
        )

    def test_validate_with_active_declaration(self):
        """Test validation using active declaration."""
        self._define_thermodynamic_kinds()

        # First declare
        self.declare_computation(
            quantity_kind="gibbs_energy",
            expected_unit="kJ/mol",
        )
        # Then validate
        result = self.validate_result(
            value=-228.6,
            unit="kJ/mol",
        )
        self.assertIsInstance(result, self.ValidationResult)
        self.assertTrue(result.passed)
        self.assertTrue(result.dimension_match)
        self.assertEqual(result.declared_kind, "gibbs_energy")

    def test_validate_with_explicit_kind(self):
        """Test validation with explicit declared_kind parameter."""
        self._define_thermodynamic_kinds()

        result = self.validate_result(
            value=100.0,
            unit="J/mol",
            declared_kind="enthalpy",
        )
        self.assertIsInstance(result, self.ValidationResult)
        self.assertTrue(result.passed)
        self.assertEqual(result.declared_kind, "enthalpy")

    def test_validate_without_declaration_or_kind_fails(self):
        """Test that validation fails without declaration or explicit kind."""
        result = self.validate_result(
            value=100.0,
            unit="J/mol",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "no_active_declaration")

    def test_validate_dimension_mismatch(self):
        """Test that dimension mismatch is detected."""
        self._define_thermodynamic_kinds()

        result = self.validate_result(
            value=100.0,
            unit="m/s",  # velocity, not energy
            declared_kind="enthalpy",
        )
        self.assertIsInstance(result, self.ValidationResult)
        self.assertFalse(result.passed)
        self.assertFalse(result.dimension_match)
        self.assertEqual(result.confidence, "low")

    def test_validate_with_reasoning_no_conflict(self):
        """Test validation with consistent reasoning."""
        self._define_thermodynamic_kinds()

        result = self.validate_result(
            value=-228.6,
            unit="kJ/mol",
            declared_kind="gibbs_energy",
            reasoning="Calculated ΔG = ΔH - TΔS at standard conditions",
        )
        self.assertIsInstance(result, self.ValidationResult)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.semantic_warnings), 0)
        self.assertEqual(result.confidence, "high")

    def test_validate_with_reasoning_conflict(self):
        """Test validation detects reasoning conflicts."""
        self._define_thermodynamic_kinds()

        result = self.validate_result(
            value=-228.6,
            unit="kJ/mol",
            declared_kind="gibbs_energy",
            reasoning="Calculated the enthalpy of formation",  # Mentions enthalpy!
        )
        self.assertIsInstance(result, self.ValidationResult)
        self.assertTrue(result.passed)  # Dimension matches
        self.assertGreater(len(result.semantic_warnings), 0)
        self.assertEqual(result.confidence, "medium")

    def test_validate_clears_active_declaration(self):
        """Test that validation clears the active declaration."""
        self._define_thermodynamic_kinds()

        # Declare
        self.declare_computation(
            quantity_kind="enthalpy",
            expected_unit="kJ/mol",
        )
        # Validate
        self.validate_result(
            value=100.0,
            unit="kJ/mol",
        )
        # Second validate should fail (no active declaration)
        result = self.validate_result(
            value=200.0,
            unit="kJ/mol",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "no_active_declaration")

    def test_validate_unknown_kind_rejected(self):
        """Test that unknown declared_kind is rejected."""
        result = self.validate_result(
            value=100.0,
            unit="J",
            declared_kind="nonexistent_kind",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "unknown_kind")


class TestListQuantityKinds(unittest.TestCase):
    """Test the list_quantity_kinds tool."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                list_quantity_kinds,
                define_quantity_kind,
                _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import KOQError
            cls.list_quantity_kinds = staticmethod(list_quantity_kinds)
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.KOQError = KOQError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def test_list_empty_session(self):
        """Test listing kinds when no kinds are defined."""
        result = self.list_quantity_kinds()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_list_session_kinds(self):
        """Test that list includes session-defined kinds."""
        # Define session kinds
        self.define_quantity_kind(
            name="my_custom_kind",
            dimension="energy",
            description="Custom kind for testing",
            category="custom",
        )

        result = self.list_quantity_kinds()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

        kind = result[0]
        self.assertEqual(kind["name"], "my_custom_kind")
        self.assertIn("dimension_vector", kind)
        self.assertIn("description", kind)
        self.assertIn("category", kind)

    def test_filter_by_dimension(self):
        """Test filtering by dimension."""
        # Define kinds with different dimensions
        self.define_quantity_kind(
            name="enthalpy",
            dimension="energy/amount_of_substance",
            description="Enthalpy",
        )
        self.define_quantity_kind(
            name="work",
            dimension="energy",
            description="Work",
        )

        result = self.list_quantity_kinds(dimension="energy/amount_of_substance")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "enthalpy")

    def test_filter_by_category(self):
        """Test filtering by category."""
        self.define_quantity_kind(
            name="enthalpy",
            dimension="energy/amount_of_substance",
            description="Enthalpy",
            category="thermodynamic",
        )
        self.define_quantity_kind(
            name="work",
            dimension="energy",
            description="Work",
            category="mechanical",
        )

        result = self.list_quantity_kinds(category="thermodynamic")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "enthalpy")

    def test_filter_by_dimension_and_category(self):
        """Test filtering by both dimension and category."""
        self.define_quantity_kind(
            name="enthalpy",
            dimension="energy/amount_of_substance",
            description="Enthalpy",
            category="thermodynamic",
        )
        self.define_quantity_kind(
            name="gibbs_energy",
            dimension="energy/amount_of_substance",
            description="Gibbs energy",
            category="thermodynamic",
        )
        self.define_quantity_kind(
            name="bond_energy",
            dimension="energy/amount_of_substance",
            description="Bond energy",
            category="chemical",
        )

        result = self.list_quantity_kinds(
            dimension="energy/amount_of_substance",
            category="thermodynamic",
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        names = [k["name"] for k in result]
        self.assertIn("enthalpy", names)
        self.assertIn("gibbs_energy", names)
        self.assertNotIn("bond_energy", names)


class TestExtendBasis(unittest.TestCase):
    """Test the extend_basis tool."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                extend_basis,
                list_extended_bases,
                _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import (
                ExtendedBasisResult,
                KOQError,
            )
            cls.extend_basis = staticmethod(extend_basis)
            cls.list_extended_bases = staticmethod(list_extended_bases)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.ExtendedBasisResult = ExtendedBasisResult
            cls.KOQError = KOQError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def test_extend_si_basis(self):
        """Test extending SI basis."""
        result = self.extend_basis(
            name="thermodynamic_basis",
            base="SI",
            additional_components=[
                {"name": "thermal", "symbol": "Φ", "description": "Thermal marker"},
            ],
        )
        self.assertIsInstance(result, self.ExtendedBasisResult)
        self.assertTrue(result.success)
        self.assertEqual(result.name, "thermodynamic_basis")
        self.assertEqual(result.base, "SI")
        self.assertIn("Φ (thermal)", result.components)

    def test_extend_with_multiple_components(self):
        """Test extending with multiple additional components."""
        result = self.extend_basis(
            name="chemical_basis",
            base="SI",
            additional_components=[
                {"name": "thermal", "symbol": "Φ", "description": "Thermal marker"},
                {"name": "mechanical", "symbol": "Ψ", "description": "Mechanical marker"},
            ],
        )
        self.assertIsInstance(result, self.ExtendedBasisResult)
        self.assertTrue(result.success)
        # ucon's SI basis has 8 components (M, L, T, I, Θ, J, N, B) + 2 additional
        self.assertEqual(len(result.components), 10)

    def test_unknown_base_rejected(self):
        """Test that unknown base is rejected."""
        result = self.extend_basis(
            name="bad_basis",
            base="INVALID",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "unknown_base")

    def test_dynamic_basis_persists_in_session(self):
        """Test that a created basis persists in the session."""
        # Create a basis
        self.extend_basis(
            name="my_dynamic_basis",
            base="SI",
            additional_components=[
                {"name": "custom", "symbol": "X", "description": "Custom component"},
            ],
        )

        # Verify it exists in session via list_extended_bases
        bases = self.list_extended_bases()
        self.assertEqual(len(bases), 1)
        self.assertEqual(bases[0]["name"], "my_dynamic_basis")
        self.assertEqual(bases[0]["base"], "SI")
        self.assertIn("X (custom)", bases[0]["components"])

    def test_multiple_bases_can_be_created(self):
        """Test that multiple bases can be created in the same session."""
        # Create first basis
        self.extend_basis(
            name="basis_one",
            base="SI",
            additional_components=[
                {"name": "marker_a", "symbol": "A", "description": "First marker"},
            ],
        )
        # Create second basis (symbol Q chosen to avoid collision with SI 'B' for information)
        self.extend_basis(
            name="basis_two",
            base="SI",
            additional_components=[
                {"name": "marker_b", "symbol": "Q", "description": "Second marker"},
            ],
        )

        # Both should exist
        bases = self.list_extended_bases()
        self.assertEqual(len(bases), 2)
        names = [b["name"] for b in bases]
        self.assertIn("basis_one", names)
        self.assertIn("basis_two", names)

    def test_duplicate_basis_name_rejected(self):
        """Test that duplicate basis name is rejected."""
        # Create first basis
        self.extend_basis(
            name="unique_basis",
            base="SI",
            additional_components=[],
        )
        # Try to create with same name
        result = self.extend_basis(
            name="unique_basis",
            base="SI",
            additional_components=[],
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "duplicate_basis")

    def test_list_empty_when_no_bases(self):
        """Test that list_extended_bases returns empty list when no bases exist."""
        bases = self.list_extended_bases()
        self.assertIsInstance(bases, list)
        self.assertEqual(len(bases), 0)


class TestKOQWorkflow(unittest.TestCase):
    """Test the complete KOQ workflow: define → declare → compute → validate."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                define_quantity_kind,
                declare_computation,
                validate_result,
                compute,
                _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import (
                ComputationDeclaration,
                ValidationResult,
            )
            from ucon.tools.mcp.server import ComputeResult
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls.declare_computation = staticmethod(declare_computation)
            cls.validate_result = staticmethod(validate_result)
            cls.compute = staticmethod(compute)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.ComputationDeclaration = ComputationDeclaration
            cls.ValidationResult = ValidationResult
            cls.ComputeResult = ComputeResult
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def test_complete_workflow_success(self):
        """Test complete define → declare → compute → validate workflow."""
        # Step 0: Define quantity kind
        self.define_quantity_kind(
            name="work",
            dimension="energy",
            description="Mechanical work",
            category="mechanical",
        )

        # Step 1: Declare computation
        decl = self.declare_computation(
            quantity_kind="work",
            expected_unit="J",
        )
        self.assertIsInstance(decl, self.ComputationDeclaration)
        self.assertEqual(decl.quantity_kind, "work")

        # Step 2: Compute (force × distance)
        # 100 N × 5 m = 500 J
        compute_result = self.compute(
            initial_value=100,
            initial_unit="N",
            factors=[
                {"value": 5, "numerator": "m", "denominator": "1 ea"},
            ],
        )
        self.assertIsInstance(compute_result, self.ComputeResult)
        self.assertAlmostEqual(compute_result.quantity, 500.0)

        # Step 3: Validate result
        validation = self.validate_result(
            value=compute_result.quantity,
            unit="J",
            reasoning="Calculated work = force × displacement",
        )
        self.assertIsInstance(validation, self.ValidationResult)
        self.assertTrue(validation.passed)
        self.assertEqual(validation.confidence, "high")

    def test_workflow_with_semantic_warning(self):
        """Test workflow where reasoning conflicts with declared kind."""
        # Define kinds
        self.define_quantity_kind(
            name="work",
            dimension="energy",
            description="Mechanical work",
        )
        self.define_quantity_kind(
            name="torque",
            dimension="energy",
            description="Rotational force",
        )

        # Declare as work
        self.declare_computation(
            quantity_kind="work",
            expected_unit="J",
        )

        # Validate with reasoning mentioning torque
        validation = self.validate_result(
            value=500.0,
            unit="J",
            reasoning="Calculated torque = r × F",  # Says torque!
        )
        self.assertIsInstance(validation, self.ValidationResult)
        self.assertTrue(validation.passed)  # Dimension still matches
        self.assertEqual(validation.confidence, "medium")  # But confidence reduced
        self.assertGreater(len(validation.semantic_warnings), 0)


class TestKOQSessionReset(unittest.TestCase):
    """Test that reset_session clears KOQ state."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                define_quantity_kind,
                declare_computation,
                validate_result,
                reset_session,
                list_quantity_kinds,
                extend_basis,
                list_extended_bases,
                _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import KOQError
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls.declare_computation = staticmethod(declare_computation)
            cls.validate_result = staticmethod(validate_result)
            cls.reset_session = staticmethod(reset_session)
            cls.list_quantity_kinds = staticmethod(list_quantity_kinds)
            cls.extend_basis = staticmethod(extend_basis)
            cls.list_extended_bases = staticmethod(list_extended_bases)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.KOQError = KOQError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def test_reset_clears_session_kinds(self):
        """Test that reset_session clears session-defined kinds."""
        # Define a session kind
        self.define_quantity_kind(
            name="session_kind",
            dimension="energy",
            description="Session kind",
        )

        # Verify it exists
        kinds = self.list_quantity_kinds()
        names = [k["name"] for k in kinds]
        self.assertIn("session_kind", names)

        # Reset session
        self.reset_session()

        # Verify it's gone
        kinds = self.list_quantity_kinds()
        self.assertEqual(len(kinds), 0)

    def test_reset_clears_active_computation(self):
        """Test that reset_session clears active computation."""
        # Define and declare
        self.define_quantity_kind(
            name="enthalpy",
            dimension="energy/amount_of_substance",
            description="Enthalpy",
        )
        self.declare_computation(
            quantity_kind="enthalpy",
            expected_unit="kJ/mol",
        )

        # Reset session
        self.reset_session()

        # Validate should fail (no active declaration)
        result = self.validate_result(
            value=100.0,
            unit="kJ/mol",
        )
        self.assertIsInstance(result, self.KOQError)
        self.assertEqual(result.error_type, "no_active_declaration")

    def test_reset_clears_extended_bases(self):
        """Test that reset_session clears extended bases."""
        # Create an extended basis
        self.extend_basis(
            name="session_basis",
            base="SI",
            additional_components=[
                {"name": "marker", "symbol": "Ω", "description": "Test marker"},
            ],
        )

        # Verify it exists
        bases = self.list_extended_bases()
        self.assertEqual(len(bases), 1)

        # Reset session
        self.reset_session()

        # Verify it's gone
        bases = self.list_extended_bases()
        self.assertEqual(len(bases), 0)


# -----------------------------------------------------------------------------
# KOQ helper function edge cases
# -----------------------------------------------------------------------------


class TestKOQEdgeCases(unittest.TestCase):
    """Test KOQ helper functions with edge-case inputs."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.koq import (
                get_quantity_kind, get_kinds_by_dimension,
                check_semantic_conflicts, QuantityKindInfo,
            )
            cls.get_quantity_kind = staticmethod(get_quantity_kind)
            cls.get_kinds_by_dimension = staticmethod(get_kinds_by_dimension)
            cls.check_semantic_conflicts = staticmethod(check_semantic_conflicts)
            cls.QuantityKindInfo = QuantityKindInfo
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")

    def test_get_quantity_kind_by_alias(self):
        """get_quantity_kind finds a kind by its alias."""
        kinds = {
            "test_kind": self.QuantityKindInfo(
                name="test_kind",
                dimension_name="energy",
                dimension_vector="M·L²·T⁻²",
                description="test",
                aliases=("alt_name", "other_name"),
                category="session",
            )
        }
        result = self.get_quantity_kind("alt_name", session_kinds=kinds)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "test_kind")

    def test_get_quantity_kind_not_found(self):
        """get_quantity_kind returns None for unknown name."""
        kinds = {
            "test_kind": self.QuantityKindInfo(
                name="test_kind",
                dimension_name="energy",
                dimension_vector="M·L²·T⁻²",
                description="test",
            )
        }
        result = self.get_quantity_kind("nonexistent", session_kinds=kinds)
        self.assertIsNone(result)

    def test_get_kinds_by_dimension_empty_session(self):
        """get_kinds_by_dimension returns [] when session_kinds is None."""
        result = self.get_kinds_by_dimension("M·L²·T⁻²", session_kinds=None)
        self.assertEqual(result, [])

    def test_check_semantic_conflicts_empty_reasoning(self):
        """check_semantic_conflicts returns [] for empty reasoning."""
        result = self.check_semantic_conflicts("gibbs_energy", "")
        self.assertEqual(result, [])

    def test_check_semantic_conflicts_none_reasoning(self):
        """check_semantic_conflicts returns [] for None-like reasoning."""
        result = self.check_semantic_conflicts("gibbs_energy", "")
        self.assertEqual(result, [])


# -----------------------------------------------------------------------------
# KOQ MCP tool endpoint edge cases
# -----------------------------------------------------------------------------


class TestKOQMCPToolEdgeCases(unittest.TestCase):
    """Test KOQ MCP tool endpoints for edge cases."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                define_quantity_kind, declare_computation, validate_result,
                list_quantity_kinds, _reset_fallback_session,
            )
            from ucon.tools.mcp.koq import KOQError
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls.declare_computation = staticmethod(declare_computation)
            cls.validate_result = staticmethod(validate_result)
            cls.list_quantity_kinds = staticmethod(list_quantity_kinds)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls.KOQError = KOQError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")
        self._reset_fallback_session()

    def tearDown(self):
        if not self.skip_tests:
            self._reset_fallback_session()

    def test_declare_unknown_kind(self):
        """declare_computation with unknown kind returns KOQError."""
        result = self.declare_computation(
            quantity_kind="nonexistent_kind",
            expected_unit="J/mol",
        )
        self.assertIsInstance(result, self.KOQError)

    def test_validate_result_unknown_unit(self):
        """validate_result with unknown unit returns KOQError."""
        self.define_quantity_kind(
            name="test_energy",
            dimension="energy",
            description="test",
        )
        self.declare_computation(
            quantity_kind="test_energy",
            expected_unit="J",
        )
        result = self.validate_result(
            value=100.0,
            unit="foobar_unit",
        )
        self.assertIsInstance(result, self.KOQError)

    def test_list_quantity_kinds_bad_dimension_filter(self):
        """list_quantity_kinds with unrecognizable dimension filter."""
        result = self.list_quantity_kinds(dimension="xyzzy_dim_999")
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()

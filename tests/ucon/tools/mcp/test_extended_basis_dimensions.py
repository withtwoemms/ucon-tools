# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""
Tests for extended-basis dimensions as first-class citizens.

Verifies that dimensions registered via ``extend_basis()`` are recognized
across the MCP tool surface: ``define_unit``, ``define_quantity_kind``,
``define_conversion``, ``convert``, ``list_units``, ``list_dimensions``,
and the dimension parser/normalizer/vector helpers.

These tests cover the wire-through of session-scoped dimensions from the
``SessionState`` into every site that previously only consulted the
built-in dimension registry.
"""

import unittest


class _ExtBasisTestBase(unittest.TestCase):
    """Shared setup: import all relevant tool functions and reset session."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import (
                extend_basis,
                define_unit,
                define_conversion,
                define_quantity_kind,
                list_units,
                list_dimensions,
                list_extended_bases,
                convert,
                reset_session,
                _reset_fallback_session,
                _get_session,
                _parse_dimension_to_vector,
                _normalize_dimension_vector,
                _get_dimension_vector,
                _all_known_dimensions,
            )
            from ucon.tools.mcp.suggestions import (
                ConversionError,
                build_unknown_dimension_error,
            )
            from ucon.tools.mcp.koq import (
                ExtendedBasisResult,
                QuantityKindDefinitionResult,
                KOQError,
            )

            cls.extend_basis = staticmethod(extend_basis)
            cls.define_unit = staticmethod(define_unit)
            cls.define_conversion = staticmethod(define_conversion)
            cls.define_quantity_kind = staticmethod(define_quantity_kind)
            cls.list_units = staticmethod(list_units)
            cls.list_dimensions = staticmethod(list_dimensions)
            cls.list_extended_bases = staticmethod(list_extended_bases)
            cls.convert = staticmethod(convert)
            cls.reset_session = staticmethod(reset_session)
            cls._reset_fallback_session = staticmethod(_reset_fallback_session)
            cls._get_session = staticmethod(_get_session)
            cls._parse_dimension_to_vector = staticmethod(_parse_dimension_to_vector)
            cls._normalize_dimension_vector = staticmethod(_normalize_dimension_vector)
            cls._get_dimension_vector = staticmethod(_get_dimension_vector)
            cls._all_known_dimensions = staticmethod(_all_known_dimensions)
            cls.build_unknown_dimension_error = staticmethod(build_unknown_dimension_error)

            cls.ExtendedBasisResult = ExtendedBasisResult
            cls.QuantityKindDefinitionResult = QuantityKindDefinitionResult
            cls.KOQError = KOQError
            cls.ConversionError = ConversionError

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

    # ---------------- Helpers ----------------

    def _extend_currency(self):
        """Register an extended basis with a 'currency' component (symbol '$')."""
        return self.extend_basis(
            name="economic_basis",
            base="SI",
            additional_components=[
                {"name": "currency", "symbol": "$", "description": "Money marker"},
            ],
        )


class TestDefineUnitWithExtendedDimension(_ExtBasisTestBase):
    """define_unit() must accept dimensions registered via extend_basis()."""

    def test_extend_then_define_unit(self):
        """define_unit(dimension="currency") succeeds after extend_basis."""
        self._extend_currency()

        from ucon.tools.mcp.server import UnitDefinitionResult

        result = self.define_unit(name="dollar", dimension="currency", aliases=["USD"])
        self.assertIsInstance(result, UnitDefinitionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.name, "dollar")
        self.assertEqual(result.dimension, "currency")
        self.assertIn("USD", result.aliases)

    def test_define_unit_unknown_dimension_still_rejected(self):
        """Without an extending basis, unknown dimension is still an error."""
        # No extend_basis call here — currency is not known
        result = self.define_unit(name="dollar", dimension="currency")
        self.assertIsInstance(result, self.ConversionError)
        self.assertEqual(result.error_type, "unknown_unit")


class TestListVisibility(_ExtBasisTestBase):
    """Extended dimensions and their units appear in list_* tools."""

    def test_extended_dim_in_list_dimensions(self):
        """list_dimensions() includes 'currency' after extend_basis."""
        self._extend_currency()

        dims = self.list_dimensions()
        self.assertIsInstance(dims, list)
        self.assertIn("currency", dims)
        # Built-in dims should still be present
        self.assertIn("mass", dims)
        self.assertIn("time", dims)

    def test_extended_dim_in_list_units_filter(self):
        """list_units(dimension='currency') returns units in that dimension."""
        self._extend_currency()
        self.define_unit(name="dollar", dimension="currency", aliases=["USD"])
        self.define_unit(name="euro", dimension="currency", aliases=["EUR"])

        units = self.list_units(dimension="currency")
        self.assertIsInstance(units, list)
        names = sorted(u.name for u in units)
        self.assertEqual(names, ["dollar", "euro"])
        for u in units:
            self.assertEqual(u.dimension, "currency")


class TestQuantityKindWithExtendedDimension(_ExtBasisTestBase):
    """define_quantity_kind accepts extended symbols and compound expressions."""

    def test_define_quantity_kind_extended_dim(self):
        """define_quantity_kind(dimension='$') succeeds with an extended symbol."""
        self._extend_currency()

        result = self.define_quantity_kind(
            name="price",
            dimension="$",
            description="Monetary price",
        )
        self.assertIsInstance(result, self.QuantityKindDefinitionResult)
        self.assertTrue(result.success)
        # Vector signature should include the extended symbol
        self.assertIn("$", result.vector_signature)

    def test_compound_extended_dim(self):
        """define_quantity_kind(dimension='currency/time') produces a vector
        with the time-inverse and currency components.

        Canonical ordering puts SI symbols before extended ones (per the
        Step 8 prescription), so the resulting vector is 'T⁻¹·$' rather
        than '$·T⁻¹' (which the plan's table column listed as a shorthand).
        """
        self._extend_currency()

        result = self.define_quantity_kind(
            name="burn_rate",
            dimension="currency/time",
            description="Cash burn rate",
        )
        self.assertIsInstance(result, self.QuantityKindDefinitionResult)
        self.assertTrue(result.success)
        # SI symbols come first in canonical order, extended symbols append
        self.assertEqual(result.vector_signature, "T⁻¹·$")


class TestEndToEndConversion(_ExtBasisTestBase):
    """Extended-dim units participate in the full conversion pipeline."""

    def test_define_conversion_extended_units(self):
        """Full workflow: extend, define 2 units, define conversion, convert."""
        self._extend_currency()
        self.define_unit(name="dollar", dimension="currency", aliases=["USD"])
        self.define_unit(name="cent", dimension="currency", aliases=["c"])

        # 1 dollar = 100 cents
        conv = self.define_conversion(src="dollar", dst="cent", factor=100.0)
        # Sanity-check the edge was registered (no error)
        self.assertFalse(isinstance(conv, self.ConversionError))

        from ucon.tools.mcp.server import ConversionResult

        result = self.convert(value=2.5, from_unit="dollar", to_unit="cent")
        self.assertIsInstance(result, ConversionResult)
        self.assertAlmostEqual(result.quantity, 250.0)


class TestParserPapercuts(_ExtBasisTestBase):
    """Parser-level papercuts for compound, bare-symbol, and dimensionless inputs."""

    def test_parse_compound_slash(self):
        """_parse_dimension_to_vector('mass/time') returns 'M·T⁻¹'."""
        result = self._parse_dimension_to_vector("mass/time")
        self.assertEqual(result, "M·T⁻¹")

    def test_parse_compound_star(self):
        """_parse_dimension_to_vector('mass*length') returns 'M·L'."""
        result = self._parse_dimension_to_vector("mass*length")
        self.assertEqual(result, "M·L")

    def test_parse_bare_symbol(self):
        """_parse_dimension_to_vector('M') returns 'M'."""
        self.assertEqual(self._parse_dimension_to_vector("M"), "M")
        self.assertEqual(self._parse_dimension_to_vector("L"), "L")
        self.assertEqual(self._parse_dimension_to_vector("T"), "T")

    def test_parse_dimensionless(self):
        """'dimensionless', '1', and '' all return '1'."""
        self.assertEqual(self._parse_dimension_to_vector("dimensionless"), "1")
        self.assertEqual(self._parse_dimension_to_vector("1"), "1")
        self.assertEqual(self._parse_dimension_to_vector(""), "1")
        # Whitespace-only and case-insensitive variants
        self.assertEqual(self._parse_dimension_to_vector("  "), "1")
        self.assertEqual(self._parse_dimension_to_vector("Dimensionless"), "1")


class TestNormalizationAndVectorRendering(_ExtBasisTestBase):
    """Vector normalization and rendering recognize extended symbols."""

    def test_normalize_extended_symbol(self):
        """A vector containing an extended symbol normalizes with SI first,
        extended after."""
        self._extend_currency()

        ctx = None  # session lookup uses fallback
        session = self._get_session(ctx)
        # Mixed input ordering: extended symbol before SI inverse
        normalized = self._normalize_dimension_vector("$·T⁻¹", session=session)
        self.assertEqual(normalized, "T⁻¹·$")

    def test_normalize_unknown_symbol_when_no_session(self):
        """Without session, extended symbols are not recognized — they drop."""
        # No session passed; "$" is unknown to the SI-only normalizer.
        normalized = self._normalize_dimension_vector("$·T⁻¹")
        # Should still contain T⁻¹; '$' is dropped.
        self.assertEqual(normalized, "T⁻¹")

    def test_get_dimension_vector_extended(self):
        """_get_dimension_vector() includes the extended component symbol
        when the unit's dimension is session-scoped."""
        self._extend_currency()
        self.define_unit(name="dollar", dimension="currency")

        session = self._get_session(None)
        graph = session.get_graph()
        resolved = graph.resolve_unit("dollar")
        self.assertIsNotNone(resolved)
        unit, _ = resolved

        vec = self._get_dimension_vector(unit)
        self.assertIn("$", vec)


class TestSessionLifecycle(_ExtBasisTestBase):
    """Session reset clears extended-basis state."""

    def test_reset_clears_session_dimensions(self):
        """reset_session() clears all session dimensions."""
        self._extend_currency()
        # Confirm currency is visible before reset
        dims_before = self.list_dimensions()
        self.assertIn("currency", dims_before)

        self.reset_session()

        # Currency should be gone
        dims_after = self.list_dimensions()
        self.assertNotIn("currency", dims_after)
        # And re-registering a unit against currency should now fail
        result = self.define_unit(name="dollar", dimension="currency")
        self.assertIsInstance(result, self.ConversionError)


class TestBackwardCompatibility(_ExtBasisTestBase):
    """SI-only flows behave identically when no basis has been extended."""

    def test_backward_compat_si_only(self):
        """All standard SI flows produce expected results when no extension exists."""
        # list_dimensions returns standard built-ins
        dims = self.list_dimensions()
        for expected in ("mass", "length", "time", "temperature"):
            self.assertIn(expected, dims)
        self.assertNotIn("currency", dims)

        # define_unit with built-in dimension still works
        from ucon.tools.mcp.server import UnitDefinitionResult

        unit_result = self.define_unit(name="zog_mass", dimension="mass", aliases=["zog"])
        self.assertIsInstance(unit_result, UnitDefinitionResult)
        self.assertTrue(unit_result.success)

        # _parse_dimension_to_vector for a known compound still works without session
        self.assertEqual(
            self._parse_dimension_to_vector("energy/amount_of_substance"),
            "M·L²·T⁻²·N⁻¹",
        )


class TestErrorSuggestionsIncludeExtended(_ExtBasisTestBase):
    """Unknown-dimension error suggestions union session dims with built-ins."""

    def test_unknown_dim_suggests_extended(self):
        """build_unknown_dimension_error('currenc') suggests 'currency' when
        an extended basis with that component exists."""
        self._extend_currency()
        session = self._get_session(None)

        err = self.build_unknown_dimension_error("currenc", session=session)
        self.assertIsInstance(err, self.ConversionError)
        # Either as likely_fix (single close match) or in hints (multiple matches)
        suggestion_text = (err.likely_fix or "") + " " + " ".join(err.hints)
        self.assertIn("currency", suggestion_text)

    def test_unknown_dim_no_session_uses_builtins_only(self):
        """Without session, suggestions are limited to built-in dimensions."""
        err = self.build_unknown_dimension_error("currenc")
        self.assertIsInstance(err, self.ConversionError)
        # currency should NOT appear since no session was provided
        suggestion_text = (err.likely_fix or "") + " " + " ".join(err.hints)
        self.assertNotIn("currency", suggestion_text)


if __name__ == "__main__":
    unittest.main()

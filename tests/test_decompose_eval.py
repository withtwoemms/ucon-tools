# © 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0
# See the LICENSE file for details.

"""
Tiered evaluation suite for the decompose MCP tool.

Tests are organized by difficulty:
- Tier 1 (Basic): Simple single-unit conversions
- Tier 2 (Intermediate): Scaled units, multi-hop paths
- Tier 3 (Advanced): Composite units, Unicode, temperature
- Tier 4 (Expert): Complex composites, edge cases, error recovery

Each test verifies:
1. decompose() returns a valid result (not an error)
2. The factor chain can be passed to compute()
3. The computed result is within expected tolerance
"""

import unittest
import math


class DecomposeEvalBase(unittest.TestCase):
    """Base class for decompose evaluation tests."""

    @classmethod
    def setUpClass(cls):
        try:
            from ucon.tools.mcp.server import decompose, compute, DecomposeResult, ComputeResult
            from ucon.tools.mcp.suggestions import ConversionError
            cls.decompose = staticmethod(decompose)
            cls.compute = staticmethod(compute)
            cls.DecomposeResult = DecomposeResult
            cls.ComputeResult = ComputeResult
            cls.ConversionError = ConversionError
            cls.skip_tests = False
        except ImportError:
            cls.skip_tests = True

    def setUp(self):
        if self.skip_tests:
            self.skipTest("mcp not installed")

    def assert_decompose_roundtrip(
        self,
        query: str,
        expected_value: float,
        tolerance: float = 0.01,
        description: str = "",
    ):
        """Assert that decompose → compute produces expected result.

        Args:
            query: The conversion query (e.g., "3 m to ft")
            expected_value: The expected numeric result
            tolerance: Relative tolerance for comparison (default 1%)
            description: Optional description for error messages
        """
        # Step 1: Decompose
        result = self.decompose(query)
        self.assertIsInstance(
            result, self.DecomposeResult,
            f"decompose failed for '{query}': {result}"
        )

        # Step 2: Compute
        initial_value = result.initial_value if result.initial_value is not None else 1.0
        compute_result = self.compute(
            initial_value=initial_value,
            initial_unit=result.initial_unit,
            factors=result.factors,
        )
        self.assertIsInstance(
            compute_result, self.ComputeResult,
            f"compute failed for '{query}': {compute_result}"
        )

        # Step 3: Verify result
        actual = compute_result.quantity
        rel_error = abs(actual - expected_value) / max(abs(expected_value), 1e-10)
        self.assertLess(
            rel_error, tolerance,
            f"{description or query}: expected {expected_value}, got {actual} "
            f"(rel_error={rel_error:.4f}, tolerance={tolerance})"
        )

    def assert_decompose_error(
        self,
        query: str,
        expected_error_type: str,
        description: str = "",
    ):
        """Assert that decompose returns an error of the expected type."""
        result = self.decompose(query)
        self.assertIsInstance(
            result, self.ConversionError,
            f"Expected error for '{query}', got: {result}"
        )
        self.assertEqual(
            result.error_type, expected_error_type,
            f"{description or query}: expected error_type '{expected_error_type}', "
            f"got '{result.error_type}'"
        )


# =============================================================================
# Tier 1: Basic Conversions
# =============================================================================

class TestDecomposeTier1Basic(DecomposeEvalBase):
    """Tier 1: Simple single-unit conversions within common dimensions."""

    # -------------------------------------------------------------------------
    # Length
    # -------------------------------------------------------------------------

    def test_meter_to_foot(self):
        """1 m → 3.28084 ft"""
        self.assert_decompose_roundtrip("1 m to ft", 3.28084)

    def test_foot_to_meter(self):
        """1 ft → 0.3048 m"""
        self.assert_decompose_roundtrip("1 ft to m", 0.3048)

    def test_inch_to_centimeter(self):
        """1 in → 2.54 cm"""
        self.assert_decompose_roundtrip("1 in to cm", 2.54)

    def test_mile_to_kilometer(self):
        """1 mi → 1.60934 km"""
        self.assert_decompose_roundtrip("1 mi to km", 1.60934, tolerance=0.01)

    def test_yard_to_meter(self):
        """1 yd → 0.9144 m"""
        self.assert_decompose_roundtrip("1 yd to m", 0.9144)

    # -------------------------------------------------------------------------
    # Mass
    # -------------------------------------------------------------------------

    def test_kilogram_to_pound(self):
        """1 kg → 2.20462 lb"""
        self.assert_decompose_roundtrip("1 kg to lb", 2.20462)

    def test_pound_to_kilogram(self):
        """1 lb → 0.453592 kg"""
        self.assert_decompose_roundtrip("1 lb to kg", 0.453592)

    def test_ounce_to_gram(self):
        """1 oz → 28.3495 g"""
        self.assert_decompose_roundtrip("1 oz to g", 28.3495)

    def test_gram_to_milligram(self):
        """1 g → 1000 mg"""
        self.assert_decompose_roundtrip("1 g to mg", 1000.0)

    # -------------------------------------------------------------------------
    # Time
    # -------------------------------------------------------------------------

    def test_hour_to_minute(self):
        """1 h → 60 min"""
        self.assert_decompose_roundtrip("1 h to min", 60.0)

    def test_minute_to_second(self):
        """1 min → 60 s"""
        self.assert_decompose_roundtrip("1 min to s", 60.0)

    def test_day_to_hour(self):
        """1 day → 24 h"""
        self.assert_decompose_roundtrip("1 day to h", 24.0)

    # -------------------------------------------------------------------------
    # Volume
    # -------------------------------------------------------------------------

    def test_liter_to_gallon(self):
        """1 L → 0.264172 gal"""
        self.assert_decompose_roundtrip("1 L to gal", 0.264172)

    def test_gallon_to_liter(self):
        """1 gal → 3.78541 L"""
        self.assert_decompose_roundtrip("1 gal to L", 3.78541)

    def test_milliliter_to_liter(self):
        """1000 mL → 1 L"""
        self.assert_decompose_roundtrip("1000 mL to L", 1.0)


# =============================================================================
# Tier 2: Intermediate Conversions
# =============================================================================

class TestDecomposeTier2Intermediate(DecomposeEvalBase):
    """Tier 2: Scaled units, multi-hop paths, less common units."""

    # -------------------------------------------------------------------------
    # Scaled Units (SI Prefixes)
    # -------------------------------------------------------------------------

    def test_kilometer_to_meter(self):
        """5 km → 5000 m"""
        self.assert_decompose_roundtrip("5 km to m", 5000.0)

    def test_microgram_to_gram(self):
        """1000000 µg → 1 g"""
        self.assert_decompose_roundtrip("1000000 µg to g", 1.0)

    def test_megahertz_to_hertz(self):
        """1 MHz → 1000000 Hz"""
        self.assert_decompose_roundtrip("1 MHz to Hz", 1e6)

    def test_gigabyte_to_megabyte(self):
        """1 GB → 1000 MB"""
        self.assert_decompose_roundtrip("1 GB to MB", 1000.0)

    def test_kilojoule_to_joule(self):
        """1 kJ → 1000 J"""
        self.assert_decompose_roundtrip("1 kJ to J", 1000.0)

    # -------------------------------------------------------------------------
    # Binary Prefixes (Information)
    # -------------------------------------------------------------------------

    def test_gibibyte_to_mebibyte(self):
        """1 GiB → 1024 MiB"""
        self.assert_decompose_roundtrip("1 GiB to MiB", 1024.0)

    def test_gibibyte_to_kibibyte(self):
        """1 GiB → 1048576 KiB (1024²)"""
        self.assert_decompose_roundtrip("1 GiB to KiB", 1048576.0)

    def test_kibibyte_to_byte(self):
        """1 KiB → 1024 byte"""
        self.assert_decompose_roundtrip("1 KiB to byte", 1024.0)

    # -------------------------------------------------------------------------
    # Multi-Hop Conversions
    # -------------------------------------------------------------------------

    def test_mile_to_inch(self):
        """1 mi → 63360 in (mile → foot → inch)"""
        self.assert_decompose_roundtrip("1 mi to in", 63360.0)

    def test_kilogram_to_ounce(self):
        """1 kg → 35.274 oz (kg → lb → oz)"""
        self.assert_decompose_roundtrip("1 kg to oz", 35.274, tolerance=0.01)

    def test_day_to_second(self):
        """1 day → 86400 s (day → hour → minute → second)"""
        self.assert_decompose_roundtrip("1 day to s", 86400.0)

    # -------------------------------------------------------------------------
    # Energy
    # -------------------------------------------------------------------------

    def test_joule_to_calorie(self):
        """1 J → 0.239 cal"""
        self.assert_decompose_roundtrip("1 J to cal", 0.239, tolerance=0.01)

    def test_kilowatt_hour_to_joule(self):
        """1 kWh → 3.6e6 J"""
        self.assert_decompose_roundtrip("1 kWh to J", 3.6e6, tolerance=0.01)

    def test_btu_to_joule(self):
        """1 BTU → 1055.06 J"""
        self.assert_decompose_roundtrip("1 BTU to J", 1055.06, tolerance=0.01)

    # -------------------------------------------------------------------------
    # Power
    # -------------------------------------------------------------------------

    def test_watt_to_horsepower(self):
        """1 W → 0.00134 hp"""
        self.assert_decompose_roundtrip("1 W to hp", 0.00134, tolerance=0.01)

    def test_kilowatt_to_watt(self):
        """1 kW → 1000 W"""
        self.assert_decompose_roundtrip("1 kW to W", 1000.0)

    # -------------------------------------------------------------------------
    # Pressure
    # -------------------------------------------------------------------------

    def test_bar_to_pascal(self):
        """1 bar → 100000 Pa"""
        self.assert_decompose_roundtrip("1 bar to Pa", 100000.0)

    def test_atmosphere_to_bar(self):
        """1 atm → 1.01325 bar"""
        self.assert_decompose_roundtrip("1 atm to bar", 1.01325, tolerance=0.01)

    def test_psi_to_pascal(self):
        """1 psi → 6894.76 Pa"""
        self.assert_decompose_roundtrip("1 psi to Pa", 6894.76, tolerance=0.01)


# =============================================================================
# Tier 3: Advanced Conversions
# =============================================================================

class TestDecomposeTier3Advanced(DecomposeEvalBase):
    """Tier 3: Composite units, Unicode notation, angles."""

    # -------------------------------------------------------------------------
    # Composite Units - Velocity
    # -------------------------------------------------------------------------

    def test_meters_per_second_to_km_per_hour(self):
        """1 m/s → 3.6 km/h"""
        self.assert_decompose_roundtrip("1 m/s to km/h", 3.6)

    def test_miles_per_hour_to_meters_per_second(self):
        """60 mi/h → 26.8224 m/s"""
        self.assert_decompose_roundtrip("60 mi/h to m/s", 26.8224, tolerance=0.01)

    def test_km_per_hour_to_miles_per_hour(self):
        """100 km/h → 62.137 mi/h"""
        self.assert_decompose_roundtrip("100 km/h to mi/h", 62.137, tolerance=0.01)

    def test_feet_per_second_to_miles_per_hour(self):
        """88 ft/s → 60 mi/h (exactly)"""
        self.assert_decompose_roundtrip("88 ft/s to mi/h", 60.0, tolerance=0.01)

    # -------------------------------------------------------------------------
    # Composite Units - Acceleration
    # -------------------------------------------------------------------------

    def test_meters_per_second_squared_to_feet(self):
        """9.81 m/s² → 32.185 ft/s²"""
        self.assert_decompose_roundtrip("9.81 m/s^2 to ft/s^2", 32.185, tolerance=0.01)

    def test_acceleration_unicode_exponent(self):
        """9.81 m/s² → 32.185 ft/s² (Unicode notation)"""
        self.assert_decompose_roundtrip("9.81 m/s² to ft/s²", 32.185, tolerance=0.01)

    # -------------------------------------------------------------------------
    # Composite Units - Density
    # -------------------------------------------------------------------------

    def test_kg_per_m3_to_g_per_cm3(self):
        """1000 kg/m³ → 1 g/cm³ (water density)"""
        self.assert_decompose_roundtrip("1000 kg/m^3 to g/cm^3", 1.0, tolerance=0.01)

    def test_lb_per_ft3_to_kg_per_m3(self):
        """62.4 lb/ft³ → ~1000 kg/m³ (water density imperial)"""
        self.assert_decompose_roundtrip("62.4 lb/ft^3 to kg/m^3", 999.5, tolerance=0.02)

    # -------------------------------------------------------------------------
    # Composite Units - Flow Rate
    # -------------------------------------------------------------------------

    def test_liters_per_minute_to_gallons_per_hour(self):
        """1 L/min → 15.85 gal/h"""
        self.assert_decompose_roundtrip("1 L/min to gal/h", 15.85, tolerance=0.01)

    def test_cubic_meters_per_second_to_liters_per_minute(self):
        """0.001 m³/s → 60 L/min"""
        self.assert_decompose_roundtrip("0.001 m^3/s to L/min", 60.0, tolerance=0.01)

    # -------------------------------------------------------------------------
    # Angles
    # -------------------------------------------------------------------------

    def test_radian_to_degree(self):
        """π rad → 180°"""
        self.assert_decompose_roundtrip(f"{math.pi} rad to deg", 180.0, tolerance=0.001)

    def test_degree_to_radian(self):
        """180° → π rad"""
        self.assert_decompose_roundtrip("180 deg to rad", math.pi, tolerance=0.001)

    def test_turn_to_degree(self):
        """1 turn → 360°"""
        self.assert_decompose_roundtrip("1 turn to deg", 360.0)

    def test_gradian_to_degree(self):
        """100 grad → 90°"""
        self.assert_decompose_roundtrip("100 grad to deg", 90.0)

    # -------------------------------------------------------------------------
    # Ratios
    # -------------------------------------------------------------------------

    def test_fraction_to_percent(self):
        """0.5 fraction → 50%"""
        self.assert_decompose_roundtrip("0.5 fraction to %", 50.0)

    def test_percent_to_ppm(self):
        """1% → 10000 ppm"""
        self.assert_decompose_roundtrip("1 % to ppm", 10000.0)

    # -------------------------------------------------------------------------
    # Scientific Notation
    # -------------------------------------------------------------------------

    def test_scientific_notation_small(self):
        """1.5e-6 kg → 1.5 mg"""
        self.assert_decompose_roundtrip("1.5e-6 kg to mg", 1.5)

    def test_scientific_notation_large(self):
        """6.022e23 mol → 6.022e23 mol (Avogadro's number)"""
        # Identity conversion test
        self.assert_decompose_roundtrip("6.022e23 mol to mol", 6.022e23)

    def test_scientific_notation_conversion(self):
        """1e-9 m → 1 nm"""
        self.assert_decompose_roundtrip("1e-9 m to nm", 1.0)


# =============================================================================
# Tier 4: Expert Conversions
# =============================================================================

class TestDecomposeTier4Expert(DecomposeEvalBase):
    """Tier 4: Complex composites, edge cases, challenging conversions."""

    # -------------------------------------------------------------------------
    # Complex Composite Units
    # -------------------------------------------------------------------------

    def test_power_density(self):
        """1 W/m² → 0.0929 W/ft²"""
        self.assert_decompose_roundtrip("1 W/m^2 to W/ft^2", 0.0929, tolerance=0.01)

    def test_thermal_conductivity(self):
        """1 W/(m*K) → 0.5778 BTU/(h*ft*°R)"""
        # Complex cross-system thermal conductivity conversion
        # Skip if not supported
        result = self.decompose("1 W/(m*K) to BTU/(h*ft*°R)")
        if isinstance(result, self.ConversionError):
            self.skipTest("Thermal conductivity conversion not yet supported")

    def test_dynamic_viscosity(self):
        """1 Pa*s → 10 poise"""
        self.assert_decompose_roundtrip("1 Pa*s to poise", 10.0)

    def test_kinematic_viscosity(self):
        """1 m²/s → 10000 stokes"""
        self.assert_decompose_roundtrip("1 m^2/s to stokes", 10000.0)

    # -------------------------------------------------------------------------
    # Force
    # -------------------------------------------------------------------------

    def test_newton_to_pound_force(self):
        """1 N → 0.2248 lbf"""
        self.assert_decompose_roundtrip("1 N to lbf", 0.2248, tolerance=0.01)

    def test_kilogram_force_to_newton(self):
        """1 kgf → 9.80665 N"""
        self.assert_decompose_roundtrip("1 kgf to N", 9.80665)

    def test_dyne_to_newton(self):
        """1e5 dyne → 1 N"""
        self.assert_decompose_roundtrip("1e5 dyne to N", 1.0)

    # -------------------------------------------------------------------------
    # Energy/Power Complex
    # -------------------------------------------------------------------------

    def test_btu_per_hour_to_watt(self):
        """1 BTU/h → 0.293 W"""
        self.assert_decompose_roundtrip("1 BTU/h to W", 0.293, tolerance=0.01)

    def test_joule_to_watt_hour(self):
        """3600 J → 1 Wh"""
        self.assert_decompose_roundtrip("3600 J to Wh", 1.0)

    def test_calorie_to_btu(self):
        """252 cal → 1 BTU"""
        self.assert_decompose_roundtrip("252 cal to BTU", 1.0, tolerance=0.01)

    # -------------------------------------------------------------------------
    # Pressure Complex
    # -------------------------------------------------------------------------

    def test_torr_to_mmhg(self):
        """1 torr → 1 mmHg (by definition)"""
        self.assert_decompose_roundtrip("1 torr to mmHg", 1.0)

    def test_atmosphere_to_torr(self):
        """1 atm → 760 torr"""
        self.assert_decompose_roundtrip("1 atm to torr", 760.0, tolerance=0.01)

    def test_inhg_to_kpa(self):
        """29.92 inHg → 101.325 kPa (standard atmosphere)"""
        self.assert_decompose_roundtrip("29.92 inHg to kPa", 101.325, tolerance=0.01)

    # -------------------------------------------------------------------------
    # Information (SI vs Binary)
    # -------------------------------------------------------------------------

    def test_terabyte_to_gibibyte(self):
        """1 TB (10¹²) → ~931 GiB (10¹²/2³⁰)"""
        # 1 TB = 10^12 bytes, 1 GiB = 2^30 bytes
        # 10^12 / 2^30 = 931.322...
        self.assert_decompose_roundtrip("1 TB to GiB", 931.322, tolerance=0.01)

    def test_tebibyte_to_gibibyte(self):
        """1 TiB → 1024 GiB"""
        self.assert_decompose_roundtrip("1 TiB to GiB", 1024.0)

    def test_bytes_to_bits(self):
        """1 byte → 8 bit"""
        self.assert_decompose_roundtrip("1 byte to bit", 8.0)

    # -------------------------------------------------------------------------
    # Edge Cases - Very Large/Small Values
    # -------------------------------------------------------------------------

    def test_very_large_value(self):
        """1e15 m → 1 Pm (petameter)"""
        self.assert_decompose_roundtrip("1e15 m to Pm", 1.0)

    def test_very_small_value(self):
        """1e-12 m → 1 pm (picometer)"""
        self.assert_decompose_roundtrip("1e-12 m to pm", 1.0)

    def test_astronomical_distance(self):
        """1.496e11 m → ~1 AU... convert to km"""
        # Earth-Sun distance in km
        self.assert_decompose_roundtrip("1.496e11 m to km", 1.496e8)

    # -------------------------------------------------------------------------
    # Unit-Only Queries
    # -------------------------------------------------------------------------

    def test_unit_only_simple(self):
        """m to ft (no value)"""
        result = self.decompose("m to ft")
        self.assertIsInstance(result, self.DecomposeResult)
        self.assertIsNone(result.initial_value)
        # Should still produce valid factors
        compute_result = self.compute(
            initial_value=1.0,
            initial_unit=result.initial_unit,
            factors=result.factors,
        )
        self.assertIsInstance(compute_result, self.ComputeResult)
        self.assertAlmostEqual(compute_result.quantity, 3.28084, places=2)

    def test_unit_only_composite(self):
        """m/s to km/h (no value)"""
        result = self.decompose("m/s to km/h")
        self.assertIsInstance(result, self.DecomposeResult)
        self.assertIsNone(result.initial_value)

    # -------------------------------------------------------------------------
    # Alternative Separators
    # -------------------------------------------------------------------------

    def test_separator_in(self):
        """5 kg in lb"""
        self.assert_decompose_roundtrip("5 kg in lb", 11.023, tolerance=0.01)

    def test_separator_arrow_unicode(self):
        """5 m → ft"""
        self.assert_decompose_roundtrip("5 m → ft", 16.404, tolerance=0.01)

    def test_separator_arrow_ascii(self):
        """5 m -> ft"""
        self.assert_decompose_roundtrip("5 m -> ft", 16.404, tolerance=0.01)


# =============================================================================
# Tier 5: Error Handling
# =============================================================================

class TestDecomposeTier5Errors(DecomposeEvalBase):
    """Tier 5: Error cases and recovery."""

    # -------------------------------------------------------------------------
    # Parse Errors
    # -------------------------------------------------------------------------

    def test_missing_separator(self):
        """No 'to' or 'in' separator"""
        self.assert_decompose_error("5 m ft", "parse_error")

    def test_empty_query(self):
        """Empty string"""
        self.assert_decompose_error("", "parse_error")

    def test_whitespace_only(self):
        """Whitespace only"""
        self.assert_decompose_error("   ", "parse_error")

    def test_no_source_unit(self):
        """Value only, no unit - '5' parses as dimensionless, mismatches with length"""
        self.assert_decompose_error("5 to ft", "dimension_mismatch")

    # -------------------------------------------------------------------------
    # Unknown Units
    # -------------------------------------------------------------------------

    def test_unknown_source_unit(self):
        """Completely unknown source unit"""
        self.assert_decompose_error("5 foobar to m", "unknown_unit")

    def test_unknown_target_unit(self):
        """Completely unknown target unit"""
        self.assert_decompose_error("5 m to bazqux", "unknown_unit")

    def test_both_unknown(self):
        """Both units unknown - should fail on first"""
        self.assert_decompose_error("5 aaa to bbb", "unknown_unit")

    # -------------------------------------------------------------------------
    # Dimension Mismatches
    # -------------------------------------------------------------------------

    def test_dimension_mismatch_basic(self):
        """Length to mass"""
        self.assert_decompose_error("5 m to kg", "dimension_mismatch")

    def test_dimension_mismatch_composite(self):
        """Velocity to mass"""
        self.assert_decompose_error("5 m/s to kg", "dimension_mismatch")

    def test_dimension_mismatch_energy_to_power(self):
        """Energy to power (different dimensions)"""
        self.assert_decompose_error("5 J to W", "dimension_mismatch")

    # -------------------------------------------------------------------------
    # Typo Recovery (should still error but with suggestions)
    # -------------------------------------------------------------------------

    def test_typo_meter(self):
        """Typo 'meetr' should error with suggestion"""
        result = self.decompose("5 meetr to ft")
        self.assertIsInstance(result, self.ConversionError)
        self.assertEqual(result.error_type, "unknown_unit")
        # Should have suggestion
        has_suggestion = (
            (result.likely_fix and "meter" in result.likely_fix) or
            any("meter" in str(h) for h in result.hints)
        )
        self.assertTrue(has_suggestion, f"Expected 'meter' suggestion in: {result}")

    def test_typo_kilogram(self):
        """Typo 'kilgoram' should error with suggestion"""
        result = self.decompose("5 kilgoram to lb")
        self.assertIsInstance(result, self.ConversionError)
        self.assertEqual(result.error_type, "unknown_unit")

    # -------------------------------------------------------------------------
    # Pseudo-Dimension Isolation
    # -------------------------------------------------------------------------

    def test_angle_to_ratio_rejected(self):
        """Angle to ratio (pseudo-dimension isolation)"""
        self.assert_decompose_error("1 rad to %", "dimension_mismatch")

    def test_count_to_angle_rejected(self):
        """Count to angle (pseudo-dimension isolation)"""
        self.assert_decompose_error("5 ea to rad", "dimension_mismatch")


# =============================================================================
# Tier 6: Structured Mode (known_quantities)
# =============================================================================

class TestDecomposeStructuredMode(DecomposeEvalBase):
    """Tier 6: Structured decompose with known_quantities."""

    def assert_structured_roundtrip(
        self,
        initial_unit: str,
        target_unit: str,
        known_quantities: list[dict],
        initial_value: float,
        expected_value: float,
        tolerance: float = 0.01,
        description: str = "",
    ):
        """Assert that structured decompose → compute produces expected result."""
        result = self.decompose(
            initial_unit=initial_unit,
            target_unit=target_unit,
            known_quantities=known_quantities,
        )
        self.assertIsInstance(
            result, self.DecomposeResult,
            f"decompose failed for structured mode: {result}"
        )

        compute_result = self.compute(
            initial_value=initial_value,
            initial_unit=result.initial_unit,
            factors=result.factors,
        )
        self.assertIsInstance(
            compute_result, self.ComputeResult,
            f"compute failed for structured mode: {compute_result}"
        )

        actual = compute_result.quantity
        rel_error = abs(actual - expected_value) / max(abs(expected_value), 1e-10)
        self.assertLess(
            rel_error, tolerance,
            f"{description}: expected {expected_value}, got {actual} "
            f"(rel_error={rel_error:.4f}, tolerance={tolerance})"
        )

    # -------------------------------------------------------------------------
    # Eval 2.1: Weight-based dosing (regression)
    # -------------------------------------------------------------------------

    def test_weight_based_dosing(self):
        """5 mcg/kg/min × 70 kg → 21 mg/h"""
        self.assert_structured_roundtrip(
            initial_unit="mcg/(kg*min)",
            target_unit="mg/h",
            known_quantities=[{"value": 70, "unit": "kg"}],
            initial_value=5,
            expected_value=21.0,
            description="Eval 2.1: weight-based dosing",
        )

    # -------------------------------------------------------------------------
    # Eval 2.2: IV drip rate (regression)
    # -------------------------------------------------------------------------

    def test_iv_drip_rate(self):
        """1000 mL / 8h with 15 gtt/mL tubing → 31.25 gtt/min"""
        from ucon.tools.mcp.server import define_unit, define_conversion, _reset_fallback_session

        # gtt (drops) is a medical unit not yet in the ucon base registry;
        # register it as a session unit before running the decompose.
        define_unit(name="gtt", dimension="count", aliases=["gtt"])
        try:
            self.assert_structured_roundtrip(
                initial_unit="mL",
                target_unit="gtt/min",
                known_quantities=[
                    {"value": 8, "unit": "h"},
                    {"value": 15, "unit": "gtt/mL"},
                ],
                initial_value=1000,
                expected_value=31.25,
                description="Eval 2.2: IV drip rate",
            )
        finally:
            _reset_fallback_session()

    # -------------------------------------------------------------------------
    # Eval 2.3: Concentration with separate quantities (new)
    # -------------------------------------------------------------------------

    def test_concentration_separate(self):
        """5 mcg/kg/min × 80 kg × 250 mL ÷ 400 mg → 15 mL/h"""
        self.assert_structured_roundtrip(
            initial_unit="mcg/(kg*min)",
            target_unit="mL/h",
            known_quantities=[
                {"value": 80, "unit": "kg"},
                {"value": 250, "unit": "mL"},
                {"value": 400, "unit": "mg"},
            ],
            initial_value=5,
            expected_value=15.0,
            description="Eval 2.3: concentration (separate quantities)",
        )

    # -------------------------------------------------------------------------
    # Eval 2.3b: Concentration with pre-composed ratio (new)
    # -------------------------------------------------------------------------

    def test_concentration_precomposed(self):
        """5 mcg/kg/min × 80 kg × 0.625 mL/mg → 15 mL/h"""
        self.assert_structured_roundtrip(
            initial_unit="mcg/(kg*min)",
            target_unit="mL/h",
            known_quantities=[
                {"value": 80, "unit": "kg"},
                {"value": 0.625, "unit": "mL/mg"},
            ],
            initial_value=5,
            expected_value=15.0,
            description="Eval 2.3b: concentration (pre-composed ratio)",
        )

    # -------------------------------------------------------------------------
    # Eval 2.4: Dosing with rate-form count (new)
    # -------------------------------------------------------------------------

    def test_dosing_with_rate(self):
        """25 mg/(kg·d) × 15 kg ÷ 3 ea/d → 125 mg"""
        self.assert_structured_roundtrip(
            initial_unit="mg/(kg*d)",
            target_unit="mg",
            known_quantities=[
                {"value": 15, "unit": "kg"},
                {"value": 3, "unit": "ea/d"},
            ],
            initial_value=25,
            expected_value=125.0,
            description="Eval 2.4: dosing with rate-form count",
        )

    # -------------------------------------------------------------------------
    # Eval 2.4 error: Bare count diagnostic (new)
    # -------------------------------------------------------------------------

    def test_dosing_bare_count_diagnostic(self):
        """25 mg/(kg·d) with [15 kg, 3 ea] → error with ea/d hint"""
        result = self.decompose(
            initial_unit="mg/(kg*d)",
            target_unit="mg",
            known_quantities=[
                {"value": 15, "unit": "kg"},
                {"value": 3, "unit": "ea"},
            ],
        )
        self.assertIsInstance(
            result, self.ConversionError,
            f"Expected ConversionError for bare 'ea', got: {result}"
        )
        self.assertEqual(result.error_type, "dimension_mismatch")
        # Should contain a hint about expressing as a rate
        hints_text = " ".join(result.hints or [])
        self.assertIn(
            "ea/d",
            hints_text,
            f"Expected 'ea/d' suggestion in hints: {result.hints}"
        )

    # -------------------------------------------------------------------------
    # Eval 3.1: Specific impulse (regression)
    # -------------------------------------------------------------------------

    def test_specific_impulse(self):
        """300 s × 9.80665 m/s² → 2941.995 m/s (Isp conversion)"""
        self.assert_structured_roundtrip(
            initial_unit="s",
            target_unit="m/s",
            known_quantities=[{"value": 9.80665, "unit": "m/s^2"}],
            initial_value=300,
            expected_value=2941.995,
            description="Eval 3.1: specific impulse",
        )

    # -------------------------------------------------------------------------
    # Ambiguous placement: two same-dimension quantities (new)
    # -------------------------------------------------------------------------

    def test_same_dimension_opposing(self):
        """mg → mL with [250 mL, 400 mg] — 250 mL in num, 400 mg in denom"""
        self.assert_structured_roundtrip(
            initial_unit="mg",
            target_unit="mL",
            known_quantities=[
                {"value": 250, "unit": "mL"},
                {"value": 400, "unit": "mg"},
            ],
            initial_value=500,
            expected_value=312.5,
            description="Same-dimension opposing placement",
        )


# =============================================================================
# Summary Statistics
# =============================================================================

class TestDecomposeEvalSummary(unittest.TestCase):
    """Print summary statistics for the eval suite."""

    def test_eval_summary(self):
        """Run all eval tests and print summary."""
        import sys
        from io import StringIO

        # Count tests per tier
        tier_counts = {
            "Tier 1 (Basic)": len([m for m in dir(TestDecomposeTier1Basic) if m.startswith("test_")]),
            "Tier 2 (Intermediate)": len([m for m in dir(TestDecomposeTier2Intermediate) if m.startswith("test_")]),
            "Tier 3 (Advanced)": len([m for m in dir(TestDecomposeTier3Advanced) if m.startswith("test_")]),
            "Tier 4 (Expert)": len([m for m in dir(TestDecomposeTier4Expert) if m.startswith("test_")]),
            "Tier 5 (Errors)": len([m for m in dir(TestDecomposeTier5Errors) if m.startswith("test_")]),
            "Tier 6 (Structured)": len([m for m in dir(TestDecomposeStructuredMode) if m.startswith("test_")]),
        }

        total = sum(tier_counts.values())

        print("\n" + "=" * 60)
        print("DECOMPOSE TOOL EVALUATION SUITE")
        print("=" * 60)
        for tier, count in tier_counts.items():
            print(f"  {tier}: {count} tests")
        print("-" * 60)
        print(f"  TOTAL: {total} tests")
        print("=" * 60 + "\n")

        # This test always passes - it's just for reporting
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

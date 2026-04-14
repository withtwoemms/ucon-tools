# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Tests for built-in domain formulas.

These tests verify:
1. Correctness: known inputs yield expected numeric results
2. Dimension enforcement: wrong-dimension inputs raise ValueError
3. Registration: all 30 formulas appear in list_formulas()
"""

import math

import pytest

from ucon import Dimension, Number, units
from ucon.units import get_unit_by_name
from ucon.tools.mcp.formulas import list_formulas, get_formula
from ucon.tools.mcp.server import call_formula, FormulaResult, FormulaError


# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------


class TestFormulaRegistry:
    """Verify all 30 built-in formulas are registered."""

    EXPECTED_NAMES = sorted([
        # Medical
        "bmi", "bsa", "creatinine_clearance", "fib4", "mean_arterial_pressure",
        # Engineering
        "reynolds_number", "ohms_law_power", "stress", "darcy_weisbach", "kinetic_energy",
        # Chemistry
        "ideal_gas_pressure", "molarity", "dilution", "moles_from_mass", "gibbs_free_energy",
        # Physics
        "gravitational_force", "photon_energy", "coulombs_law", "projectile_range",
        "schwarzschild_radius",
        # SRE
        "availability", "error_budget_remaining", "mtbf", "mttr", "throughput",
        # Aerospace
        "orbital_velocity", "escape_velocity", "orbital_period",
        "tsiolkovsky_delta_v", "thrust",
    ])

    def test_total_count(self):
        formulas = list_formulas()
        registered_names = [f.name for f in formulas]
        for name in self.EXPECTED_NAMES:
            assert name in registered_names, f"Missing formula: {name}"
        assert len(formulas) >= 30

    def test_all_have_descriptions(self):
        for name in self.EXPECTED_NAMES:
            info = get_formula(name)
            assert info is not None, f"Formula '{name}' not found"
            assert info.description, f"Formula '{name}' missing description"

    def test_all_have_parameters(self):
        for name in self.EXPECTED_NAMES:
            info = get_formula(name)
            assert info is not None
            assert isinstance(info.parameters, dict)
            assert len(info.parameters) > 0, f"Formula '{name}' has no parameters"


# ---------------------------------------------------------------------------
# Medical Formulas
# ---------------------------------------------------------------------------


class TestBMI:
    def test_correctness(self):
        result = call_formula("bmi", {
            "mass": {"value": 70, "unit": "kg"},
            "height": {"value": 1.75, "unit": "m"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(22.857, rel=1e-3)

    def test_normalizes_height_in_cm(self):
        """BMI normalizes inputs — height in cm produces same result as meters."""
        result = call_formula("bmi", {
            "mass": {"value": 82, "unit": "kg"},
            "height": {"value": 178, "unit": "cm"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(25.88, rel=1e-2)

    def test_normalizes_imperial_inputs(self):
        """BMI normalizes inputs — lb and inches produce correct kg/m² result."""
        result = call_formula("bmi", {
            "mass": {"value": 180, "unit": "lb"},
            "height": {"value": 70, "unit": "in"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(25.82, rel=1e-2)

    def test_dimension_mismatch(self):
        result = call_formula("bmi", {
            "mass": {"value": 70, "unit": "m"},
            "height": {"value": 1.75, "unit": "m"},
        })
        assert isinstance(result, FormulaError)
        assert result.error_type == "dimension_mismatch"


class TestBSA:
    def test_correctness(self):
        result = call_formula("bsa", {
            "mass": {"value": 70, "unit": "kg"},
            "height": {"value": 1.75, "unit": "m"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(1.848, rel=1e-2)

    def test_dimension_mismatch(self):
        result = call_formula("bsa", {
            "mass": {"value": 70, "unit": "s"},
            "height": {"value": 1.75, "unit": "m"},
        })
        assert isinstance(result, FormulaError)
        assert result.error_type == "dimension_mismatch"


class TestCreatinineClearance:
    def test_correctness_male(self):
        result = call_formula("creatinine_clearance", {
            "age": {"value": 40, "unit": "yr"},
            "mass": {"value": 70, "unit": "kg"},
            "serum_creatinine": {"value": 1.0, "unit": "mg/dL"},
            "is_female": {"value": 0},
        })
        assert isinstance(result, FormulaResult)
        expected = (140 - 40) * 70 / (72 * 1.0)
        assert result.quantity == pytest.approx(expected, rel=1e-3)

    def test_correctness_female(self):
        result = call_formula("creatinine_clearance", {
            "age": {"value": 40, "unit": "yr"},
            "mass": {"value": 70, "unit": "kg"},
            "serum_creatinine": {"value": 1.0, "unit": "mg/dL"},
            "is_female": {"value": 1},
        })
        assert isinstance(result, FormulaResult)
        expected = (140 - 40) * 70 / (72 * 1.0) * 0.85
        assert result.quantity == pytest.approx(expected, rel=1e-3)


class TestFIB4:
    def test_correctness(self):
        result = call_formula("fib4", {
            "age": {"value": 50, "unit": "yr"},
            "ast": {"value": 35},
            "alt": {"value": 25},
            "platelets": {"value": 200},
        })
        assert isinstance(result, FormulaResult)
        expected = (50 * 35) / (200 * math.sqrt(25))
        assert result.quantity == pytest.approx(expected, rel=1e-3)

    def test_accepts_dimensionless_ast_alt(self):
        """AST/ALT are unconstrained — clinical U/L values pass without Hz workaround."""
        result = call_formula("fib4", {
            "age": {"value": 55, "unit": "yr"},
            "ast": {"value": 60},
            "alt": {"value": 45},
            "platelets": {"value": 150},
        })
        assert isinstance(result, FormulaResult)
        expected = (55 * 60) / (150 * math.sqrt(45))
        assert result.quantity == pytest.approx(expected, rel=1e-3)


class TestMeanArterialPressure:
    def test_correctness(self):
        result = call_formula("mean_arterial_pressure", {
            "systolic": {"value": 120, "unit": "Pa"},
            "diastolic": {"value": 80, "unit": "Pa"},
        })
        assert isinstance(result, FormulaResult)
        expected = (2 * 80 + 120) / 3
        assert result.quantity == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# Engineering Formulas
# ---------------------------------------------------------------------------


class TestReynoldsNumber:
    def test_correctness(self):
        result = call_formula("reynolds_number", {
            "density": {"value": 1000, "unit": "kg/m^3"},
            "velocity": {"value": 2, "unit": "m/s"},
            "characteristic_length": {"value": 0.05, "unit": "m"},
            "dynamic_viscosity": {"value": 0.001, "unit": "Pa*s"},
        })
        assert isinstance(result, FormulaResult)
        # Re = 1000 * 2 * 0.05 / 0.001 = 100,000
        assert result.quantity == pytest.approx(1e5, rel=1e-3)

    def test_unit_one_inputs(self):
        """All inputs = 1 in base SI → Re = 1."""
        result = call_formula("reynolds_number", {
            "density": {"value": 1, "unit": "kg/m^3"},
            "velocity": {"value": 1, "unit": "m/s"},
            "characteristic_length": {"value": 1, "unit": "m"},
            "dynamic_viscosity": {"value": 1, "unit": "Pa*s"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(1.0, rel=1e-3)


class TestOhmsLawPower:
    def test_correctness(self):
        result = call_formula("ohms_law_power", {
            "voltage": {"value": 12, "unit": "V"},
            "resistance": {"value": 4, "unit": "ohm"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(36, rel=1e-3)


class TestStress:
    def test_correctness(self):
        result = call_formula("stress", {
            "force": {"value": 1000, "unit": "N"},
            "area": {"value": 0.01, "unit": "m^2"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(100000, rel=1e-3)


class TestDarcyWeisbach:
    def test_correctness(self):
        result = call_formula("darcy_weisbach", {
            "friction_factor": {"value": 0.02},
            "pipe_length": {"value": 100, "unit": "m"},
            "pipe_diameter": {"value": 0.1, "unit": "m"},
            "flow_velocity": {"value": 2, "unit": "m/s"},
        })
        assert isinstance(result, FormulaResult)
        expected = 0.02 * (100 / 0.1) * (2 ** 2) / (2 * 9.80665)
        assert result.quantity == pytest.approx(expected, rel=1e-3)

    def test_normalizes_non_base_units(self):
        """Pipe length in km and velocity in km/h produce correct result."""
        result = call_formula("darcy_weisbach", {
            "friction_factor": {"value": 0.02},
            "pipe_length": {"value": 0.1, "unit": "km"},
            "pipe_diameter": {"value": 0.1, "unit": "m"},
            "flow_velocity": {"value": 7.2, "unit": "km/h"},
        })
        assert isinstance(result, FormulaResult)
        expected = 0.02 * (100 / 0.1) * (2 ** 2) / (2 * 9.80665)
        assert result.quantity == pytest.approx(expected, rel=1e-2)


class TestKineticEnergy:
    def test_correctness(self):
        result = call_formula("kinetic_energy", {
            "mass": {"value": 10, "unit": "kg"},
            "velocity": {"value": 5, "unit": "m/s"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(125, rel=1e-3)

    def test_dimension_mismatch(self):
        result = call_formula("kinetic_energy", {
            "mass": {"value": 10, "unit": "m"},
            "velocity": {"value": 5, "unit": "m/s"},
        })
        assert isinstance(result, FormulaError)
        assert result.error_type == "dimension_mismatch"


# ---------------------------------------------------------------------------
# Chemistry Formulas
# ---------------------------------------------------------------------------


class TestIdealGasPressure:
    def test_correctness_stp(self):
        result = call_formula("ideal_gas_pressure", {
            "amount": {"value": 1, "unit": "mol"},
            "temperature": {"value": 273.15, "unit": "K"},
            "volume": {"value": 0.02241, "unit": "m^3"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(101325, rel=1e-2)

    def test_normalizes_cm3_volume(self):
        """Volume in cm^3 produces same result as m^3."""
        result = call_formula("ideal_gas_pressure", {
            "amount": {"value": 1, "unit": "mol"},
            "temperature": {"value": 273.15, "unit": "K"},
            "volume": {"value": 22410, "unit": "cm^3"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(101325, rel=1e-2)


class TestMolarity:
    def test_correctness(self):
        result = call_formula("molarity", {
            "amount": {"value": 2, "unit": "mol"},
            "volume": {"value": 0.5, "unit": "L"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(4, rel=1e-3)


class TestDilution:
    def test_correctness(self):
        result = call_formula("dilution", {
            "initial_concentration": {"value": 2, "unit": "mol/L"},
            "initial_volume": {"value": 0.5, "unit": "L"},
            "final_concentration": {"value": 0.5, "unit": "mol/L"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(2.0, rel=1e-3)


class TestMolesFromMass:
    def test_correctness(self):
        # Water: 18 g/mol, 36 g = 2 mol
        result = call_formula("moles_from_mass", {
            "mass": {"value": 36, "unit": "g"},
            "molar_mass": {"value": 18, "unit": "g/mol"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(2.0, rel=1e-3)


class TestGibbsFreeEnergy:
    def test_correctness(self):
        # delta_G = delta_H - T * delta_S
        # = -285800 J - 298.15 K * (-163.15 J/K) = -285800 + 48663.3 = -237137
        result = call_formula("gibbs_free_energy", {
            "enthalpy": {"value": -285800, "unit": "J"},
            "temperature": {"value": 298.15, "unit": "K"},
            "entropy": {"value": -163.15, "unit": "J/K"},
        })
        assert isinstance(result, FormulaResult)
        expected = -285800 - 298.15 * (-163.15)
        assert result.quantity == pytest.approx(expected, rel=1e-3)

    def test_normalizes_kj_enthalpy(self):
        """Enthalpy in kJ with entropy in J/K produces correct result."""
        result = call_formula("gibbs_free_energy", {
            "enthalpy": {"value": -285.8, "unit": "kJ"},
            "temperature": {"value": 298.15, "unit": "K"},
            "entropy": {"value": -163.3, "unit": "J/K"},
        })
        assert isinstance(result, FormulaResult)
        expected = -285800 - 298.15 * (-163.3)
        assert result.quantity == pytest.approx(expected, rel=1e-2)


# ---------------------------------------------------------------------------
# Physics Formulas
# ---------------------------------------------------------------------------


class TestGravitationalForce:
    def test_correctness(self):
        # Earth-Moon: F = G * M_earth * M_moon / r^2
        result = call_formula("gravitational_force", {
            "mass1": {"value": 5.972e24, "unit": "kg"},
            "mass2": {"value": 7.342e22, "unit": "kg"},
            "distance": {"value": 3.844e8, "unit": "m"},
        })
        assert isinstance(result, FormulaResult)
        G = 6.6743e-11
        expected = G * 5.972e24 * 7.342e22 / (3.844e8) ** 2
        assert result.quantity == pytest.approx(expected, rel=1e-3)

    def test_normalizes_km_distance(self):
        """Distance in km produces same result as meters."""
        result = call_formula("gravitational_force", {
            "mass1": {"value": 5.972e24, "unit": "kg"},
            "mass2": {"value": 7.342e22, "unit": "kg"},
            "distance": {"value": 3.844e5, "unit": "km"},
        })
        assert isinstance(result, FormulaResult)
        G = 6.6743e-11
        expected = G * 5.972e24 * 7.342e22 / (3.844e8) ** 2
        assert result.quantity == pytest.approx(expected, rel=1e-3)


class TestPhotonEnergy:
    def test_correctness(self):
        # Visible light ~5e14 Hz
        result = call_formula("photon_energy", {
            "frequency": {"value": 5e14, "unit": "Hz"},
        })
        assert isinstance(result, FormulaResult)
        expected = 6.62607015e-34 * 5e14
        assert result.quantity == pytest.approx(expected, rel=1e-3)


class TestCoulombsLaw:
    def test_correctness(self):
        result = call_formula("coulombs_law", {
            "charge1": {"value": 1e-6, "unit": "C"},
            "charge2": {"value": 1e-6, "unit": "C"},
            "distance": {"value": 1, "unit": "m"},
        })
        assert isinstance(result, FormulaResult)
        eps0 = 8.8541878128e-12
        expected = (1e-6 * 1e-6) / (4 * math.pi * eps0 * 1)
        assert result.quantity == pytest.approx(expected, rel=1e-2)

    def test_normalizes_km_distance(self):
        """Distance in km produces same result as meters."""
        result = call_formula("coulombs_law", {
            "charge1": {"value": 1e-6, "unit": "C"},
            "charge2": {"value": 1e-6, "unit": "C"},
            "distance": {"value": 0.001, "unit": "km"},
        })
        assert isinstance(result, FormulaResult)
        eps0 = 8.8541878128e-12
        expected = (1e-6 * 1e-6) / (4 * math.pi * eps0 * 1)
        assert result.quantity == pytest.approx(expected, rel=1e-2)


class TestProjectileRange:
    def test_correctness_45deg(self):
        result = call_formula("projectile_range", {
            "initial_velocity": {"value": 20, "unit": "m/s"},
            "launch_angle": {"value": 45, "unit": "deg"},
        })
        assert isinstance(result, FormulaResult)
        expected = (20 ** 2) * math.sin(math.radians(90)) / 9.80665
        assert result.quantity == pytest.approx(expected, rel=1e-3)

    def test_normalizes_km_per_s(self):
        """Velocity in km/s produces same result as m/s."""
        result = call_formula("projectile_range", {
            "initial_velocity": {"value": 0.02, "unit": "km/s"},
            "launch_angle": {"value": 45, "unit": "deg"},
        })
        assert isinstance(result, FormulaResult)
        expected = (20 ** 2) * math.sin(math.radians(90)) / 9.80665
        assert result.quantity == pytest.approx(expected, rel=1e-3)


class TestSchwarzschildRadius:
    def test_correctness_solar_mass(self):
        result = call_formula("schwarzschild_radius", {
            "mass": {"value": 1.989e30, "unit": "kg"},
        })
        assert isinstance(result, FormulaResult)
        # r_s = 2GM/c^2 ~ 2954 m for the Sun
        G = 6.6743e-11
        c = 299792458
        expected = 2 * G * 1.989e30 / (c ** 2)
        assert result.quantity == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# SRE Formulas
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_correctness(self):
        result = call_formula("availability", {
            "uptime": {"value": 8750, "unit": "h"},
            "total_time": {"value": 8760, "unit": "h"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(8750 / 8760, rel=1e-5)

    def test_dimension_mismatch(self):
        result = call_formula("availability", {
            "uptime": {"value": 8750, "unit": "kg"},
            "total_time": {"value": 8760, "unit": "h"},
        })
        assert isinstance(result, FormulaError)
        assert result.error_type == "dimension_mismatch"


class TestErrorBudgetRemaining:
    def test_correctness(self):
        # SLO = 0.999, 50 errors out of 100000 requests
        # error_rate = 0.0005, allowed = 0.001, consumed = 0.5, remaining = 0.5
        result = call_formula("error_budget_remaining", {
            "errors": {"value": 50},
            "total_requests": {"value": 100000},
            "slo": {"value": 0.999},
        })
        assert isinstance(result, FormulaResult)
        expected = 1 - ((50 / 100000) / (1 - 0.999))  # 0.5
        assert result.quantity == pytest.approx(expected, rel=1e-5)

    def test_fully_consumed(self):
        """Error rate equals allowed error rate → 0 remaining."""
        result = call_formula("error_budget_remaining", {
            "errors": {"value": 100},
            "total_requests": {"value": 100000},
            "slo": {"value": 0.999},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(0.0, abs=1e-10)

    def test_no_errors(self):
        """Zero errors → 100% budget remaining."""
        result = call_formula("error_budget_remaining", {
            "errors": {"value": 0},
            "total_requests": {"value": 100000},
            "slo": {"value": 0.999},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(1.0, rel=1e-5)


class TestMTBF:
    def test_correctness(self):
        result = call_formula("mtbf", {
            "total_uptime": {"value": 8760, "unit": "h"},
            "failure_count": {"value": 4},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(2190, rel=1e-3)


class TestMTTR:
    def test_correctness(self):
        result = call_formula("mttr", {
            "total_downtime": {"value": 10, "unit": "h"},
            "repair_count": {"value": 5},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(2, rel=1e-3)


class TestThroughput:
    def test_correctness(self):
        result = call_formula("throughput", {
            "data_transferred": {"value": 1000, "unit": "B"},
            "duration": {"value": 10, "unit": "s"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(100, rel=1e-3)


# ---------------------------------------------------------------------------
# Aerospace Formulas
# ---------------------------------------------------------------------------


class TestOrbitalVelocity:
    def test_correctness_iss(self):
        result = call_formula("orbital_velocity", {
            "body_mass": {"value": 5.972e24, "unit": "kg"},
            "orbital_radius": {"value": 6.771e6, "unit": "m"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(7672, rel=1e-3)

    def test_normalizes_km_radius(self):
        """Radius in km produces same result as meters."""
        result = call_formula("orbital_velocity", {
            "body_mass": {"value": 5.972e24, "unit": "kg"},
            "orbital_radius": {"value": 6771, "unit": "km"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(7672, rel=1e-3)

    def test_dimension_mismatch(self):
        result = call_formula("orbital_velocity", {
            "body_mass": {"value": 5.972e24, "unit": "m"},
            "orbital_radius": {"value": 6.771e6, "unit": "m"},
        })
        assert isinstance(result, FormulaError)
        assert result.error_type == "dimension_mismatch"


class TestEscapeVelocity:
    def test_correctness_earth(self):
        result = call_formula("escape_velocity", {
            "body_mass": {"value": 5.972e24, "unit": "kg"},
            "radius": {"value": 6.371e6, "unit": "m"},
        })
        assert isinstance(result, FormulaResult)
        G = 6.6743e-11
        expected = math.sqrt(2 * G * 5.972e24 / 6.371e6)
        assert result.quantity == pytest.approx(expected, rel=1e-3)

    def test_normalizes_km_radius(self):
        """Radius in km produces same result as meters."""
        result = call_formula("escape_velocity", {
            "body_mass": {"value": 5.972e24, "unit": "kg"},
            "radius": {"value": 6371, "unit": "km"},
        })
        assert isinstance(result, FormulaResult)
        G = 6.6743e-11
        expected = math.sqrt(2 * G * 5.972e24 / 6.371e6)
        assert result.quantity == pytest.approx(expected, rel=1e-3)


class TestOrbitalPeriod:
    def test_correctness_iss(self):
        result = call_formula("orbital_period", {
            "semi_major_axis": {"value": 6.771e6, "unit": "m"},
            "body_mass": {"value": 5.972e24, "unit": "kg"},
        })
        assert isinstance(result, FormulaResult)
        G = 6.6743e-11
        expected = 2 * math.pi * math.sqrt((6.771e6) ** 3 / (G * 5.972e24))
        assert result.quantity == pytest.approx(expected, rel=1e-2)

    def test_normalizes_km_axis(self):
        """Semi-major axis in km produces same result as meters."""
        result = call_formula("orbital_period", {
            "semi_major_axis": {"value": 6771, "unit": "km"},
            "body_mass": {"value": 5.972e24, "unit": "kg"},
        })
        assert isinstance(result, FormulaResult)
        G = 6.6743e-11
        expected = 2 * math.pi * math.sqrt((6.771e6) ** 3 / (G * 5.972e24))
        assert result.quantity == pytest.approx(expected, rel=1e-2)


class TestTsiolkovskyDeltaV:
    def test_correctness(self):
        # Saturn V first stage Isp ~ 263 s, mass ratio ~ 10
        result = call_formula("tsiolkovsky_delta_v", {
            "specific_impulse": {"value": 263, "unit": "s"},
            "wet_mass": {"value": 10000, "unit": "kg"},
            "dry_mass": {"value": 1000, "unit": "kg"},
        })
        assert isinstance(result, FormulaResult)
        expected = 263 * 9.80665 * math.log(10000 / 1000)
        assert result.quantity == pytest.approx(expected, rel=1e-3)


class TestThrust:
    def test_correctness(self):
        # mass_flow_rate 100 kg/s, exhaust velocity 3000 m/s -> 300000 N
        result = call_formula("thrust", {
            "mass_flow_rate": {"value": 100, "unit": "kg/s"},
            "exhaust_velocity": {"value": 3000, "unit": "m/s"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(300000, rel=1e-3)


# ---------------------------------------------------------------------------
# Constant Unit Structure
# ---------------------------------------------------------------------------


class TestConstantUnitIntegrity:
    """Verify that physical constants used in formulas have correct units.

    These tests catch regressions where the TOML parser produces wrong
    unit decompositions — e.g., if ``m³/(kg·s²)`` is parsed without
    parentheses as ``m³/kg·s²`` under non-standard associativity,
    ``s²`` ends up in the numerator instead of the denominator.
    """

    def _get_factors(self, constant_attr):
        """Get {unit_name: exponent} dict from a constant's unit."""
        from ucon.core import UnitProduct
        const = getattr(__import__("ucon", fromlist=["constants"]).constants,
                        constant_attr)
        unit = const.unit
        if isinstance(unit, UnitProduct):
            return {uf.unit.name: exp for uf, exp in unit.factors.items()}
        return {unit.name: 1.0}

    def test_gravitational_constant_unit(self):
        """G should have unit m³/(kg·s²) = m³·kg⁻¹·s⁻²."""
        factors = self._get_factors("gravitational_constant")
        assert factors["meter"] == pytest.approx(3.0)
        assert factors["kilogram"] == pytest.approx(-1.0)
        assert factors["second"] == pytest.approx(-2.0)

    def test_molar_gas_constant_unit(self):
        """R should have unit J/(mol·K) = J·mol⁻¹·K⁻¹."""
        factors = self._get_factors("molar_gas_constant")
        assert factors["joule"] == pytest.approx(1.0)
        assert factors["mole"] == pytest.approx(-1.0)
        assert factors["kelvin"] == pytest.approx(-1.0)

    def test_stefan_boltzmann_constant_unit(self):
        """σ should have unit W/(m²·K⁴) = W·m⁻²·K⁻⁴."""
        factors = self._get_factors("stefan_boltzmann_constant")
        assert factors["watt"] == pytest.approx(1.0)
        assert factors["meter"] == pytest.approx(-2.0)
        assert factors["kelvin"] == pytest.approx(-4.0)

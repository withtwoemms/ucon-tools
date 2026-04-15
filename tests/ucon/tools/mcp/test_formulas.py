# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Tests for formula registry and schema introspection."""

import pytest

from ucon import Dimension, Number, enforce_dimensions
from ucon.tools.mcp.formulas import (
    FormulaInfo,
    register_formula,
    list_formulas,
    get_formula,
    clear_formulas,
)
from ucon.tools.mcp.formulas._registry import _FORMULA_REGISTRY
from ucon.tools.mcp.schema import extract_dimension_constraints


@pytest.fixture(autouse=True)
def clean_registry():
    """Save built-in formulas, clear for isolated test, then restore."""
    saved = dict(_FORMULA_REGISTRY)
    clear_formulas()
    yield
    clear_formulas()
    _FORMULA_REGISTRY.update(saved)


# -----------------------------------------------------------------------------
# Schema Introspection Tests
# -----------------------------------------------------------------------------


class TestExtractDimensionConstraints:
    """Tests for extract_dimension_constraints()."""

    def test_extracts_single_constraint(self):
        @enforce_dimensions
        def measure(length: Number[Dimension.length]) -> Number:
            return length

        constraints = extract_dimension_constraints(measure)
        assert constraints == {'length': 'length'}

    def test_extracts_multiple_constraints(self):
        @enforce_dimensions
        def speed(
            distance: Number[Dimension.length],
            time: Number[Dimension.time],
        ) -> Number:
            return distance / time

        constraints = extract_dimension_constraints(speed)
        assert constraints == {'distance': 'length', 'time': 'time'}

    def test_unconstrained_params_are_none(self):
        @enforce_dimensions
        def mixed(
            mass: Number[Dimension.mass],
            factor: Number,  # No dimension constraint
        ) -> Number:
            return mass * factor

        constraints = extract_dimension_constraints(mixed)
        assert constraints == {'mass': 'mass', 'factor': None}

    def test_handles_unwrapped_function(self):
        """Works on functions without @enforce_dimensions."""
        def bare(distance: Number[Dimension.length]) -> Number:
            return distance

        constraints = extract_dimension_constraints(bare)
        assert constraints == {'distance': 'length'}

    def test_handles_no_annotations(self):
        def untyped(x, y):
            return x + y

        constraints = extract_dimension_constraints(untyped)
        assert constraints == {}

    def test_excludes_return_annotation(self):
        @enforce_dimensions
        def with_return(
            time: Number[Dimension.time],
        ) -> Number[Dimension.time]:
            return time

        constraints = extract_dimension_constraints(with_return)
        assert 'return' not in constraints
        assert constraints == {'time': 'time'}


# -----------------------------------------------------------------------------
# Formula Registry Tests
# -----------------------------------------------------------------------------


class TestRegisterFormula:
    """Tests for @register_formula decorator."""

    def test_registers_formula(self):
        @register_formula("test_formula", description="A test formula")
        @enforce_dimensions
        def test_fn(x: Number[Dimension.length]) -> Number:
            return x

        info = get_formula("test_formula")
        assert info is not None
        assert info.name == "test_formula"
        assert info.description == "A test formula"
        assert info.parameters == {'x': 'length'}
        assert info.fn is test_fn

    def test_returns_original_function(self):
        @register_formula("identity_test")
        def original(x: Number) -> Number:
            return x

        # Decorator should return the function unchanged
        result = original(Number(5))
        assert result.quantity == 5

    def test_duplicate_name_raises(self):
        @register_formula("duplicate")
        def first():
            pass

        with pytest.raises(ValueError, match="already registered"):
            @register_formula("duplicate")
            def second():
                pass

    def test_empty_description_default(self):
        @register_formula("no_desc")
        def nodesc():
            pass

        info = get_formula("no_desc")
        assert info.description == ""


class TestListFormulas:
    """Tests for list_formulas()."""

    def test_empty_registry(self):
        assert list_formulas() == []

    def test_returns_all_formulas(self):
        @register_formula("alpha")
        def a():
            pass

        @register_formula("beta")
        def b():
            pass

        formulas = list_formulas()
        assert len(formulas) == 2
        names = [f.name for f in formulas]
        assert "alpha" in names
        assert "beta" in names

    def test_sorted_by_name(self):
        @register_formula("zebra")
        def z():
            pass

        @register_formula("apple")
        def a():
            pass

        formulas = list_formulas()
        assert formulas[0].name == "apple"
        assert formulas[1].name == "zebra"


class TestGetFormula:
    """Tests for get_formula()."""

    def test_returns_none_if_not_found(self):
        assert get_formula("nonexistent") is None

    def test_returns_formula_info(self):
        @register_formula("findme", description="Find this")
        def find():
            pass

        info = get_formula("findme")
        assert isinstance(info, FormulaInfo)
        assert info.name == "findme"
        assert info.description == "Find this"


class TestClearFormulas:
    """Tests for clear_formulas()."""

    def test_clears_all(self):
        @register_formula("temp")
        def temp():
            pass

        assert len(list_formulas()) == 1
        clear_formulas()
        assert len(list_formulas()) == 0


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


class TestFormulaIntegration:
    """End-to-end tests for formula registration and introspection."""

    def test_medical_formula(self):
        """Test a realistic medical formula with multiple dimensions."""
        @register_formula("bmi", description="Body Mass Index")
        @enforce_dimensions
        def bmi(
            mass: Number[Dimension.mass],
            height: Number[Dimension.length],
        ) -> Number:
            return mass / (height * height)

        info = get_formula("bmi")
        assert info.parameters == {'mass': 'mass', 'height': 'length'}

    def test_formula_with_mixed_constraints(self):
        """Test formula with both constrained and unconstrained params."""
        @register_formula("dosage", description="Calculate medication dosage")
        @enforce_dimensions
        def dosage(
            patient_mass: Number[Dimension.mass],
            dose_per_kg: Number,  # Unconstrained (could be mg/kg)
            frequency: Number[Dimension.frequency],
        ) -> Number:
            return patient_mass * dose_per_kg * frequency

        info = get_formula("dosage")
        assert info.parameters == {
            'patient_mass': 'mass',
            'dose_per_kg': None,
            'frequency': 'frequency',
        }


# -----------------------------------------------------------------------------
# MCP Tool Tests
# -----------------------------------------------------------------------------


class TestCallFormula:
    """Tests for call_formula MCP tool."""

    def test_unknown_formula(self):
        from ucon.tools.mcp.server import call_formula, FormulaError

        result = call_formula("nonexistent", {})
        assert isinstance(result, FormulaError)
        assert result.error_type == "unknown_formula"
        assert "nonexistent" in result.error

    def test_missing_parameter(self):
        from ucon.tools.mcp.server import call_formula, FormulaError

        @register_formula("needs_params")
        @enforce_dimensions
        def needs_params(x: Number[Dimension.length]) -> Number:
            return x

        result = call_formula("needs_params", {})
        assert isinstance(result, FormulaError)
        assert result.error_type == "missing_parameter"
        assert result.parameter == "x"

    def test_invalid_parameter_format(self):
        from ucon.tools.mcp.server import call_formula, FormulaError

        @register_formula("simple")
        def simple(x: Number) -> Number:
            return x

        # Pass a non-dict value
        result = call_formula("simple", {"x": 5.0})
        assert isinstance(result, FormulaError)
        assert result.error_type == "invalid_parameter"

    def test_missing_value_key(self):
        from ucon.tools.mcp.server import call_formula, FormulaError

        @register_formula("simple2")
        def simple2(x: Number) -> Number:
            return x

        result = call_formula("simple2", {"x": {"unit": "m"}})
        assert isinstance(result, FormulaError)
        assert result.error_type == "invalid_parameter"
        assert "value" in result.error

    def test_unknown_unit(self):
        from ucon.tools.mcp.server import call_formula, FormulaError

        @register_formula("with_unit")
        def with_unit(x: Number) -> Number:
            return x

        result = call_formula("with_unit", {"x": {"value": 5, "unit": "foobar"}})
        assert isinstance(result, FormulaError)
        assert result.error_type == "invalid_parameter"
        assert "foobar" in result.error

    def test_dimension_mismatch(self):
        from ucon.tools.mcp.server import call_formula, FormulaError

        @register_formula("length_only")
        @enforce_dimensions
        def length_only(x: Number[Dimension.length]) -> Number:
            return x

        # Pass mass instead of length
        result = call_formula("length_only", {"x": {"value": 5, "unit": "kg"}})
        assert isinstance(result, FormulaError)
        assert result.error_type == "dimension_mismatch"

    def test_successful_call(self):
        from ucon.tools.mcp.server import call_formula, FormulaResult

        @register_formula("double_length")
        @enforce_dimensions
        def double_length(x: Number[Dimension.length]) -> Number:
            return x * Number(2)

        result = call_formula("double_length", {"x": {"value": 5, "unit": "m"}})
        assert isinstance(result, FormulaResult)
        assert result.formula == "double_length"
        assert result.quantity == 10.0
        assert result.unit == "m"
        assert result.dimension == "length"

    def test_dimensionless_parameter(self):
        from ucon.tools.mcp.server import call_formula, FormulaResult

        @register_formula("scale_it")
        def scale_it(x: Number, factor: Number) -> Number:
            return x * factor

        result = call_formula("scale_it", {
            "x": {"value": 5, "unit": "m"},
            "factor": {"value": 3}
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == 15.0

    def test_composite_unit_result(self):
        from ucon.tools.mcp.server import call_formula, FormulaResult

        @register_formula("velocity")
        @enforce_dimensions
        def velocity(
            distance: Number[Dimension.length],
            time: Number[Dimension.time]
        ) -> Number:
            return distance / time

        result = call_formula("velocity", {
            "distance": {"value": 100, "unit": "m"},
            "time": {"value": 10, "unit": "s"}
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == 10.0
        assert result.unit == "m/s"

    def test_compound_output_simplified_to_named_unit(self):
        from ucon.tools.mcp.server import call_formula, FormulaResult

        @register_formula("force")
        @enforce_dimensions
        def force(
            mass: Number[Dimension.mass],
            acceleration: Number[Dimension.acceleration],
        ) -> Number:
            return mass * acceleration

        result = call_formula("force", {
            "mass": {"value": 10, "unit": "kg"},
            "acceleration": {"value": 9.81, "unit": "m/s^2"},
        })
        assert isinstance(result, FormulaResult)
        assert result.quantity == pytest.approx(98.1)
        assert result.unit == "N"
        assert result.dimension == "force"


# -----------------------------------------------------------------------------
# Cross-Basis Formula Inputs
# -----------------------------------------------------------------------------


class TestCallFormulaCrossBasis:
    """Tests for calling formulas with non-default-scale SI units (g, cm, mm).

    ucon v1.6.2 added cross-basis @enforce_dimensions support, so CGS-basis
    units like dyne pass validation.  However, formulas that call .to_base()
    stay within the input's basis — mixing CGS and SI arithmetic inside a
    formula body still raises.  These tests document both the working path
    (SI units at non-default scale) and the boundary (true CGS-basis units).
    """

    def test_force_with_grams_and_cm(self):
        """gram and cm are SI-basis; to_base() yields kg and m."""
        from ucon.tools.mcp.server import call_formula, FormulaResult

        @register_formula("grav_force")
        @enforce_dimensions
        def grav_force(
            mass1: Number[Dimension.mass],
            mass2: Number[Dimension.mass],
            distance: Number[Dimension.length],
        ) -> Number:
            from ucon.constants import gravitational_constant
            G = gravitational_constant.as_number()
            mass1 = mass1.to_base()
            mass2 = mass2.to_base()
            distance = distance.to_base()
            return G * mass1 * mass2 / (distance ** 2)

        result = call_formula("grav_force", {
            "mass1": {"value": 1000, "unit": "g"},
            "mass2": {"value": 1000, "unit": "g"},
            "distance": {"value": 100, "unit": "cm"},
        })
        assert isinstance(result, FormulaResult)
        assert result.dimension == "force"
        assert result.unit == "N"
        # 1 kg * 1 kg / (1 m)^2 * G ≈ 6.6743e-11
        assert result.quantity == pytest.approx(6.6743e-11, rel=1e-3)

    def test_pressure_with_millimeters(self):
        """mm is SI-basis; formula receives non-base-scale length."""
        from ucon.tools.mcp.server import call_formula, FormulaResult

        @register_formula("simple_pressure")
        @enforce_dimensions
        def simple_pressure(
            force: Number[Dimension.force],
            area: Number[Dimension.area],
        ) -> Number:
            force = force.to_base()
            area = area.to_base()
            return force / area

        result = call_formula("simple_pressure", {
            "force": {"value": 1000, "unit": "mN"},
            "area": {"value": 1, "unit": "m^2"},
        })
        assert isinstance(result, FormulaResult)
        assert result.dimension == "pressure"
        assert result.unit == "Pa"
        # 1 N / 1 m² = 1 Pa
        assert result.quantity == pytest.approx(1.0)

    def test_energy_with_grams_and_km(self):
        """Kinetic energy with grams and km/s — both SI-basis."""
        from ucon.tools.mcp.server import call_formula, FormulaResult

        @register_formula("kinetic_energy")
        @enforce_dimensions
        def kinetic_energy(
            mass: Number[Dimension.mass],
            velocity: Number[Dimension.velocity],
        ) -> Number:
            mass = mass.to_base()
            velocity = velocity.to_base()
            return Number(0.5) * mass * (velocity ** 2)

        result = call_formula("kinetic_energy", {
            "mass": {"value": 500, "unit": "g"},
            "velocity": {"value": 10, "unit": "m/s"},
        })
        assert isinstance(result, FormulaResult)
        assert result.dimension == "energy"
        assert result.unit == "J"
        # 0.5 * 0.5 kg * 100 m²/s² = 25 J
        assert result.quantity == pytest.approx(25.0)

    def test_cgs_basis_unit_passes_validation_but_fails_arithmetic(self):
        """dyne is CGS-basis — passes @enforce_dimensions but to_base()
        stays in CGS, so multiplying CGS force × SI length raises."""
        from ucon.tools.mcp.server import call_formula, FormulaError

        @register_formula("cross_basis_trap")
        @enforce_dimensions
        def cross_basis_trap(
            force: Number[Dimension.force],
            distance: Number[Dimension.length],
        ) -> Number:
            force = force.to_base()
            distance = distance.to_base()
            return force * distance

        result = call_formula("cross_basis_trap", {
            "force": {"value": 1.0, "unit": "dyn"},
            "distance": {"value": 1.0, "unit": "m"},
        })
        assert isinstance(result, FormulaError)
        assert result.error_type == "dimension_mismatch"


# -----------------------------------------------------------------------------
# Unit Simplification
# -----------------------------------------------------------------------------


class TestSimplifyFormulaUnit:
    """Tests for _simplify_formula_unit helper."""

    def test_plain_unit_unchanged(self):
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import meter

        result = Number(5.0, meter)
        assert _simplify_formula_unit(result) is result

    def test_dimensionless_unchanged(self):
        from ucon.tools.mcp.server import _simplify_formula_unit

        result = Number(3.14)
        assert _simplify_formula_unit(result) is result

    def test_single_factor_product_unchanged(self):
        from ucon.core import UnitProduct
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import meter

        result = Number(10.0, UnitProduct.from_unit(meter))
        assert _simplify_formula_unit(result) is result

    def test_force_simplifies_to_newton(self):
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import kilogram, meter, second

        compound = kilogram * meter / (second ** 2)
        result = Number(9.81, compound)
        simplified = _simplify_formula_unit(result)
        assert simplified.unit.shorthand == "N"
        assert simplified.quantity == 9.81

    def test_energy_simplifies_to_joule(self):
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import kilogram, meter, second

        compound = kilogram * meter ** 2 / second ** 2
        result = Number(100.0, compound)
        simplified = _simplify_formula_unit(result)
        assert simplified.unit.shorthand == "J"

    def test_power_simplifies_to_watt(self):
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import kilogram, meter, second

        compound = kilogram * meter ** 2 / second ** 3
        result = Number(50.0, compound)
        simplified = _simplify_formula_unit(result)
        assert simplified.unit.shorthand == "W"

    def test_pressure_simplifies_to_pascal(self):
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import kilogram, meter, second

        compound = kilogram / (meter * second ** 2)
        result = Number(101325.0, compound)
        simplified = _simplify_formula_unit(result)
        assert simplified.unit.shorthand == "Pa"

    def test_voltage_simplifies_to_volt(self):
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import kilogram, meter, second, ampere

        compound = kilogram * meter ** 2 / (ampere * second ** 3)
        result = Number(12.0, compound)
        simplified = _simplify_formula_unit(result)
        assert simplified.unit.shorthand == "V"

    def test_uncertainty_preserved(self):
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import kilogram, meter, second

        compound = kilogram * meter / (second ** 2)
        result = Number(9.81, compound, uncertainty=0.01)
        simplified = _simplify_formula_unit(result)
        assert simplified.unit.shorthand == "N"
        assert simplified.uncertainty == 0.01

    def test_velocity_not_simplified(self):
        """m/s has no single named SI unit — should stay compound."""
        from ucon.tools.mcp.server import _simplify_formula_unit
        from ucon.units import meter, second

        compound = meter / second
        result = Number(10.0, compound)
        simplified = _simplify_formula_unit(result)
        assert simplified.unit.shorthand == "m/s"


# -----------------------------------------------------------------------------
# Schema Edge Cases
# -----------------------------------------------------------------------------


class TestSchemaEdgeCases:
    """Test extract_dimension_constraints edge cases."""

    def test_forward_ref_fallback(self):
        """Function with unresolvable forward refs returns empty dict."""
        fn = lambda x: x
        fn.__annotations__ = {"x": "NonExistentType"}
        result = extract_dimension_constraints(fn)
        assert result == {}

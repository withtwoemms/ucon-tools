# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Medical/clinical formulas."""

from ucon import Dimension, Number, enforce_dimensions
from ucon import units
from ucon.units import get_unit_by_name
from ucon.tools.mcp.formulas._registry import register_formula

_centimeter = get_unit_by_name('cm')


@register_formula("bmi", description="Body Mass Index")
@enforce_dimensions
def bmi(
    mass: Number[Dimension.mass],
    height: Number[Dimension.length],
) -> Number:
    return mass / (height ** 2)


@register_formula("bsa", description="Body Surface Area (Du Bois formula)")
@enforce_dimensions
def bsa(
    mass: Number[Dimension.mass],
    height: Number[Dimension.length],
) -> Number:
    mass_kg = mass.to(units.kilogram).quantity
    height_cm = height.to(_centimeter).quantity
    area_m2 = 0.007184 * (mass_kg ** 0.425) * (height_cm ** 0.725)
    return Number(area_m2, units.meter ** 2)


@register_formula(
    "creatinine_clearance",
    description="Creatinine clearance (Cockcroft-Gault equation)",
)
@enforce_dimensions
def creatinine_clearance(
    age: Number[Dimension.time],
    mass: Number[Dimension.mass],
    serum_creatinine: Number[Dimension.density],
    is_female: Number,
) -> Number:
    age_yr = age.to(units.year).quantity
    mass_kg = mass.to(units.kilogram).quantity
    scr_mg_dl = serum_creatinine.to(
        get_unit_by_name('mg') / get_unit_by_name('dL')
    ).quantity
    female_factor = 0.85 if is_female.quantity else 1.0
    result = ((140 - age_yr) * mass_kg) / (72 * scr_mg_dl) * female_factor
    return Number(result, get_unit_by_name('mL') / units.minute)


@register_formula("fib4", description="FIB-4 liver fibrosis score")
@enforce_dimensions
def fib4(
    age: Number[Dimension.time],
    ast: Number[Dimension.frequency],
    alt: Number[Dimension.frequency],
    platelets: Number,
) -> Number:
    age_yr = age.to(units.year).quantity
    ast_uL = ast.to(units.hertz).quantity
    alt_uL = alt.to(units.hertz).quantity
    plt = platelets.quantity
    result = (age_yr * ast_uL) / (plt * (alt_uL ** 0.5))
    return Number(result)


@register_formula(
    "mean_arterial_pressure",
    description="Mean arterial pressure from systolic and diastolic",
)
@enforce_dimensions
def mean_arterial_pressure(
    systolic: Number[Dimension.pressure],
    diastolic: Number[Dimension.pressure],
) -> Number:
    return (diastolic * 2 + systolic) / 3

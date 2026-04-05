# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Chemistry formulas."""

from ucon import Dimension, Number, enforce_dimensions
from ucon import units
from ucon.constants import molar_gas_constant
from ucon.tools.mcp.formulas._registry import register_formula

R = molar_gas_constant.as_number()


@register_formula(
    "ideal_gas_pressure",
    description="Pressure from ideal gas law (PV = nRT)",
)
@enforce_dimensions
def ideal_gas_pressure(
    amount: Number[Dimension.amount_of_substance],
    temperature: Number[Dimension.temperature],
    volume: Number[Dimension.volume],
) -> Number:
    return amount * R * temperature / volume


@register_formula(
    "molarity",
    description="Molar concentration (C = n/V)",
)
@enforce_dimensions
def molarity(
    amount: Number[Dimension.amount_of_substance],
    volume: Number[Dimension.volume],
) -> Number:
    return amount / volume


@register_formula(
    "dilution",
    description="Dilution equation — final volume (V2 = C1*V1/C2)",
)
@enforce_dimensions
def dilution(
    initial_concentration: Number[Dimension.concentration],
    initial_volume: Number[Dimension.volume],
    final_concentration: Number[Dimension.concentration],
) -> Number:
    return initial_concentration * initial_volume / final_concentration


@register_formula(
    "moles_from_mass",
    description="Amount of substance from mass and molar mass (n = m/M)",
)
@enforce_dimensions
def moles_from_mass(
    mass: Number[Dimension.mass],
    molar_mass: Number[Dimension.molar_mass],
) -> Number:
    return mass / molar_mass


@register_formula(
    "gibbs_free_energy",
    description="Gibbs free energy (delta_G = delta_H - T*delta_S)",
)
@enforce_dimensions
def gibbs_free_energy(
    enthalpy: Number[Dimension.energy],
    temperature: Number[Dimension.temperature],
    entropy: Number[Dimension.entropy],
) -> Number:
    return enthalpy - temperature * entropy

# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Engineering formulas."""

from ucon import Dimension, Number, enforce_dimensions
from ucon import units
from ucon.units import get_unit_by_name
from ucon.tools.mcp.formulas._registry import register_formula

_kg_per_m3 = units.kilogram / units.meter ** 3
_m_per_s = units.meter / units.second
_Pa_s = get_unit_by_name('Pa') * units.second


@register_formula(
    "reynolds_number",
    description="Reynolds number for fluid flow (Re = rho*v*L/mu)",
)
@enforce_dimensions
def reynolds_number(
    density: Number[Dimension.density],
    velocity: Number[Dimension.velocity],
    characteristic_length: Number[Dimension.length],
    dynamic_viscosity: Number[Dimension.dynamic_viscosity],
) -> Number:
    rho = density.to(_kg_per_m3).quantity
    v = velocity.to(_m_per_s).quantity
    L = characteristic_length.to(units.meter).quantity
    mu = dynamic_viscosity.to(_Pa_s).quantity
    return Number(rho * v * L / mu)


@register_formula(
    "ohms_law_power",
    description="Electrical power from voltage and resistance (P = V^2/R)",
)
@enforce_dimensions
def ohms_law_power(
    voltage: Number[Dimension.voltage],
    resistance: Number[Dimension.resistance],
) -> Number:
    return (voltage ** 2) / resistance


@register_formula("stress", description="Mechanical stress (sigma = F/A)")
@enforce_dimensions
def stress(
    force: Number[Dimension.force],
    area: Number[Dimension.area],
) -> Number:
    return force / area


@register_formula(
    "darcy_weisbach",
    description="Head loss via Darcy-Weisbach equation (h_f = f*L/D*v^2/(2g))",
)
@enforce_dimensions
def darcy_weisbach(
    friction_factor: Number,
    pipe_length: Number[Dimension.length],
    pipe_diameter: Number[Dimension.length],
    flow_velocity: Number[Dimension.velocity],
) -> Number:
    g = Number(9.80665, units.meter / units.second ** 2)
    return friction_factor * (pipe_length / pipe_diameter) * (flow_velocity ** 2) / (Number(2) * g)


@register_formula(
    "kinetic_energy",
    description="Kinetic energy (KE = 0.5*m*v^2)",
)
@enforce_dimensions
def kinetic_energy(
    mass: Number[Dimension.mass],
    velocity: Number[Dimension.velocity],
) -> Number:
    return mass * (velocity ** 2) * 0.5

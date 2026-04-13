# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Physics formulas."""

import math

from ucon import Dimension, Number, enforce_dimensions
from ucon import units
from ucon.constants import (
    gravitational_constant,
    planck_constant,
    speed_of_light,
    standard_gravity,
    vacuum_permittivity,
)
from ucon.tools.mcp.formulas._registry import register_formula

G = gravitational_constant.as_number()
h = planck_constant.as_number()
c = speed_of_light.as_number()
eps0 = vacuum_permittivity.as_number()
g0 = standard_gravity.as_number()


@register_formula(
    "gravitational_force",
    description="Gravitational force between two masses (F = G*m1*m2/r^2)",
)
@enforce_dimensions
def gravitational_force(
    mass1: Number[Dimension.mass],
    mass2: Number[Dimension.mass],
    distance: Number[Dimension.length],
) -> Number:
    return G * mass1 * mass2 / (distance ** 2)


@register_formula(
    "photon_energy",
    description="Energy of a photon (E = h*f)",
)
@enforce_dimensions
def photon_energy(
    frequency: Number[Dimension.frequency],
) -> Number:
    return h * frequency


@register_formula(
    "coulombs_law",
    description="Electrostatic force between two charges (F = q1*q2/(4*pi*eps0*r^2))",
)
@enforce_dimensions
def coulombs_law(
    charge1: Number[Dimension.charge],
    charge2: Number[Dimension.charge],
    distance: Number[Dimension.length],
) -> Number:
    return charge1 * charge2 / (Number(4 * math.pi) * eps0 * (distance ** 2))


@register_formula(
    "projectile_range",
    description="Projectile range on flat ground (R = v^2*sin(2*theta)/g)",
)
@enforce_dimensions
def projectile_range(
    initial_velocity: Number[Dimension.velocity],
    launch_angle: Number[Dimension.angle],
) -> Number:
    angle_rad = launch_angle.to(units.radian).quantity
    return (initial_velocity ** 2) * math.sin(2 * angle_rad) / g0


@register_formula(
    "schwarzschild_radius",
    description="Schwarzschild radius of a mass (r_s = 2*G*M/c^2)",
)
@enforce_dimensions
def schwarzschild_radius(
    mass: Number[Dimension.mass],
) -> Number:
    return G * mass * 2 / (c ** 2)

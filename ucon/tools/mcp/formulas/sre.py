# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Site Reliability Engineering (SRE) formulas."""

from ucon import Dimension, Number, enforce_dimensions
from ucon import units
from ucon.tools.mcp.formulas._registry import register_formula


@register_formula(
    "availability",
    description="Service availability (uptime fraction)",
)
@enforce_dimensions
def availability(
    uptime: Number[Dimension.time],
    total_time: Number[Dimension.time],
) -> Number:
    return uptime / total_time


@register_formula(
    "error_budget_remaining",
    description="Remaining error budget fraction: 1 - (error_rate / allowed_error_rate)",
)
@enforce_dimensions
def error_budget_remaining(
    errors: Number,
    total_requests: Number,
    slo: Number,
) -> Number:
    e = errors.quantity
    t = total_requests.quantity
    s = slo.quantity
    error_rate = e / t
    allowed_error_rate = 1 - s
    result = 1 - (error_rate / allowed_error_rate)
    return Number(result)


@register_formula(
    "mtbf",
    description="Mean time between failures (MTBF = total_uptime / failure_count)",
)
@enforce_dimensions
def mtbf(
    total_uptime: Number[Dimension.time],
    failure_count: Number,
) -> Number:
    return total_uptime / failure_count


@register_formula(
    "mttr",
    description="Mean time to repair (MTTR = total_downtime / repair_count)",
)
@enforce_dimensions
def mttr(
    total_downtime: Number[Dimension.time],
    repair_count: Number,
) -> Number:
    return total_downtime / repair_count


@register_formula(
    "throughput",
    description="Data throughput (data_transferred / duration)",
)
@enforce_dimensions
def throughput(
    data_transferred: Number[Dimension.information],
    duration: Number[Dimension.time],
) -> Number:
    return data_transferred / duration

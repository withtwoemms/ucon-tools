# Copyright 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0

"""Built-in domain formulas for the ucon MCP server.

Re-exports the formula registry API and imports domain modules
to trigger registration of built-in formulas at server startup.
"""

from ucon.tools.mcp.formulas._registry import (
    FormulaInfo,
    register_formula,
    list_formulas,
    get_formula,
    clear_formulas,
)

# Import domain modules to trigger formula registration
from ucon.tools.mcp.formulas import (  # noqa: F401
    medical,
    engineering,
    chemistry,
    physics,
    sre,
    aerospace,
)

__all__ = [
    'FormulaInfo',
    'register_formula',
    'list_formulas',
    'get_formula',
    'clear_formulas',
]

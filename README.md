<table>
  <tr>
    <td width="200">
      <img src="https://gist.githubusercontent.com/withtwoemms/8386e69ff949733a99dbc41bdab0dc1e/raw/42c00e74a37ff091f415ffec7292b8eceac18cbb/ucon-tools-logo.png" align="left" width="200" />
    </td>
    <td>

# ucon-tools

[![tests](https://github.com/withtwoemms/ucon-tools/workflows/tests/badge.svg)](https://github.com/withtwoemms/ucon-tools/actions?query=workflow%3Atests)
[![codecov](https://codecov.io/gh/withtwoemms/ucon-tools/graph/badge.svg?token=HDKWKAF7PX)](https://codecov.io/gh/withtwoemms/ucon-tools)
[![publish](https://github.com/withtwoemms/ucon-tools/workflows/publish/badge.svg)](https://github.com/withtwoemms/ucon-tools/actions?query=workflow%3Apublish)

   </td>
  </tr>
</table>

> Hostable interfaces for the [ucon](https://github.com/withtwoemms/ucon) dimensional analysis engine.

**[Documentation](https://docs.ucon.dev)** · [MCP Server Guide](https://docs.ucon.dev/guides/mcp-server/) · [Tool Reference](https://docs.ucon.dev/reference/mcp-tools/)

---

## What is ucon-tools?

[ucon](https://github.com/withtwoemms/ucon) is a unit-aware computation library for Python. `ucon-tools` packages it into interfaces that other systems can consume — MCP servers for AI agents, REST APIs for web services, CLIs for humans at a terminal.

Each interface lives under `ucon.tools.<interface>` and is installable as an optional extra:

| Interface | Package | Extra | Status |
|-----------|---------|-------|--------|
| MCP server | `ucon.tools.mcp` | `ucon-tools[mcp]` | Available |
| REST API | `ucon.tools.rest` | `ucon-tools[rest]` | Planned |
| CLI | `ucon.tools.cli` | `ucon-tools[cli]` | Planned |

---

## MCP Server

The MCP server gives AI agents (Claude, Cursor, and other [MCP](https://modelcontextprotocol.io/) clients) dimensionally-verified unit conversion and computation.

```
Agent: "Convert 5 mcg/kg/min for an 80 kg patient to mL/h. Drug is 400 mg in 250 mL."

  decompose → constraint solver places quantities, auto-bridges mcg→mg and min→h
  compute   → 5 × 80 kg × (60 min/h) × (1 mg/1000 mcg) × (250 mL/400 mg) = 15 mL/h
  validate  → result dimension matches expected unit ✓
```

### Installation

```bash
pip install ucon-tools[mcp]
```

Requires Python 3.10+.

### Configuration

**Claude Desktop / Claude Code** — add to your MCP configuration:

```json
{
  "mcpServers": {
    "ucon": {
      "command": "uvx",
      "args": ["--from", "ucon-tools[mcp]", "ucon-mcp"]
    }
  }
}
```

**Standalone:**

```bash
ucon-mcp                    # stdio transport (default)
ucon-mcp --transport sse    # SSE transport for remote clients
```

### Tools

**Core** — conversion and computation:

| Tool | Description |
|------|-------------|
| `convert` | Convert a value between compatible units |
| `compute` | Multi-step factor-label calculation with dimensional tracking |
| `decompose` | Build a factor chain from natural-language or structured input |
| `check_dimensions` | Check if two units share the same dimension |

**Discovery** — explore the unit system:

| Tool | Description |
|------|-------------|
| `list_units` | List available units, optionally filtered by dimension |
| `list_scales` | List SI decimal and binary prefixes |
| `list_dimensions` | List available physical dimensions |
| `list_constants` | List physical constants (CODATA 2022) |
| `list_formulas` | List registered domain formulas |

**Runtime extension** — add units and conversions per session:

| Tool | Description |
|------|-------------|
| `define_unit` | Register a custom unit for the session |
| `define_conversion` | Add a conversion edge (linear or affine) |
| `define_constant` | Define a custom physical constant |
| `call_formula` | Call a registered dimensionally-typed formula |
| `reset_session` | Clear all session-defined units, conversions, and constants |

**Kind-of-Quantity (KOQ)** — semantic disambiguation:

| Tool | Description |
|------|-------------|
| `define_quantity_kind` | Register a quantity kind for disambiguation |
| `declare_computation` | Declare expected quantity kind before computing |
| `validate_result` | Validate that a result matches the declared kind |
| `list_quantity_kinds` | List registered quantity kinds |
| `extend_basis` | Create an extended dimensional basis |
| `list_extended_bases` | List session-defined extended bases |

---

## Architecture

`ucon-tools` is an interface layer. It does not reimplement dimensional analysis — it delegates to `ucon` for all unit resolution, conversion, and dimensional algebra. What it adds is interface-specific logic: session state, protocol handling, error suggestions, and agent-oriented features like the `decompose` constraint solver and KOQ disambiguation.

```
┌───────────────────────────────────────────────────────┐
│                     Clients                           │
│   MCP (Claude, Cursor)  ·  HTTP  ·  Terminal          │
└──────────┬──────────────────┬──────────────┬──────────┘
           │                  │              │
┌──────────▼───┐   ┌──────────▼───┐  ┌───────▼──────┐
│ ucon.tools   │   │ ucon.tools   │  │ ucon.tools   │
│     .mcp     │   │     .rest    │  │     .cli     │
│              │   │              │  │              │
│  sessions    │   │  (planned)   │  │  (planned)   │
│  decompose   │   │              │  │              │
│  KOQ         │   │              │  │              │
│  suggestions │   │              │  │              │
└──────┬───────┘   └──────┬───────┘  └──────┬───────┘
       │                  │                 │
       └──────────────────┼─────────────────┘
                          │ Python imports
               ┌──────────▼──────────┐
               │        ucon         │
               │                     │
               │  Units, Dimensions  │
               │  ConversionGraph    │
               │  Scales, Constants  │
               └─────────────────────┘
```

---

## Development

```bash
make venv                               # Create virtual environment
source .ucon-tools-3.12/bin/activate    # Activate
make test                               # Run tests
make test-all                           # Run across all supported Python versions
```

### Running the MCP server locally

```bash
make mcp-server                         # Foreground (stdio)
make mcp-server-bg                      # Background
make mcp-server-stop                    # Stop background server
```

---

## License

AGPL-3.0. See [LICENSE](./LICENSE).

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

INSTRUCTIONS = """\
Tearsheet: stock prices, fundamentals, indicators, backtests and charts from Yahoo Finance.

- Analysis and plot tools take a ticker and dates and fetch data themselves. Do not
  fetch price rows to pass them on; call the tool you need directly.
- Ratios, margins, returns and growth rates are fractions: 0.25 means 25%.
- Dates are YYYY-MM-DD; end_date is inclusive and defaults to today.
- Price history and indicators return summaries by default. Ask for
  response_format="rows" only when you need individual bars.
- Errors explain what to change (symbol, date range, interval). Share-class tickers
  use a dash, e.g. BRK-B.
"""

# This is the shared MCP server instance
mcp = MCPServer("tearsheet_mcp", instructions=INSTRUCTIONS)

# Tools that only read from Yahoo Finance.
READ_ONLY_REMOTE = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

# Tools that only compute on their inputs, with no external calls.
PURE_COMPUTE = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)

# Plot tools write a new PNG to local disk on every call.
PLOT_LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)

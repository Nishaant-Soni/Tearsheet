# Changes

Tracks the refactor described in the refactor spec: tool renames, behavior changes,
and deviations from the spec.

## Deviations from the spec

- **mcp 2.x instead of 1.x APIs.** The current `mcp` release is 2.3.0, where `FastMCP`
  was renamed to `MCPServer` (`mcp.server.mcpserver`). The spec's references map as:
  - `mcp.server.fastmcp.FastMCP` -> `mcp.server.mcpserver.MCPServer`
  - `mcp.server.fastmcp.Image` -> `mcp.server.mcpserver.Image`
  - `mcp.server.fastmcp.exceptions.ToolError` -> `mcp.server.mcpserver.exceptions.ToolError`
  - `mcp.shared.memory.create_connected_server_and_client_session` -> `mcp.Client(server)`
    (in-process transport)
- **anyio pytest plugin instead of pytest-asyncio.** anyio ships with `mcp`, so async
  tests use `@pytest.mark.anyio` and no extra dependency is added.
- **Agg backend set in Phase 0.** mcp 2.x runs sync tools in worker threads, and the
  macOS GUI backend aborts the process when pyplot creates a figure off the main thread.
  `tearsheet/viz/charts.py` forces `Agg` now rather than waiting for Phase 4. PNG output
  is unchanged.
- **Backtest trades include `signal_date`.** With next-open fills, `entry_date` is the
  day after the crossover. Eval Q4 asks for the crossover (signal) date, so each trade
  in `tearsheet_backtest_ma_crossover` also reports `signal_date` and `exit_signal_date`.
- **Eval answers use the fiscal year ending in 2025.** yfinance serves about four annual
  periods, so older fiscal years would drop out of the data within a year or two.

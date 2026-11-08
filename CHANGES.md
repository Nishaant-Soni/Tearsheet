# Changes

Tracks the refactor described in the refactor spec: tool renames, behavior changes,
and deviations from the spec.

## Tool renames

| Old tool | New tool | Since |
|---|---|---|
| `retrieve_current_price` | `tearsheet_get_quote` | Phase 1 |
| `retrieve_stock_data` | `tearsheet_get_price_history` | Phase 1 |
| `retrieve_ticker_info` | `tearsheet_get_company_info` | Phase 1 |
| `retrieve_dividends` | `tearsheet_get_dividends` | Phase 1 |
| `retrieve_splits` | `tearsheet_get_splits` | Phase 1 |

## Behavior changes

- **Price history** takes `tickers` (1 to 10), validates symbols and dates, treats
  `end_date` as inclusive, and returns a summary per ticker by default.
  `response_format="rows"` returns row records capped at `max_rows` (default 100,
  max 1000), downsampled evenly with `truncated` and `total_rows` when longer.
- **Quote** reads `Ticker.fast_info` instead of `.info`, and adds previous close, change,
  market cap and shares outstanding.
- **Dividends and splits** return `[{"date": "YYYY-MM-DD", "value": float}]` instead of
  a JSON string keyed by epoch milliseconds.
- **Errors** are raised as `ToolError` (`isError: true`) with a next step. Unknown
  tickers no longer return `{}` or `{"error": ...}`.
- **Intraday limits** are checked before calling Yahoo: `1m` spans at most 7 days within
  the last 30, `5m`/`15m`/`30m` reach back 60 days, `1h` 730 days.
- All yfinance calls run in worker threads. Price histories and dividend/split series
  are cached in-process: 15 minutes for intraday or ranges ending today, 4 hours
  otherwise.

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
- **yfinance upgraded to 1.8.0** (from 0.2.61). It stamps dividends and splits at
  market open (09:30) rather than midnight, so the data layer normalizes them to dates.
  All ten eval answers were re-verified as unchanged under 1.8.0.
- **Retrieval tools renamed in Phase 1, not Phase 5.** The new data layer replaces
  their bodies, so they got their final names, typed inputs, annotations and
  structured output at the same time. Analysis and plot tools follow in Phases 3 to 5.
- **`adjusted=false` is split-adjusted.** yfinance's unadjusted close still reflects
  later splits; only dividend adjustment is removed.
- **Summary is included in `rows` mode too**, so callers always get the headline numbers.
- **Multi-ticker history fails as a whole** if any ticker is invalid, naming each bad
  symbol, instead of returning partial results.
- **`tearsheet/serialize.py` added** (not in the spec's layout) for NaN/inf to `None`,
  rounding, summaries and row downsampling, shared by all tool wrappers.

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
| `retrieve_financial_statements` | `tearsheet_get_financial_statement` | Phase 2 |
| `mcp_calculate_financial_metrics` | `tearsheet_get_fundamentals` | Phase 2 |

## Renamed metrics

| Old | New |
|---|---|
| `net_profit_margin` | `net_margin` |
| `cash_flow_margin` | `operating_cash_flow_margin` |

New metrics: `liabilities_to_equity` (the old `debt_to_equity` figure under a correct
name), `fcf_margin`. `tearsheet_get_fundamentals` computes all 17 metrics by default.

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
- **Financial statements** are normalized on the server into canonical snake_case fields
  per fiscal period (newest first), instead of `DataFrame.to_json()` keyed by epoch ms.
  `unmapped_labels` lists yfinance line items with no canonical name.
- **Fundamentals** are computed on the server from ticker + period; the model no longer
  assembles a `financial_data` dict. Market-based ratios get the price from `fast_info`.
- **`debt_to_equity` fixed:** now `total_debt / stockholders_equity`. It was total
  liabilities / equity, which is now reported as `liabilities_to_equity`.
- **`free_cash_flow` fixed:** `operating_cash_flow - |capital_expenditure|`. yfinance
  reports capex as negative, so the old `ocf - capex` overstated FCF. The result is
  cross-checked against Yahoo's reported free cash flow.
- **`pe_ratio`** uses reported diluted EPS (it divided net income by a share count the
  model had to supply) and is null when EPS <= 0. **`dividend_yield`** uses trailing
  12 months of `Ticker.dividends`.
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
- **Statement output adds `missing_fields` and `notes`** alongside `unmapped_labels`, so
  canonical fields Yahoo did not report, and derived values, are visible.
- **`total_liabilities` fallback:** when Yahoo omits it (NVDA annual), it is derived as
  total assets minus total equity, with a note.
- **Quarterly P/E uses TTM EPS** (sum of the last 4 quarters); the spec only defines
  annual. **P/E and P/B are skipped** when the reporting currency differs from the quote
  currency (e.g. TSM: TWD statements, USD price), with a note.
- **`inputs_used` is keyed by period end** (`{period_end: {field: value}}`), holding only
  the inputs the requested metrics read.
- **Null metrics carry a note** naming the missing inputs, e.g. gross margin for banks.
- **`tearsheet/serialize.py` added** (not in the spec's layout) for NaN/inf to `None`,
  rounding, summaries and row downsampling, shared by all tool wrappers.

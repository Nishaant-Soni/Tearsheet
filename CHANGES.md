# Changes

Tracks the refactor described in the refactor spec: tool renames, behavior changes,
deviations from the spec, regression coverage and the evaluation result.

## Tool renames

The old tool names are removed, not aliased. Clients and prompts that call them need
the new names. The `filename`, `prices`, `price_data`, `series`, `dates` and
`financial_data` parameters are gone: tools take a ticker and dates instead.

| Old tool | New tool | Since |
|---|---|---|
| `retrieve_current_price` | `tearsheet_get_quote` | Phase 1 |
| `retrieve_stock_data` | `tearsheet_get_price_history` | Phase 1 |
| `retrieve_ticker_info` | `tearsheet_get_company_info` | Phase 1 |
| `retrieve_dividends` | `tearsheet_get_dividends` | Phase 1 |
| `retrieve_splits` | `tearsheet_get_splits` | Phase 1 |
| `retrieve_financial_statements` | `tearsheet_get_financial_statement` | Phase 2 |
| `mcp_calculate_financial_metrics` | `tearsheet_get_fundamentals` | Phase 2 |
| `mcp_calculate_technical_indicators` | `tearsheet_calculate_indicator` | Phase 3 |
| `mcp_calculate_growth_rates` | `tearsheet_calculate_growth_rates` | Phase 3 |
| `mcp_backtest_strategy` | `tearsheet_backtest_ma_crossover` | Phase 3 |
| `mcp_plot_price_chart` | `tearsheet_plot_price_chart` | Phase 4 |
| `mcp_plot_comparison_chart` | `tearsheet_plot_comparison` | Phase 4 |
| `mcp_plot_financial_metric` | `tearsheet_plot_fundamental` | Phase 4 |
| `mcp_plot_trading_opportunities` | `tearsheet_plot_ma_crossover` | Phase 4 |

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
- **Indicators and the backtest take `ticker` + dates** and fetch prices on the server.
  The model no longer passes price arrays. Indicator output defaults to a summary
  (latest, min, max per series); `response_format="rows"` returns capped rows.
- **`volatility` is annualized:** rolling std of returns times sqrt(252) for daily
  bars (52 weekly, 12 monthly). It was the daily std. Intraday intervals are rejected.
- **MACD** takes `fast`, `slow`, `signal` (12/26/9) and returns `macd`, `signal`,
  `histogram`. It used fixed 12/26/9 and silently ignored `window`.
- **RSI** returns 100 when there are no losses (was inf/NaN) and nulls for the first
  `window` bars. **Bollinger bands** take `num_std`. **ATR and stochastic** use real
  high/low now that OHLC is fetched on the server.
- **Growth:** `annualized_growth_rate` renamed to `cagr`, annualized with
  `periods_per_year`. CAGR is null with a note when the first or last value is <= 0;
  it could return a complex number.
- **Backtest rewritten:** signals at bar t's close fill at bar t+1's open (was the
  signal bar's close, a look-ahead). `cost_bps` (default 5) is charged on each entry
  and exit. Metrics come from a daily mark-to-market equity curve: `max_drawdown`
  with start/end dates now includes drawdowns inside open positions (it only looked
  at trade exits), and `sharpe_ratio` is annualized with `risk_free_rate` (it was
  mean/std of per-trade returns). Adds `cagr`, `annualized_volatility`, `exposure`,
  `avg_trade_return`. `outperformance` renamed to `excess_return`. Zero trades is no
  longer an error.
- **Plot tools take `ticker` + dates** (or `ticker` + `metric` + `period` for
  fundamentals) and fetch data on the server. The `filename` parameter is gone: the
  server names files `{tool}_{TICKERS}_{start}_{end}_{yyyymmddHHMMSS}.png` with
  tickers reduced to `[A-Z0-9-]`, checks the resolved path is inside the data
  directory (it accepted `../../x.png`), and never overwrites an earlier chart.
- **Charts no longer open the system image viewer.** Set `TEARSHEET_OPEN_CHARTS=1` to
  opt in. Charts are saved under `TEARSHEET_DATA_DIR` (default: the repo's `data/`).
- **Plot results** carry the PNG, a text summary (file path, date range, last close,
  period return or signal dates or plotted values) and structured content.
- **Rendering** uses matplotlib's object API (`Figure` + Agg canvas) instead of
  pyplot global state, and runs in a worker thread. Candlesticks use `mplfinance.plot`
  on server-created axes (the deprecated `original_flavor` module is gone).
  `tearsheet_plot_comparison` normalizes to 100 by default.
- **Fundamental charts label values by unit:** margins and returns as percentages,
  leverage and liquidity ratios as multiples (`1.34x`), EBITDA and free cash flow
  scaled to the reporting currency (`$59.5B`, `1.7T TWD`) on both bars and axis, book
  value per share as currency (`$7.71`). Units come from `METRIC_UNITS` in
  `tearsheet/analysis/ratios.py`.
- **Server renamed** from `tearsheet` to `tearsheet_mcp` and given `instructions`:
  prefer ticker-based tools over passing data between tools, ratios are fractions,
  dates are inclusive, summaries are the default.
- **Every tool** has a `tearsheet_` name, typed inputs with enums for fixed choices,
  tool annotations, an output schema, and a docstring (under 25 lines) covering when
  to use it versus related tools, units, outputs and an example call.
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
  `tearsheet/viz/charts.py` forced `Agg` in Phase 0, ahead of the Phase 4 rewrite to
  the object API. PNG output was unchanged.
- **Backtest trades include `signal_date`.** With next-open fills, `entry_date` is the
  day after the crossover. Eval Q4 asks for the crossover (signal) date, so each trade
  in `tearsheet_backtest_ma_crossover` also reports `signal_date` and `exit_signal_date`.
- **Eval answers use the fiscal year ending in 2025.** yfinance serves about four annual
  periods, so older fiscal years would drop out of the data within a year or two.
- **yfinance upgraded to 1.8.0** (from 0.2.61). It stamps dividends and splits at
  market open (09:30) rather than midnight, so the data layer normalizes them to dates.
  All ten eval answers were re-verified as unchanged under 1.8.0.
- **Retrieval tools renamed in Phase 1, not Phase 5.** The new data layer replaced
  their bodies, so they got their final names, typed inputs, annotations and
  structured output at the same time. Analysis and plot tools followed in Phases 3
  and 4.
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
- **Backtest `num_trades` counts completed round trips only.** An open position at the
  end is listed in `trades` with `open_at_end: true`, marked to the last close without
  an exit cost. The old code force-closed it and counted it.
- **Backtest adds `buy_signal_dates` and `sell_signal_dates`**, listing every crossover
  (including a sell signal while flat, which does not trade), and an `adjusted` flag.
- **Indicators accept `interval`** (needed to annualize volatility and to reject it
  for intraday bars) and are computed from bars in the requested range only, so the
  first values are warm-up nulls. No extra history is fetched before `start_date`.
- **RSI is 50 when the price does not move at all** (both average gain and loss are
  0); the spec only defines the zero-loss case.
- **Period growth divides by |prev|**, as before, so -50 to -25 is +0.5.
- **Default data dir is the repo's `data/` folder**, not `./data` relative to the
  working directory, so charts land in the same place however the server is launched
  (Claude Desktop may start it with a different cwd).
- **Plot tools return `CallToolResult`** (image + text) annotated with a `ChartResult`
  model, so they still publish an `outputSchema` and `structuredContent`.
- **`tearsheet_plot_fundamental` plots statement metrics only.** `pe_ratio`,
  `pb_ratio` and `dividend_yield` exist only for the latest period, so they are not in
  its `metric` enum.
- **Added `tearsheet/viz/storage.py`** (file naming, path checks, opt-in viewer) and
  `tearsheet/tools/common.py` (the fundamentals fetch-and-compute step shared by
  `tearsheet_get_fundamentals` and `tearsheet_plot_fundamental`), neither in the
  spec's layout. `viz/charts.py` stays pure.
- **`tearsheet/serialize.py` added** (not in the spec's layout) for NaN/inf to `None`,
  rounding, summaries and row downsampling, shared by all tool wrappers.

## Regression coverage

Each problem from the refactor spec has a test that fails on the original code. The
P4/P5 scenarios were re-run against commit `41f093a` to confirm the old behavior.

| Problem | Old behavior | Test |
|---|---|---|
| FCF sign | OCF 500, capex -100 gave 600 | `test_ratios.py::test_fcf_subtracts_absolute_capex` |
| D/E definition | total liabilities / equity (1.5 instead of 0.4) | `test_ratios.py::test_debt_to_equity_uses_total_debt_not_liabilities` |
| Volatility | daily std labelled annualized | `test_indicators.py::test_volatility_is_annualized_daily_std` |
| MACD | fixed 12/26/9, `window` silently ignored | `test_indicators.py::test_macd_uses_fast_slow_signal`, `test_macd_ignores_window` |
| Growth | complex number across sign changes | `test_growth.py::test_sign_change_cagr_is_none_with_note` |
| Backtest drawdown | only at trade exits (-14.5% for a -21.6% dip) | `test_backtest.py::test_intra_trade_drawdown_is_captured` |
| Backtest fills | signal bar close (look-ahead) | `test_backtest.py::test_fill_is_next_open_not_signal_close` |
| Backtest costs | none | `test_backtest.py::test_cost_bps_changes_total_return_by_expected_amount` |
| Backtest Sharpe | per-trade mean/std, not annualized | `test_backtest.py::test_sharpe_and_volatility_formulas`, `test_flat_series_sharpe_is_none` |
| Path traversal | `os.path.join(data, filename)` accepted `../../x.png` | `test_plot_paths.py::test_crafted_ticker_cannot_escape_data_dir`, `test_tool_schemas.py::test_no_filenames_or_price_arrays` |
| Image viewer | opened on every plot | `test_plot_tools.py` (`no_subprocess` fixture), `test_plot_paths.py::test_viewer_only_opens_when_enabled` |
| Overwritten charts | fixed default names | `test_plot_paths.py::test_same_second_does_not_overwrite` |
| pyplot state | `plt.scatter` mixed with `ax.*` | `test_charts.py::test_charts_never_use_pyplot_figures` |
| `eval` | `custom_formula_evaluator` | `test_hygiene.py::test_no_eval_or_exec_in_source` |
| Model as data pipe (P1) | tools took price arrays | `test_tool_schemas.py::test_no_filenames_or_price_arrays` |
| Fundamentals pipeline (P2) | no label mapping, no market block | `test_fundamentals_mapping.py`, `test_fundamentals_tools.py` |
| Return types (P3) | JSON strings in dicts | `test_market.py::test_dividends_are_dated_records`, `test_retrieve_tools.py` |
| Errors (P6) | `{"error": ...}` or `{}` as success | `test_tool_schemas.py::test_bad_ticker_is_error` |
| Payload size (P6) | unbounded rows | `test_serialize.py::test_rows_truncated_flag_and_nan`, `test_retrieve_tools.py::test_price_history_rows_truncated` |
| Blocking calls (P6) | sync tools on the event loop | `test_hygiene.py::test_yfinance_calls_run_off_the_event_loop`, `test_chart_rendering_runs_off_the_event_loop` |
| Slow quote (P6) | `.info` for the currency | `test_market.py::test_quote_uses_fast_info_not_info` |

Tests run offline: yfinance is replaced by a fake and outbound sockets are refused.
`uv run pytest -m live` runs four optional checks against Yahoo Finance.

## Evaluation

Ten questions in `evaluation.xml` (answers verified independently by
`evals/ground_truth.py`) were run in Claude Desktop with Claude Opus 5.5 (medium
reasoning, code execution on) against the old and new tool surfaces. Full results are
in `evals/EVAL_RESULTS.md`.

| Measure | Before | After |
|---|---|---|
| Accuracy | 10/10 | 10/10 |
| Median tool calls | 2 | 2 |
| Total tool calls | 18 | 17 |

Accuracy was already 10/10 on the old surface, and call counts barely changed. The
difference is where the computation happens: on the old surface Claude computed
moving averages in `bash_tool` (2 of 18 calls) and worked out ratios from raw
statements to avoid the buggy metric tools. On the new surface every figure came from
a Tearsheet tool, with no `bash_tool` use.

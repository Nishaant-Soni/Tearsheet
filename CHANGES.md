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
  a schema description on every parameter, tool annotations, an output schema, and a
  docstring (under 25 lines) covering when to use it versus related tools, units,
  outputs and an example call.
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
  for intraday bars). Until addendum A1 they were computed from bars in the
  requested range only; A1 replaced that with warm-up bars (see below).
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
- **Tests fake yfinance instead of monkeypatching `data/`.** The spec says to
  monkeypatch the data layer. The tests replace `yfinance.Ticker` and `yfinance.Search`
  with an in-memory fake instead, so the data layer itself (normalization, caching,
  error mapping) is exercised too, and outbound sockets are refused as a backstop. The
  scenario price series (trending, flat, crossover-producing, intra-trade drawdown) are
  built in the test modules that use them (`test_backtest.py`, `test_analysis_tools.py`,
  `test_tool_schemas.py`); `conftest.py` holds the shared builders (`make_ohlcv`,
  `make_actions`, `make_statement`) and the fake.
- **Eval results do not record tokens.** The spec asks for input/output tokens if the
  client reports them. Claude Desktop does not, so the Tokens column was dropped from
  `evals/EVAL_RESULTS.md` rather than left as `n/a` in every row.
- **Eval Q10 can be answered with one tool call.** The spec requires every question to
  need 2 or more calls. Q10 (NVDA revenue CAGR) was meant as statement +
  `tearsheet_calculate_growth_rates`, but one statement call returns both revenue
  figures and Claude computed the CAGR by hand in both runs (1 call each). The question
  was kept unchanged so the before/after comparison stays like-for-like. Q1 needs three
  splits calls on both surfaces; Claude answered it from its own knowledge in both runs.
- **`tearsheet/serialize.py` added** (not in the spec's layout) for NaN/inf to `None`,
  rounding, summaries and row downsampling, shared by all tool wrappers.

## Addendum A1: warm-up bars

Moving averages and indicators were computed only from bars inside the requested
range, so a 50-day MA was undefined for the first ~50 trading days and early signals
were missed (MSFT 20/50 from 2023-01-01 found only the 2023-10-25 buy, with 18%
exposure). Now:

- **Warm-up history.** `tearsheet/data/warmup.py` fetches bars before `start_date` in
  the same cached `get_history` call and keeps only as many as needed. The caller's
  range is validated exactly as before; intraday warm-up is clamped to Yahoo's lookback
  window with a note instead of raising. Fewer available bars (new listings) give a
  note with the count, not an error. Outputs report `warmup_bars_used`.
- **Backtest.** SMAs and signals use warm-up plus range; trading and every metric start
  at the first in-range bar. A signal on the last warm-up bar fills at the first
  in-range open and keeps its pre-range `signal_date`. New `entry_mode`:
  `"crossover"` (default, fresh cross only) or `"state"` (long whenever short > long).
  New outputs `entry_mode`, `warmup_bars_used`, `warmup_start`. The old requirement of
  `long_window + 2` bars inside the range is gone: a backtest needs `long_window` bars
  including warm-up.
- **Buy-and-hold basis changed:** `buy_and_hold_return` now runs from the open of the
  first in-range bar (the earliest fill the strategy could get) to the last close,
  without costs. It was first close to last close.
- **Indicators** compute on warm-up plus range and return only in-range values;
  summary, rows and `total_rows` cover the range. With enough history the first
  in-range value is defined.
- **Crossover chart** uses the backtest's warm-up and signal computation (same
  `entry_mode`) and draws only the range, so it lists the same signal dates as the
  backtest. A signal on the last warm-up bar is listed in the summary but not drawn.
- MSFT 20/50 from 2023-01-01 now finds the 2023-02-07 and 2023-10-25 buys, exposure
  69.6%, excess return -24.8% (was -47.8%).

Deviations from the addendum:

- **Warm-up for recursive indicators is longer than 3x window.** The addendum's own
  acceptance test (values agree to 1e-3 between 3x and 10x warm-up) fails at 3x:
  measured on AAPL, NVDA, KO and a synthetic series, the largest differences were
  0.009 for EMA, 0.83 RSI points, 0.046 for ATR and 0.024 for MACD at 3*slow+signal.
  EMA forgets its seed by about e^-2 per window and Wilder smoothing (RSI, ATR) by
  about e^-1. The warm-up is 6x window for EMA, 12x window for RSI and ATR, and
  5x(slow+signal) for MACD; against a 20x reference the worst differences were
  2.8e-4, 1.0e-4, 2.7e-5 and 2.8e-4. Tests assert < 1e-3 for each.
- **Stochastic uses window + 2 warm-up bars**, not window, because %D averages the
  last 3 %K values; with window bars its first two in-range values would be null.
- **The warm-up helper returns a `WarmupHistory`** (frame, first in-range position,
  notes) rather than a `(DataFrame, int)` tuple, so short-history and clamp notes reach
  the tool output.
- **Eval v1 results predate A1.** Q4 and Q5 define their moving averages "using daily
  closes from" the range start, the pre-A1 convention, and their ground truth follows
  that wording. Under the new default the server reports earlier crosses: GOOGL's first
  2023 buy becomes 2023-02-01 (Q4's expected answer is GOOGL:2023-03-27). Q6's RSI is
  unchanged at 57.95. The recorded results are kept as measured.

## Addendum A2: negative equity

Companies with negative stockholders' equity after large buybacks got sign-flipped
ratios: SBUX showed `roe` of -37.7%, -51.6%, -50.5% and -22.9% for FY2022 to FY2025
although net income was positive every year, and `debt_to_equity` around -3.

- `roe`, `debt_to_equity` and `liabilities_to_equity` are null when equity is <= 0,
  with the note `"<metric>: undefined because stockholders' equity is zero or
  negative (<value>)."` The inputs stay in `inputs_used`. `pb_ratio` already behaved
  this way.
- `book_value_per_share` keeps its negative value, with the note
  `"book_value_per_share is negative because stockholders' equity is negative."`
- ROA, margins and liquidity ratios are unchanged.
- `tearsheet_plot_fundamental` draws null periods as "n/a" bars and puts the reason
  in the text summary. When every period is null it raises an error stating the
  reason; it used to say "Yahoo does not report the inputs", which was wrong for
  negative equity.

## Addendum A3: share count

`shares_outstanding` fell back to `"Share Issued"`, which includes treasury shares, so
book value per share and P/B were understated whenever the fallback was used.

- Fallback order: `"Ordinary Shares Number"`, then `"Share Issued"` minus `"Treasury
  Shares Number"` (note: `"<period>: shares_outstanding derived as shares issued minus
  treasury shares."`), then the deviation below, then `None` with a note.
- **Fallback labels are never listed in `unmapped_labels`.** `"Share Issued"`,
  `"Treasury Shares Number"` and `"Total Equity Gross Minority Interest"` are read by
  the share-count and total-liabilities fallbacks, so they are known labels whether or
  not a given period needs them. `unmapped_labels` lists only labels the server has
  no use for, which is what it is meant to surface. Compared with before A3,
  `"Treasury Shares Number"` and `"Total Equity Gross Minority Interest"` no longer
  appear there (they did when unused); `"Share Issued"` stays hidden as before.
- Checked on AAPL, MSFT, SBUX, KO, JPM, NVDA, TSLA, MCD, BKNG, TSM, BRK-B and XOM:
  issued equals ordinary plus treasury in every case, and all twelve report
  `"Ordinary Shares Number"`, so their share counts are unchanged.

Deviation from the addendum:

- **`"Share Issued"` alone is used when no treasury count is reported**, with the note
  `"<period>: shares_outstanding taken from shares issued; Yahoo reports no treasury
  shares for this period."` The addendum returns `None` here. Yahoo leaves out the
  treasury line for companies that hold no treasury shares (they retire bought-back
  shares): AAPL, MSFT, NVDA, TSLA, SBUX and TSM have no treasury line and issued equal
  to ordinary. Returning `None` would discard a correct count. The note keeps the
  remaining risk (treasury shares that Yahoo fails to report) visible.

## Addendum A4: cache cleanup

Expired entries were removed only when the same key was requested again, and the
per-key locks were never removed, so a long-running server grew without bound.

- Every `set` drops expired entries and locks that no live entry or in-flight load
  needs (anyio hands a released lock straight to the next waiter, so "unlocked with
  nobody waiting" is safe to forget). A failed load removes its own lock.
- `max_entries` (default 256) caps each cache; the entries closest to expiry are
  evicted first.
- Concurrent requests for the same key still share one upstream fetch.

## Addendum A5: partially reported periods

A fiscal period can appear in one statement before the others: SBUX's FY2026 column
exists only in the income statement, with just diluted EPS and diluted shares (from
the earnings release). It showed up as an unexplained "n/a" bar, and it pushed P/B
onto a period with no balance sheet.

- `get_merged_fields` records which statements reported each period end. A period
  missing from any requested statement gets the note `"<period_end>: only <statements>
  reported so far; metrics needing other statements are null."`
- `tearsheet_get_fundamentals` still drops periods where every requested metric is
  null, and now only returns notes about the periods it keeps.
- `tearsheet_plot_fundamental` leaves null periods off both ends of the series and
  names them, with the reason, in the summary. Nulls in the middle stay as "n/a" bars.

Deviations and additions:

- **Older periods use different wording.** A period older than every complete one
  has aged out of a statement's Yahoo window rather than being "reported so far", so
  its note reads `"<period_end>: only <statements> available from Yahoo for this
  period; ..."`.
- **Price-based ratios pick their own period.** `pe_ratio` uses the newest period with
  diluted EPS (TTM: 4 consecutive quarters ending there), `pb_ratio` the newest with
  equity and a share count, `dividend_yield` the newest period. Previously all three
  went on the newest period, so SBUX's P/B read "not reported" instead of "undefined
  because book value per share <= 0". A single "latest complete period" rule was
  rejected because it would have used stale FY2025 EPS for SBUX's P/E. The new
  `as_of_price.applies_to` maps each ratio to its period, and a note says when it is
  not the newest. `applies_to_period_end` is the newest of those periods.
- **Notes that already name their period** no longer repeat it in a
  `(periods: ...)` suffix.

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
| Negative equity (A2) | ROE -37.7% for profitable SBUX | `test_ratios.py::test_equity_ratios_undefined_for_non_positive_equity`, `test_negative_equity_tools.py` |
| Cold-start MAs (A1) | first ~50 days missed | `test_warmup.py` |
| Share count (A3) | issued shares incl. treasury | `test_fundamentals_mapping.py::test_issued_minus_treasury_when_ordinary_missing` |
| Partial periods (A5) | unexplained n/a bars, P/B on a period with no balance sheet | `test_partial_periods.py` |
| Cache growth (A4) | expired entries and locks kept forever | `test_cache.py::test_expired_entries_are_swept_on_next_set`, `test_locks_do_not_outgrow_live_keys`, `test_max_entries_evicts_closest_to_expiry` |

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

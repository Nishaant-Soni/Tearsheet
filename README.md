# Tearsheet

## Introduction
Tearsheet is a **Model Context Protocol (MCP) server** that lets LLMs (Claude, Cursor, or other MCP clients) retrieve, analyze, and visualize stock prices and financial statement data from Yahoo Finance. It is built for quantitative trading research, investment analysis, and financial education.

Every analysis and plot tool takes a **ticker and a date range** and fetches the data on the server, so the model never copies price arrays between tools. Financial statements are normalized on the server into standard field names, and ratios are computed there too.

## Usage Scenarios
- **LLM-driven trading analysis**: fetch prices, financial statements and technical indicators to generate trading insights.
- **Financial metric calculation**: margins, leverage, liquidity, cash flow and valuation ratios per fiscal period.
- **Visualization**: line and candlestick price charts, normalized comparisons, fundamental trends and crossover signal charts.
- **Backtesting**: run a moving-average crossover strategy with realistic fills and costs, and get return, risk and trade statistics.
- **Automated research**: answer questions like "What is the ROE of AAPL?", "How did MSFT do in the last 6 months?" or "Plot buy/sell signals for TSLA."

## Available Tools

### Data Retrieval
| Tool | Description |
|------|-------------|
| `tearsheet_get_quote` | Latest price, previous close, day change, market cap and shares outstanding |
| `tearsheet_get_price_history` | OHLCV history for 1 to 10 tickers. Returns a summary by default, rows on request |
| `tearsheet_get_company_info` | Name, type, exchange, sector, industry, country and website |
| `tearsheet_get_dividends` | Cash dividends per share by ex-date |
| `tearsheet_get_splits` | Stock split history (new shares per old share) |
| `tearsheet_get_financial_statement` | Income statement, balance sheet or cash flow, annual or quarterly, with standard field names |

### Metrics & Analysis
| Tool | Description |
|------|-------------|
| `tearsheet_get_fundamentals` | 17 ratios per fiscal period: margins, debt-to-equity, current/quick ratio, free cash flow, ROE, ROA, P/E, P/B, dividend yield and more |
| `tearsheet_calculate_indicator` | SMA, EMA, RSI, MACD, annualized volatility, Bollinger Bands, ATR or Stochastic for a ticker and date range |
| `tearsheet_calculate_growth_rates` | Period-over-period growth and CAGR for a short series of numbers you pass in |
| `tearsheet_backtest_ma_crossover` | Long-only SMA crossover backtest with warm-up bars and two entry modes (fresh crossover or short-above-long state): total and excess return, CAGR, volatility, Sharpe, max drawdown, trades and signal dates |

### Visualization
| Tool | Description |
|------|-------------|
| `tearsheet_plot_price_chart` | Line chart of closes, or candlesticks with a volume panel |
| `tearsheet_plot_comparison` | 2 to 8 tickers on one chart, normalized to 100 by default |
| `tearsheet_plot_fundamental` | One financial metric across fiscal periods as a bar chart |
| `tearsheet_plot_ma_crossover` | Closes with both SMAs and buy/sell signal markers |

Plot tools return the image, a short text summary (file path, date range, last close, return or signal dates) and structured data. Charts are saved under the data directory with names chosen by the server. They are not opened in an image viewer unless you turn that on (see [Configuration](#configuration)).

### Conventions
- Ratios, margins, returns and growth rates are **fractions**: `0.25` means 25%.
- Price-based ratios each use the **newest fully reported period that has their inputs**: P/E the newest diluted EPS, P/B the newest balance sheet, dividend yield the newest period. `as_of_price.applies_to` says which.
- A fiscal period that statements have **only partly reported** so far (for example, a column with diluted EPS but no revenue or net income yet) gets a note saying what is there, and price-based ratios skip it in favour of the newest fully reported period. Fundamental charts leave periods with no value off either end of the series and say why; gaps in the middle show as "n/a" bars.
- `roe`, `debt_to_equity`, `liabilities_to_equity` and `pb_ratio` are **null when stockholders' equity is zero or negative** (common after large buybacks, e.g. SBUX, MCD, BKNG), with one note per metric giving the equity range. `book_value_per_share` stays negative, and ROA and the margins are unaffected.
- Dates are `YYYY-MM-DD`. `end_date` is **inclusive** and defaults to today.
- Price history and indicators return a **summary** by default. Pass `response_format="rows"` for individual bars, capped at `max_rows` (default 100, max 1000). Longer series are evenly downsampled and flagged `truncated`.
- Prices are adjusted for splits and dividends by default.
- Indicators, the backtest and the crossover chart fetch **warm-up bars** before `start_date`, so moving averages and indicators are defined from the first day of the range. Only in-range values are returned, and `warmup_bars_used` says how many were used. If less history exists (a recent listing, or Yahoo's intraday limits), a note says how many bars were available.
- Intraday limits are checked up front: `1m` covers at most 7 days within the last 30, `5m`/`15m`/`30m` the last 60 days, `1h` the last 730 days.
- Errors come back as MCP errors (`isError: true`) that say what to change, e.g. a ticker typo (`BRK.B` suggests `BRK-B`) or a date range that is too short.

### Backtest assumptions
`tearsheet_backtest_ma_crossover` uses daily bars and:
- computes the SMAs over `long_window + 1` warm-up bars plus the range, then trades and measures only from the first in-range bar,
- detects a crossover at the **close** of bar t (short SMA above the long SMA after being at or below it the day before; the reverse for a sell),
- **fills at the open of bar t+1**, never at the signal bar's close. A signal on the last bar is not filled. A signal on the last warm-up bar fills at the first in-range open and keeps its earlier `signal_date`,
- with `entry_mode="crossover"` (default) enters only on a fresh buy signal; with `entry_mode="state"` is long whenever the short SMA is above the long SMA, including from the first in-range bar,
- lists only crossovers in `buy_signal_dates` and `sell_signal_dates`. A state-mode entry at the start of the range is not a crossover, so it appears in `trades` but not in `buy_signal_dates`,
- is long-only, fully invested or flat,
- charges `cost_bps` (default 5) on every entry and exit, with no other slippage model,
- marks the position to market every day, so max drawdown includes dips during open trades,
- annualizes volatility and Sharpe with 252 trading days. Sharpe uses `risk_free_rate` (default 0),
- counts completed round trips in `num_trades`. A position still open at the end is listed with `open_at_end: true`,
- measures `buy_and_hold_return` from the **open of the first in-range bar** (the earliest fill the strategy could get) to the last close, without costs.

`tearsheet_plot_ma_crossover` uses the same warm-up and signal computation, so for the same inputs it lists the same signal dates as the backtest.

## Installation
1. **Clone the repository**
   ```bash
   git clone https://github.com/Nishaant-Soni/Tearsheet.git
   cd Tearsheet
   ```
2. **Install dependencies** (requires [uv](https://github.com/astral-sh/uv) and Python 3.12+)
   ```bash
   uv sync
   ```

## How to Run
1. **Configure your LLM client (Claude, Cursor, etc.)** to connect to the MCP server.

    In Claude Desktop, go to Settings → Developer → Edit Config and add a new MCP server entry:
    ```json
    {
      "mcpServers": {
        "tearsheet": {
          "command": "uv",
          "args": [
            "--directory",
            "/path/to/Tearsheet",
            "run",
            "main.py"
          ]
        }
      }
    }
    ```
    Restart Claude Desktop. The `tearsheet_*` tools should now be listed in your Claude tools.

2. **Start talking with your trading assistant!**

    Example queries:

    - Compare the stock prices of Nvidia and AMD in the past month.
    - How's Tesla stock looking in the past 3 months?
    - Plot the moving-average crossover signals for Microsoft over the past 3 months.
    - What is the ROE and P/E ratio of Apple?
    - Show me the dividend history of Coca-Cola.
    - Backtest a 20/50-day moving-average crossover strategy on TSLA for the past year.
    - Plot a candlestick chart for NVDA over the last 30 days.
    - Compare AAPL, MSFT, and GOOGL returns over the past 6 months on a normalized chart.
    - Plot Microsoft's free cash flow over the last four fiscal years.

3. **Inspect the server directly** (optional) with the MCP Inspector:
    ```bash
    npx @modelcontextprotocol/inspector uv run main.py
    ```

## Configuration
| Environment variable | Default | Effect |
|---|---|---|
| `TEARSHEET_DATA_DIR` | the repo's `data/` folder | Where chart PNGs are saved |
| `TEARSHEET_OPEN_CHARTS` | unset (off) | Set to `1` to open each new chart in the system image viewer |

In Claude Desktop, set these with an `"env": {...}` block next to `"command"` in the server entry.

## Development
```bash
uv run pytest              # offline test suite (yfinance is faked, network access is refused)
uv run pytest -m live      # optional checks against live Yahoo Finance data
uv run ruff check .        # lint
uv run ruff format .       # format
```

Project layout:
```
main.py, server.py          entry point and the shared MCP server
tearsheet/data/             the only code that calls yfinance (async, cached)
tearsheet/analysis/         pure functions: indicators, growth, backtest, ratios
tearsheet/viz/              chart rendering (PNG bytes) and chart file storage
tearsheet/tools/            thin MCP tool wrappers
tests/                      offline tests and optional live tests
evals/, evaluation.xml      before/after evaluation of the tool surface
```

See [CHANGES.md](CHANGES.md) for the mapping from the old tool names, behavior changes and fixed calculation bugs, and [evals/EVAL_RESULTS.md](evals/EVAL_RESULTS.md) for the evaluation results.

# MCP Server for Financial Analysis

## Introduction
This project is a **Model Context Protocol (MCP) server** designed to enable LLMs (such as Claude, Cursor, or GPT-based agents) to retrieve, analyze, and visualize stock prices and financial report data. It provides a set of robust tools for quantitative trading research, investment analysis, and financial education.

## Usage Scenarios
- **LLM-driven trading analysis**: Let LLMs fetch and analyze stock data, financial statements, and technical indicators to generate trading insights.
- **Financial metric calculation**: Compute key ratios and metrics from income statements, balance sheets, and cash flow tables.
- **Visualization**: Generate price charts (line or candlestick), financial metric trends, normalized comparisons, and trading signal charts.
- **Backtesting**: Run a moving-average crossover strategy and get performance stats (total return, Sharpe ratio, max drawdown, win rate).
- **Automated research**: Integrate with LLMs to answer questions like "What is the ROE of AAPL?", "Show me the last 6 months of MSFT price data.", or "Plot buy/sell signals for TSLA."

## Features
- Retrieve real-time and historical stock prices (single or multiple tickers)
- Retrieve dividends and stock splits history
- Retrieve general ticker info and fundamentals
- Extract and analyze financial statements (income statement, balance sheet, cash flow)
- Calculate key financial metrics (gross margin, operating margin, net profit margin, EBITDA, debt-to-equity, current ratio, quick ratio, book value per share, free cash flow, cash flow margin, ROE, ROA, P/E, P/B, dividend yield)
- Calculate technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, volatility, ATR, Stochastic)
- Calculate period-over-period and annualized growth rates
- Backtest a moving-average crossover (Golden Cross / Death Cross) strategy
- Visualize price data with line and candlestick charts
- Plot financial metrics over time
- Compare multiple tickers side-by-side with optional normalization
- Plot trading signals and opportunities
- LLM-friendly, JSON-serializable outputs

## Available Tools

### Data Retrieval
| Tool | Description |
|------|-------------|
| `retrieve_current_price` | Current price and related info for a ticker |
| `retrieve_stock_data` | Historical OHLCV data for one or more tickers |
| `retrieve_financial_statements` | Annual income statement, balance sheet, or cash flow |
| `retrieve_ticker_info` | General info and fundamentals for a ticker |
| `retrieve_dividends` | Dividend history for a ticker |
| `retrieve_splits` | Stock split history for a ticker |

### Metrics & Analysis
| Tool | Description |
|------|-------------|
| `mcp_calculate_financial_metrics` | Compute a financial ratio or metric from statement data |
| `mcp_calculate_technical_indicators` | Compute SMA, EMA, RSI, MACD, Bollinger Bands, volatility, ATR, or Stochastic |
| `mcp_calculate_growth_rates` | Period-over-period and annualized growth rates for a time series |
| `mcp_backtest_strategy` | Backtest a MA crossover strategy; returns total return, Sharpe ratio, max drawdown, win rate, and individual trades |

### Visualization
| Tool | Description |
|------|-------------|
| `mcp_plot_price_chart` | Line or candlestick price chart from OHLCV data |
| `mcp_plot_financial_metric` | Plot a financial metric over time |
| `mcp_plot_comparison_chart` | Compare multiple tickers or metrics; supports normalization to a common base of 100 |
| `mcp_plot_trading_opportunities` | Price chart overlaid with MA crossover buy/sell signals |

> **Note:** All visualization tools automatically save charts to the `data/` directory and open them with your system's default image viewer (macOS, Linux, and Windows are supported).

## Installation
1. **Clone the repository**
   ```bash
   git clone https://github.com/Nishaant-Soni/MCP_Server_for_Financial_Analysis.git
   cd MCP_Server_for_Financial_Analysis
   ```
2. **Install dependencies** (requires [uv](https://github.com/astral-sh/uv))
   ```bash
   uv sync
   ```

## How to Run
1. **Configure your LLM client (Claude, Cursor, etc.)** to connect to the MCP server and call the available tools.

    Go to Claude settings → Developer → Edit Config and add a new MCP server entry:
    ```json
    {
      "mcpServers": {
        "trader-mcp": {
          "command": "uv",
          "args": [
            "--directory",
            "/path/to/MCP_Server_for_Financial_Analysis",
            "run",
            "main.py"
          ]
        }
      }
    }
    ```
    `trader-mcp` should now be listed in your Claude tools.

2. **Start talking with your trading assistant!**

    Example queries:

    - Compare the stock prices of Nvidia and AMD in the past month.
    - How's Tesla stock looking in the past 3 months?
    - Plot the trading opportunities of Microsoft in the past 3 months.
    - What is the ROE and P/E ratio of Apple?
    - Show me the dividend history of Coca-Cola.
    - Backtest a moving-average crossover strategy on TSLA for the past year.
    - Plot a candlestick chart for NVDA over the last 30 days.
    - Compare AAPL, MSFT, and GOOGL returns over the past 6 months on a normalized chart.

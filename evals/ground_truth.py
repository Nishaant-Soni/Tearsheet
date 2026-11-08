"""Independent ground truth for evaluation.xml.

Computes every answer with yfinance and pandas directly. Nothing here imports
the server code, so bugs in the tools cannot leak into the expected answers.

Usage (from the repo root, needs network):
    uv run python evals/ground_truth.py              # print answers and checks
    uv run python evals/ground_truth.py --write-xml  # also regenerate evaluation.xml

Every answer is also checked for fragility: a value that sits close to a
rounding boundary, or a comparison won by a tiny margin, prints a warning so
the question can be reworded before it is used.
"""

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- helpers


def history(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Daily bars, adjusted (yfinance default), end date exclusive."""
    df = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
    if df.empty:
        raise RuntimeError(f"no price data for {ticker} {start}..{end}")
    df.index = df.index.tz_localize(None)
    return df


def statement(ticker: str, name: str) -> pd.DataFrame:
    df = getattr(yf.Ticker(ticker), name)
    if df.empty:
        raise RuntimeError(f"no {name} for {ticker}")
    return df


def fiscal_column(df: pd.DataFrame, year: int) -> pd.Timestamp:
    """The single statement column whose period end falls in `year`."""
    cols = [c for c in df.columns if pd.Timestamp(c).year == year]
    if len(cols) != 1:
        raise RuntimeError(f"expected one fiscal period ending in {year}, got {cols}")
    return cols[0]


def field_value(df: pd.DataFrame, col: pd.Timestamp, label: str) -> float:
    if label not in df.index:
        raise RuntimeError(f"label {label!r} missing; have {list(df.index)[:10]}...")
    v = df.loc[label, col]
    if pd.isna(v):
        raise RuntimeError(f"{label!r} is NaN for {col}")
    return float(v)


def golden_crosses(close: pd.Series, short: int, long: int) -> pd.Index:
    """Dates where the short SMA closes above the long SMA after being at or below."""
    s = close.rolling(short).mean()
    lg = close.rolling(long).mean()
    cross = (s > lg) & (s.shift(1) <= lg.shift(1))
    return close.index[cross]


def wilder_rsi(close: pd.Series, window: int, seed: str) -> pd.Series:
    """RSI with Wilder smoothing.

    seed="ewm": recursive average from the first bar (pandas ewm, adjust=False).
    seed="sma": textbook Wilder, first average is a simple mean of `window` bars.
    """
    delta = close.diff()
    gain = delta.clip(lower=0).fillna(0.0)
    loss = (-delta).clip(lower=0).fillna(0.0)
    if seed == "ewm":
        ag = gain.ewm(alpha=1 / window, adjust=False).mean()
        al = loss.ewm(alpha=1 / window, adjust=False).mean()
    else:
        ag = pd.Series(index=close.index, dtype=float)
        al = pd.Series(index=close.index, dtype=float)
        ag.iloc[window] = gain.iloc[1 : window + 1].mean()
        al.iloc[window] = loss.iloc[1 : window + 1].mean()
        for i in range(window + 1, len(close)):
            ag.iloc[i] = (ag.iloc[i - 1] * (window - 1) + gain.iloc[i]) / window
            al.iloc[i] = (al.iloc[i - 1] * (window - 1) + loss.iloc[i]) / window
    return 100 - 100 / (1 + ag / al)


def near_rounding_edge(x: float, dp: int, tol: float = 0.1) -> bool:
    """True if x is within `tol` of a rounding step from a .5 boundary."""
    scaled = x * 10**dp
    return abs(scaled - math.floor(scaled) - 0.5) < tol


@dataclass
class Result:
    answer: str
    details: dict
    warnings: list[str] = field(default_factory=list)


@dataclass
class Question:
    qid: int
    text: str
    old_tools: str
    new_tools: str
    compute: Callable[[], Result]


def pick(values: dict[str, float], dp: int, larger: bool = True) -> Result:
    """Answer 'TICKER:VALUE' for the larger (or smaller) of two or more values."""
    ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=larger)
    (winner, wv), (_, rv) = ranked[0], ranked[1]
    warnings = []
    if abs(wv - rv) < 10**-dp * 5:
        warnings.append(f"close comparison: {ranked}")
    if near_rounding_edge(wv, dp):
        warnings.append(f"{winner}={wv} is near a rounding boundary at {dp} dp")
    return Result(
        f"{winner}:{wv:.{dp}f}", {k: round(v, 6) for k, v in values.items()}, warnings
    )


# --------------------------------------------------------------- questions


def q1() -> Result:
    ratios = {}
    for t in ("NVDA", "AVGO", "CMG"):
        s = yf.Ticker(t).splits
        s.index = s.index.tz_localize(None)
        in_2024 = s[(s.index >= "2024-01-01") & (s.index < "2025-01-01")]
        if len(in_2024) != 1:
            raise RuntimeError(f"{t}: expected one 2024 split, got {in_2024}")
        ratios[t] = float(in_2024.iloc[0])
    best = max(ratios, key=ratios.get)
    return Result(f"{best}:{ratios[best]:g}", ratios)


def q2() -> Result:
    totals = {}
    for t in ("KO", "PEP"):
        d = yf.Ticker(t).dividends
        d.index = d.index.tz_localize(None)
        d = d[(d.index >= "2023-01-01") & (d.index < "2024-01-01")]
        totals[t] = float(d.sum())
    return pick(totals, 3)


def q3() -> Result:
    s = yf.Ticker("NVDA").splits
    s.index = s.index.tz_localize(None)
    split_day = s[(s.index >= "2024-06-01") & (s.index < "2024-07-01")].index[0]
    df = history("NVDA", "2024-05-01", "2024-12-01")
    before = df[df.index < split_day]["Close"]
    start_close = before.iloc[-1]
    end_close = df["Close"].iloc[-1]
    ret = (end_close / start_close - 1) * 100
    warnings = []
    if df.index[-1] != pd.Timestamp("2024-11-29"):
        warnings.append(f"last bar is {df.index[-1].date()}, expected 2024-11-29")
    if near_rounding_edge(ret, 1):
        warnings.append(f"return {ret} near rounding boundary")
    return Result(
        f"{ret:.1f}",
        {
            "split_date": str(split_day.date()),
            "start_date": str(before.index[-1].date()),
            "start_close": round(start_close, 4),
            "end_close": round(end_close, 4),
            "return_pct": round(ret, 4),
        },
        warnings,
    )


def q4() -> Result:
    firsts = {}
    for t in ("MSFT", "GOOGL"):
        close = history(t, "2023-01-01", "2023-12-31")["Close"]
        crosses = golden_crosses(close, 20, 50)
        firsts[t] = crosses[0]
    winner = min(firsts, key=firsts.get)
    warnings = []
    if firsts["MSFT"] == firsts["GOOGL"]:
        warnings.append("tie on first cross date")
    return Result(
        f"{winner}:{firsts[winner].date()}",
        {k: str(v.date()) for k, v in firsts.items()},
        warnings,
    )


def q5() -> Result:
    counts, dates = {}, {}
    warnings = []
    for t in ("AMZN", "META"):
        close = history(t, "2022-01-01", "2022-12-31")["Close"]
        crosses = golden_crosses(close, 10, 30)
        counts[t] = len(crosses)
        dates[t] = [str(d.date()) for d in crosses]
        if len(crosses) and crosses[-1] == close.index[-1]:
            warnings.append(f"{t}: cross on last bar (fill semantics may differ)")
    return Result(
        str(sum(counts.values())), {"counts": counts, "dates": dates}, warnings
    )


def q6() -> Result:
    values, warnings = {}, []
    for t in ("AAPL", "MSFT"):
        close = history(t, "2023-01-01", "2023-12-31")["Close"]
        if close.index[-1] != pd.Timestamp("2023-12-29"):
            warnings.append(f"{t}: last bar {close.index[-1].date()}")
        ewm = wilder_rsi(close, 14, "ewm").iloc[-1]
        sma = wilder_rsi(close, 14, "sma").iloc[-1]
        if f"{ewm:.0f}" != f"{sma:.0f}":
            warnings.append(f"{t}: RSI seed changes answer ({ewm} vs {sma})")
        values[t] = float(ewm)
    res = pick(values, 0)
    res.warnings += warnings
    return res


def q7() -> Result:
    margins = {}
    for t in ("MSFT", "GOOGL"):
        df = statement(t, "financials")
        col = fiscal_column(df, 2025)
        gp = field_value(df, col, "Gross Profit")
        rev = field_value(df, col, "Total Revenue")
        margins[t] = gp / rev
    return pick(margins, 2)


def q8() -> Result:
    ratios = {}
    for t in ("AAPL", "MSFT"):
        df = statement(t, "balance_sheet")
        col = fiscal_column(df, 2025)
        debt = field_value(df, col, "Total Debt")
        equity = field_value(df, col, "Stockholders Equity")
        ratios[t] = debt / equity
    return pick(ratios, 2)


def q9() -> Result:
    fcf, warnings = {}, []
    for t in ("AAPL", "GOOGL"):
        df = statement(t, "cashflow")
        col = fiscal_column(df, 2025)
        ocf = field_value(df, col, "Operating Cash Flow")
        capex = field_value(df, col, "Capital Expenditure")
        value = (ocf - abs(capex)) / 1e9
        if "Free Cash Flow" in df.index and not pd.isna(df.loc["Free Cash Flow", col]):
            reported = df.loc["Free Cash Flow", col] / 1e9
            if abs(reported - value) > 0.05:
                warnings.append(f"{t}: computed FCF {value} != reported {reported}")
        fcf[t] = value
    res = pick(fcf, 1)
    res.warnings += warnings
    return res


def q10() -> Result:
    df = statement("NVDA", "financials")
    first = field_value(df, fiscal_column(df, 2024), "Total Revenue")
    last = field_value(df, fiscal_column(df, 2026), "Total Revenue")
    cagr = ((last / first) ** (1 / 2) - 1) * 100
    warnings = (
        [f"CAGR {cagr} near rounding boundary"] if near_rounding_edge(cagr, 1) else []
    )
    return Result(
        f"{cagr:.1f}",
        {"revenue_fy2024": first, "revenue_fy2026": last, "cagr_pct": round(cagr, 4)},
        warnings,
    )


QUESTIONS = [
    Question(
        1,
        "NVDA, AVGO and CMG each had a stock split in 2024. Which one had the largest "
        "split ratio, and what was the ratio (new shares per old share)? "
        "Answer in the form TICKER:RATIO, e.g. ABC:3.",
        "retrieve_splits x3",
        "tearsheet_get_splits x3",
        q1,
    ),
    Question(
        2,
        "Between KO and PEP, which paid the higher total dividend per share across "
        "dividends with ex-dates in calendar year 2023, and what was that total in USD? "
        "Answer in the form TICKER:AMOUNT rounded to 3 decimals, e.g. ABC:1.234.",
        "retrieve_dividends x2",
        "tearsheet_get_dividends x2",
        q2,
    ),
    Question(
        3,
        "Using adjusted daily closes, what was NVDA's percentage price return from the "
        "last close before its June 2024 stock split took effect to the last close of "
        "November 2024? Answer as a percentage rounded to 1 decimal, without the % sign, "
        "e.g. 12.3.",
        "retrieve_splits + retrieve_stock_data",
        "tearsheet_get_splits + tearsheet_get_price_history",
        q3,
    ),
    Question(
        4,
        "Using daily closes from 2023-01-01 to 2023-12-31, find the first date on which "
        "the 20-day simple moving average closed above the 50-day simple moving average "
        "after being at or below it the previous day (the signal date, not a next-day "
        "fill), for MSFT and for GOOGL. Which ticker's first signal came earlier, and "
        "on what date? Answer in the form TICKER:YYYY-MM-DD.",
        "retrieve_stock_data + mcp_backtest_strategy x2",
        "tearsheet_backtest_ma_crossover x2 (signal dates)",
        q4,
    ),
    Question(
        5,
        "Using daily closes from 2022-01-01 to 2022-12-31, count the days on which the "
        "10-day simple moving average closed above the 30-day simple moving average "
        "after being at or below it the previous day. What is the combined count for "
        "AMZN and META? Answer with a single integer.",
        "retrieve_stock_data + mcp_backtest_strategy x2",
        "tearsheet_backtest_ma_crossover x2",
        q5,
    ),
    Question(
        6,
        "Compute the 14-day RSI (Wilder smoothing) from daily closes between 2023-01-01 "
        "and 2023-12-31 for AAPL and for MSFT, and take the value on 2023-12-29. Which "
        "ticker had the higher RSI, and what was it? Answer in the form TICKER:VALUE "
        "rounded to the nearest integer, e.g. ABC:55.",
        "retrieve_stock_data + mcp_calculate_technical_indicators x2",
        "tearsheet_calculate_indicator x2",
        q6,
    ),
    Question(
        7,
        "For each company's fiscal year ending in 2025, which of MSFT and GOOGL had the "
        "higher gross margin (gross profit divided by total revenue), and what was it? "
        "Answer in the form TICKER:MARGIN as a fraction rounded to 2 decimals, "
        "e.g. ABC:0.45.",
        "retrieve_financial_statements x2 (+ mcp_calculate_financial_metrics)",
        "tearsheet_get_fundamentals x2",
        q7,
    ),
    Question(
        8,
        "At the end of each company's fiscal year ending in 2025, which of AAPL and MSFT "
        "had the higher debt-to-equity ratio, defined as total debt divided by "
        "stockholders' equity, and what was it? Answer in the form TICKER:RATIO rounded "
        "to 2 decimals, e.g. ABC:1.23.",
        "retrieve_financial_statements x2 (+ mcp_calculate_financial_metrics)",
        "tearsheet_get_fundamentals x2",
        q8,
    ),
    Question(
        9,
        "For each company's fiscal year ending in 2025, which of AAPL and GOOGL had the "
        "higher free cash flow (operating cash flow minus capital expenditure), and how "
        "much was it in billions of USD? Answer in the form TICKER:BILLIONS rounded to "
        "1 decimal, e.g. ABC:12.3.",
        "retrieve_financial_statements x2 (+ mcp_calculate_financial_metrics)",
        "tearsheet_get_fundamentals x2",
        q9,
    ),
    Question(
        10,
        "What was NVDA's compound annual growth rate of total revenue from its fiscal "
        "year ending in January 2024 to its fiscal year ending in January 2026? Answer "
        "as a percentage rounded to 1 decimal, without the % sign, e.g. 12.3.",
        "retrieve_financial_statements + mcp_calculate_growth_rates",
        "tearsheet_get_financial_statement + tearsheet_calculate_growth_rates",
        q10,
    ),
]


# --------------------------------------------------------------------- main


def write_xml(results: dict[int, Result]) -> Path:
    lines = [
        "<!-- Generated by evals/ground_truth.py. Do not edit answers by hand. -->",
        "<evaluation>",
    ]
    for q in QUESTIONS:
        lines += [
            f"  <!-- Q{q.qid}. Old tools: {q.old_tools}. New tools: {q.new_tools}. -->",
            "  <qa_pair>",
            f"    <question>{escape(q.text)}</question>",
            f"    <answer>{escape(results[q.qid].answer)}</answer>",
            "  </qa_pair>",
        ]
    lines.append("</evaluation>")
    path = REPO_ROOT / "evaluation.xml"
    path.write_text("\n".join(lines) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write-xml", action="store_true")
    args = parser.parse_args()

    results, failed = {}, False
    for q in QUESTIONS:
        try:
            r = q.compute()
        except Exception as e:  # report every question, then fail
            print(f"Q{q.qid}: ERROR {e}")
            failed = True
            continue
        results[q.qid] = r
        print(f"Q{q.qid}: {r.answer}    {r.details}")
        for w in r.warnings:
            print(f"    WARNING: {w}")

    if failed:
        return 1
    if args.write_xml:
        print(f"wrote {write_xml(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

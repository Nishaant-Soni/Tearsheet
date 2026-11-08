from datetime import date

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tearsheet.data import market


@pytest.mark.anyio
async def test_history_normalized_and_end_inclusive(aapl, fake_yahoo):
    df = await market.get_history("AAPL", date(2024, 1, 2), date(2024, 1, 5))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None
    assert str(df.index[-1].date()) == "2024-01-05"  # end date included
    call = fake_yahoo.history_calls[0]
    assert call["end"] == "2024-01-06" and call["auto_adjust"] is True


@pytest.mark.anyio
async def test_history_cached_copy(aapl, fake_yahoo):
    a = await market.get_history("AAPL", date(2024, 1, 2), date(2024, 2, 1))
    a.loc[a.index[0], "close"] = -1.0
    b = await market.get_history("AAPL", date(2024, 1, 2), date(2024, 2, 1))
    assert len(fake_yahoo.history_calls) == 1
    assert b["close"].iloc[0] != -1.0


@pytest.mark.anyio
async def test_unknown_ticker_raises_with_hint_and_suggestions(fake_yahoo):
    fake_yahoo.search_results = [
        {"symbol": "BRK-B", "quoteType": "EQUITY"},
        {"symbol": "BRKB261106P00540000", "quoteType": "OPTION"},
    ]
    with pytest.raises(ToolError) as exc:
        await market.get_history("BRK.B", date(2024, 1, 2), date(2024, 2, 1))
    msg = str(exc.value)
    assert "BRK.B" in msg and "use a dash" in msg
    assert "Did you mean: BRK-B?" in msg
    assert "OPTION" not in msg and "P00540000" not in msg


@pytest.mark.anyio
async def test_known_ticker_empty_range_says_widen(aapl):
    with pytest.raises(ToolError, match="Widen the date range"):
        await market.get_history("AAPL", date(2020, 1, 1), date(2020, 2, 1))


@pytest.mark.anyio
async def test_quote_uses_fast_info_not_info(aapl, fake_yahoo):
    q = await market.get_quote("AAPL")
    assert q.last_price == 120.0 and q.currency == "USD"
    assert q.change == 2.0 and q.change_pct == pytest.approx(0.0169, abs=1e-4)
    assert fake_yahoo.info_calls == []


@pytest.mark.anyio
async def test_quote_unknown_ticker(fake_yahoo):
    with pytest.raises(ToolError, match="No data found for ticker 'ZZZZ'"):
        await market.get_quote("ZZZZ")


@pytest.mark.anyio
async def test_dividends_are_dated_records(aapl):
    events = await market.get_dividends("AAPL")
    assert [e.model_dump() for e in events] == [
        {"date": "2023-11-10", "value": 0.24},
        {"date": "2024-02-09", "value": 0.24},
    ]
    since = await market.get_dividends("AAPL", date(2024, 1, 1))
    assert [e.date for e in since] == ["2024-02-09"]


@pytest.mark.anyio
async def test_splits_and_non_payer(aapl, fake_yahoo):
    splits = await market.get_splits("AAPL")
    assert [(s.date, s.value) for s in splits] == [
        ("2014-06-09", 7.0),
        ("2020-08-31", 4.0),
    ]
    fake_yahoo.add("TSLA", fast_info={"lastPrice": 250.0})
    assert await market.get_dividends("TSLA") == []


@pytest.mark.anyio
async def test_dividends_unknown_ticker(fake_yahoo):
    with pytest.raises(ToolError, match="No data found"):
        await market.get_dividends("ZZZZ")


@pytest.mark.anyio
async def test_company_info_unknown_ticker(fake_yahoo):
    with pytest.raises(ToolError, match="No data found"):
        await market.get_company_info("ZZZZ")

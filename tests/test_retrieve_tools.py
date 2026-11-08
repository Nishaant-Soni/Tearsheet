"""Retrieval tools end to end through the in-memory MCP client, on fake data."""

import numpy as np
import pytest
from mcp import Client

import main
from tests.conftest import make_ohlcv

RETRIEVE_TOOLS = [
    "tearsheet_get_quote",
    "tearsheet_get_price_history",
    "tearsheet_get_company_info",
    "tearsheet_get_dividends",
    "tearsheet_get_splits",
]


async def call(name: str, args: dict):
    async with Client(main.mcp) as client:
        return await client.call_tool(name, args)


@pytest.mark.anyio
async def test_schemas_annotations_and_enums():
    async with Client(main.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in RETRIEVE_TOOLS:
        tool = tools[name]
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is True
        assert tool.output_schema is not None
    props = tools["tearsheet_get_price_history"].input_schema["properties"]
    assert "enum" in props["interval"]
    assert props["response_format"]["enum"] == ["summary", "rows"]


@pytest.mark.anyio
async def test_price_history_summary_default(aapl):
    r = await call(
        "tearsheet_get_price_history",
        {"tickers": ["aapl"], "start_date": "2024-01-02", "end_date": "2024-03-01"},
    )
    assert not r.is_error
    res = r.structured_content["results"][0]
    assert res["ticker"] == "AAPL"
    assert res["rows"] is None and res["summary"]["rows"] == res["total_rows"]
    assert res["summary"]["first_date"] == "2024-01-02"


@pytest.mark.anyio
async def test_price_history_rows_truncated(fake_yahoo):
    fake_yahoo.add("SPY", history=make_ohlcv(np.linspace(400, 500, 300)))
    r = await call(
        "tearsheet_get_price_history",
        {
            "tickers": ["SPY"],
            "start_date": "2024-01-01",
            "end_date": "2025-12-31",
            "response_format": "rows",
            "max_rows": 20,
        },
    )
    res = r.structured_content["results"][0]
    assert len(res["rows"]) == 20
    assert res["truncated"] is True and res["total_rows"] == 300
    assert set(res["rows"][0]) == {"date", "open", "high", "low", "close", "volume"}


@pytest.mark.anyio
async def test_price_history_bad_ticker_is_error(aapl):
    r = await call(
        "tearsheet_get_price_history",
        {"tickers": ["AAPL", "ZZZZ"], "start_date": "2024-01-02"},
    )
    assert r.is_error
    assert "ZZZZ" in r.content[0].text


@pytest.mark.anyio
async def test_price_history_rejects_bad_input_before_fetch(fake_yahoo):
    r = await call(
        "tearsheet_get_price_history",
        {"tickers": ["AAPL"], "start_date": "2024-01-01", "interval": "1m"},
    )
    assert r.is_error and "at most 7 days" in r.content[0].text
    r = await call(
        "tearsheet_get_price_history",
        {"tickers": ["AAPL"], "start_date": "2024-01-01", "interval": "2h"},
    )
    assert r.is_error
    assert fake_yahoo.history_calls == []


@pytest.mark.anyio
async def test_dividends_and_splits_structured(aapl):
    r = await call("tearsheet_get_dividends", {"ticker": "AAPL"})
    assert r.structured_content["count"] == 2
    assert r.structured_content["total"] == 0.48
    assert r.structured_content["dividends"][0] == {"date": "2023-11-10", "value": 0.24}
    r = await call("tearsheet_get_splits", {"ticker": "AAPL"})
    assert r.structured_content["splits"][-1] == {"date": "2020-08-31", "value": 4.0}


@pytest.mark.anyio
async def test_quote_and_company_info(aapl):
    r = await call("tearsheet_get_quote", {"ticker": "AAPL"})
    assert r.structured_content["last_price"] == 120.0
    r = await call("tearsheet_get_company_info", {"ticker": "AAPL"})
    assert r.structured_content["name"] == "Apple Inc."
    r = await call("tearsheet_get_company_info", {"ticker": "ZZZZ"})
    assert r.is_error

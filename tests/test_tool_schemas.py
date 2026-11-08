"""MCP conventions across the whole tool surface, via the in-memory client."""

import numpy as np
import pytest
from mcp import Client

import main
from tests.conftest import make_actions, make_ohlcv

ENUM_PARAMS = {"indicator", "chart_type", "interval", "statement", "period", "metric"}
# Small lists of plain values that are not price series.
ALLOWED_ARRAYS = {
    ("tearsheet_get_price_history", "tickers"),
    ("tearsheet_plot_comparison", "tickers"),
    ("tearsheet_get_fundamentals", "metrics"),
    ("tearsheet_calculate_growth_rates", "values"),  # short series by design (spec)
}

START, END = "2024-01-01", "2024-12-31"
ONE_CALL_EACH = {
    "tearsheet_get_quote": {"ticker": "ACME"},
    "tearsheet_get_price_history": {
        "tickers": ["ACME", "BETA"],
        "start_date": START,
        "end_date": END,
    },
    "tearsheet_get_company_info": {"ticker": "ACME"},
    "tearsheet_get_dividends": {"ticker": "ACME"},
    "tearsheet_get_splits": {"ticker": "ACME"},
    "tearsheet_get_financial_statement": {"ticker": "ACME", "statement": "cash_flow"},
    "tearsheet_get_fundamentals": {"ticker": "ACME"},
    "tearsheet_calculate_indicator": {
        "ticker": "ACME",
        "indicator": "macd",
        "start_date": START,
        "end_date": END,
    },
    "tearsheet_calculate_growth_rates": {"values": [100, 110, 121]},
    "tearsheet_backtest_ma_crossover": {
        "ticker": "ACME",
        "start_date": START,
        "end_date": END,
        "short_window": 5,
        "long_window": 20,
    },
    "tearsheet_plot_price_chart": {
        "ticker": "ACME",
        "start_date": START,
        "end_date": END,
    },
    "tearsheet_plot_comparison": {
        "tickers": ["ACME", "BETA"],
        "start_date": START,
        "end_date": END,
    },
    "tearsheet_plot_fundamental": {"ticker": "ACME", "metric": "net_margin"},
    "tearsheet_plot_ma_crossover": {
        "ticker": "ACME",
        "start_date": START,
        "end_date": END,
        "short_window": 5,
        "long_window": 20,
    },
}


async def list_tools():
    async with Client(main.mcp) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


def resolve(schema: dict, prop: dict) -> dict:
    """Follow $ref and unwrap Optional (anyOf with null) to the underlying schema."""
    if "$ref" in prop:
        prop = schema["$defs"][prop["$ref"].split("/")[-1]]
    for option in prop.get("anyOf", []):
        if option.get("type") != "null":
            return resolve(schema, option)
    return prop


@pytest.fixture
def market_data(acme, fake_yahoo):
    t = np.arange(250)
    acme.history = make_ohlcv(100 + 10 * np.sin(t / 8))
    acme.dividends = make_actions([("2024-03-01", 0.5), ("2024-06-01", 0.5)])
    acme.splits = make_actions([("2020-08-31", 4.0)])
    fake_yahoo.add("BETA", history=make_ohlcv(np.linspace(50, 80, 250)))


@pytest.mark.anyio
async def test_server_name_and_instructions():
    async with Client(main.mcp) as client:
        assert client.server_info.name == "tearsheet_mcp"
        assert "fractions" in client.instructions and "ticker" in client.instructions


@pytest.mark.anyio
async def test_names_annotations_and_output_schemas():
    tools = await list_tools()
    assert set(tools) == set(ONE_CALL_EACH), "add new tools to ONE_CALL_EACH"
    for name, tool in tools.items():
        assert name.startswith("tearsheet_")
        a = tool.annotations
        assert a is not None and None not in (
            a.read_only_hint,
            a.destructive_hint,
            a.idempotent_hint,
            a.open_world_hint,
        ), name
        assert a.destructive_hint is False
        assert tool.output_schema is not None, name
        assert len(tool.description.strip().splitlines()) <= 25, name
        assert "Example" in tool.description, name


@pytest.mark.anyio
async def test_enumerated_parameters_are_enums():
    tools = await list_tools()
    seen = set()
    for name, tool in tools.items():
        schema = tool.input_schema
        for param, prop in schema["properties"].items():
            if param in ENUM_PARAMS:
                assert "enum" in resolve(schema, prop), f"{name}.{param} is not an enum"
                seen.add(param)
            if param == "metrics":
                assert "enum" in resolve(schema, resolve(schema, prop)["items"])
    assert seen == ENUM_PARAMS


@pytest.mark.anyio
async def test_every_parameter_has_a_description():
    tools = await list_tools()
    missing = [
        f"{name}.{param}"
        for name, tool in tools.items()
        for param, prop in tool.input_schema["properties"].items()
        if not (
            prop.get("description")
            or resolve(tool.input_schema, prop).get("description")
        )
    ]
    assert missing == []


@pytest.mark.anyio
async def test_no_filenames_or_price_arrays():
    tools = await list_tools()
    for name, tool in tools.items():
        schema = tool.input_schema
        for param, prop in schema["properties"].items():
            assert "file" not in param and "path" not in param, f"{name}.{param}"
            if resolve(schema, prop).get("type") == "array":
                assert (name, param) in ALLOWED_ARRAYS, f"{name}.{param} takes an array"
        if name != "tearsheet_calculate_growth_rates":
            assert not {"prices", "price_data", "series", "dates", "values"} & set(
                schema["properties"]
            )


@pytest.mark.anyio
@pytest.mark.parametrize("name", sorted(ONE_CALL_EACH))
async def test_every_tool_succeeds_on_mock_data(market_data, name):
    async with Client(main.mcp) as client:
        r = await client.call_tool(name, ONE_CALL_EACH[name])
    assert not r.is_error, r.content[0].text
    assert r.structured_content


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name",
    sorted(
        n for n, args in ONE_CALL_EACH.items() if "ticker" in args or "tickers" in args
    ),
)
async def test_bad_ticker_is_error(market_data, name):
    args = dict(ONE_CALL_EACH[name])
    if "ticker" in args:
        args["ticker"] = "ZZZZ"
    else:
        args["tickers"] = ["ACME", "ZZZZ"]
    async with Client(main.mcp) as client:
        r = await client.call_tool(name, args)
    assert r.is_error
    assert "ZZZZ" in r.content[0].text and "Traceback" not in r.content[0].text

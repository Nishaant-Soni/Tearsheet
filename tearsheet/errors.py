"""Helpers that build actionable ToolError messages.

Every tool failure raises ToolError so the client sees `isError: true`. Messages say
what went wrong and what to try next. They never include stack traces or paths.
"""

from collections.abc import Sequence

from mcp.server.mcpserver.exceptions import ToolError

SYMBOL_HINT = "Check the symbol. For share classes use a dash, e.g. BRK-B."


def ticker_not_found(ticker: str, suggestions: Sequence[str] = ()) -> ToolError:
    msg = f"No data found for ticker '{ticker}'. {SYMBOL_HINT}"
    if suggestions:
        msg += f" Did you mean: {', '.join(suggestions)}?"
    return ToolError(msg)


class NoDataError(ToolError):
    """The symbol exists but has no bars in the requested range."""


def no_data_in_range(ticker: str, start: str, end: str, interval: str) -> NoDataError:
    return NoDataError(
        f"'{ticker}' returned no {interval} bars between {start} and {end}. "
        "Widen the date range, or check that the security traded in that period."
    )


def invalid_input(message: str) -> ToolError:
    return ToolError(message)


def upstream_failure(what: str, exc: Exception) -> ToolError:
    if type(exc).__name__ == "YFRateLimitError":
        return ToolError(
            f"Yahoo Finance rate-limited the request for {what}. "
            "Wait a minute and try again."
        )
    return ToolError(
        f"Yahoo Finance request for {what} failed ({type(exc).__name__}). "
        "Try again shortly. If it keeps failing, check the symbol and date range."
    )

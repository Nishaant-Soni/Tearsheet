import yfinance as yf


def get_financial_statements(ticker: str, indicator: str) -> str:
    """
    Fetches the annual income statements, balance sheet, and cash flow for the given ticker.
    """
    stock = yf.Ticker(ticker)
    if indicator == "income_statement":
        statements = stock.financials
        return {"income_statement": statements.to_json()}
    elif indicator == "balance_sheet":
        statements = stock.balance_sheet
        return {"balance_sheet": statements.to_json()}
    elif indicator == "cash_flow":
        statements = stock.cashflow
        return {"cash_flow": statements.to_json()}
    else:
        return {"error": f"Invalid indicator: {indicator}"}

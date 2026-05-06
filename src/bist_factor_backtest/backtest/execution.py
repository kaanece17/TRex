from __future__ import annotations

from datetime import date

import pandas as pd


def calculate_position_return_open_to_open(
    prices: pd.DataFrame,
    symbol: str,
    buy_date: date,
    sell_date: date,
    commission_rate: float,
) -> dict[str, float | str | date] | None:
    symbol_prices = prices[prices["symbol"] == symbol]
    if not symbol_prices.empty and not isinstance(symbol_prices["date"].iloc[0], date):
        symbol_prices = symbol_prices.copy()
        symbol_prices["date"] = pd.to_datetime(symbol_prices["date"]).dt.date
    buy = symbol_prices[symbol_prices["date"] == buy_date]
    sell = symbol_prices[symbol_prices["date"] == sell_date]
    if buy.empty or sell.empty:
        return None
    buy_price = float(buy["open"].iloc[0])
    sell_price = float(sell["open"].iloc[0])
    gross_return = sell_price / buy_price - 1
    return {
        "symbol": symbol,
        "buy_date": buy_date,
        "buy_price": buy_price,
        "sell_date": sell_date,
        "sell_price": sell_price,
        "gross_return": gross_return,
        "net_return": gross_return - (2 * commission_rate),
    }

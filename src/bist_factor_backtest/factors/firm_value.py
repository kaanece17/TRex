from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def attach_market_cap_firm_value(
    candidates: pd.DataFrame,
    prices: pd.DataFrame,
    rebalance_datetime: datetime,
) -> pd.DataFrame:
    data = candidates.copy()
    data = data.drop(columns=["firm_value_price", "firm_value_price_date", "firm_value"], errors="ignore")
    cutoff_date = rebalance_datetime.date()
    price_data = prices
    if not price_data.empty and not isinstance(price_data["date"].iloc[0], date):
        price_data = price_data.copy()
        price_data["date"] = pd.to_datetime(price_data["date"]).dt.date
    price_data = price_data[price_data["date"] < cutoff_date]
    latest_prices = (
        price_data.sort_values(["symbol", "date"])
        .groupby("symbol", as_index=False)
        .tail(1)[["symbol", "close", "date"]]
        .rename(columns={"close": "firm_value_price", "date": "firm_value_price_date"})
    )
    data = data.merge(latest_prices, on="symbol", how="left")
    market_cap = data["firm_value_price"] * data["shares_outstanding"]
    data["market_cap"] = market_cap
    debt = pd.to_numeric(data.get("total_debt"), errors="coerce")
    cash = pd.to_numeric(data.get("cash"), errors="coerce")
    data["firm_value"] = market_cap + debt - cash
    return data


def calculate_market_cap_firm_value(
    data: pd.DataFrame,
    price_column: str = "firm_value_price",
    shares_column: str = "shares_outstanding",
) -> pd.DataFrame:
    result = data.copy()
    market_cap = result[price_column] * result[shares_column]
    debt = pd.to_numeric(result.get("total_debt"), errors="coerce")
    cash = pd.to_numeric(result.get("cash"), errors="coerce")
    result["firm_value"] = market_cap + debt - cash
    return result

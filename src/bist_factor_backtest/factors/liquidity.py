from __future__ import annotations

from datetime import date

import pandas as pd


def attach_avg_turnover_20d(candidates: pd.DataFrame, prices: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    price_data = prices
    if not price_data.empty and not isinstance(price_data["date"].iloc[0], date):
        price_data = price_data.copy()
        price_data["date"] = pd.to_datetime(price_data["date"]).dt.date
    price_data = price_data[price_data["date"] < as_of_date].copy()
    price_data["turnover"] = price_data["close"] * price_data["volume"]
    turnover = (
        price_data.sort_values(["symbol", "date"])
        .groupby("symbol")
        .tail(20)
        .groupby("symbol", as_index=False)["turnover"]
        .mean()
        .rename(columns={"turnover": "avg_turnover_20d"})
    )
    return candidates.merge(turnover, on="symbol", how="left")


def attach_recent_return_20d(candidates: pd.DataFrame, prices: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    price_data = prices
    if not price_data.empty and not isinstance(price_data["date"].iloc[0], date):
        price_data = price_data.copy()
        price_data["date"] = pd.to_datetime(price_data["date"]).dt.date
    price_data = price_data[price_data["date"] < as_of_date].copy()
    close_col = "adjusted_close" if "adjusted_close" in price_data.columns else "close"
    price_data = price_data.sort_values(["symbol", "date"]).copy()
    price_data["recent_return_20d"] = price_data.groupby("symbol")[close_col].pct_change(20)
    latest = (
        price_data.groupby("symbol", as_index=False)
        .tail(1)[["symbol", "recent_return_20d"]]
        .reset_index(drop=True)
    )
    return candidates.merge(latest, on="symbol", how="left")

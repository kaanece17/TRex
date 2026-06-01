from __future__ import annotations

from datetime import date

import pandas as pd


def attach_announcement_age_days(candidates: pd.DataFrame, buy_date: date) -> pd.DataFrame:
    result = candidates.copy()
    announcement_dates = pd.to_datetime(result.get("announcement_date"), errors="coerce")
    result["announcement_age_days"] = (pd.Timestamp(buy_date) - announcement_dates).dt.days
    return result


def attach_announcement_drift_return(
    candidates: pd.DataFrame,
    prices: pd.DataFrame,
    buy_date: date,
    lookback_days: int = 20,
) -> pd.DataFrame:
    result = candidates.copy()
    result["announcement_drift_return"] = pd.NA
    if result.empty or prices.empty:
        return result

    working_prices = prices.copy()
    working_prices["date"] = pd.to_datetime(working_prices["date"]).dt.date

    returns: list[float | None] = []
    for row in result.itertuples(index=False):
        symbol = str(getattr(row, "symbol"))
        announcement_date = pd.to_datetime(getattr(row, "announcement_date", None), errors="coerce")
        if pd.isna(announcement_date):
            returns.append(None)
            continue
        symbol_prices = working_prices[
            (working_prices["symbol"].astype(str) == symbol)
            & (working_prices["date"] > announcement_date.date())
            & (working_prices["date"] < buy_date)
        ].sort_values("date")
        if symbol_prices.empty:
            returns.append(None)
            continue
        window = symbol_prices.head(max(int(lookback_days), 1))
        start_price = pd.to_numeric(window["adjusted_close"], errors="coerce").iloc[0]
        end_price = pd.to_numeric(window["adjusted_close"], errors="coerce").iloc[-1]
        if pd.isna(start_price) or pd.isna(end_price) or start_price == 0:
            returns.append(None)
            continue
        returns.append(float(end_price / start_price) - 1.0)

    result["announcement_drift_return"] = returns
    return result

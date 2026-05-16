from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def get_latest_known_financials(
    financials: pd.DataFrame,
    rebalance_datetime: datetime,
    first_trading_day: date | None = None,
    date_only_fallback: bool = True,
) -> pd.DataFrame:
    data = financials.copy()
    data["announcement_datetime"] = pd.to_datetime(data["announcement_datetime"], errors="coerce")
    if pd.api.types.is_datetime64tz_dtype(data["announcement_datetime"]):
        data["announcement_datetime"] = data["announcement_datetime"].dt.tz_localize(None)
    data["announcement_date"] = pd.to_datetime(data["announcement_date"], errors="coerce").dt.date
    cutoff = pd.Timestamp(rebalance_datetime)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    known_by_datetime = data[data["announcement_datetime"].notna() & (data["announcement_datetime"] <= cutoff)]

    if date_only_fallback and first_trading_day is not None:
        known_by_date = data[
            data["announcement_datetime"].isna()
            & data["announcement_date"].notna()
            & (data["announcement_date"] < first_trading_day)
        ]
        known = pd.concat([known_by_datetime, known_by_date], ignore_index=True)
    else:
        known = known_by_datetime

    if known.empty:
        return known

    return (
        known.sort_values(["symbol", "period_end", "announcement_datetime", "announcement_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

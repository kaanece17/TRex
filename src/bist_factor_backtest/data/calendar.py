from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd


def trading_days_for_month(prices: pd.DataFrame, month: str) -> list[date]:
    if prices.empty:
        return []
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame[frame["date"].map(lambda value: value.strftime("%Y-%m")) == month].copy()
    if frame.empty:
        return []

    breadth = _daily_breadth(frame)
    if breadth.empty:
        return []

    max_breadth = int(breadth.max())
    min_breadth = max(3, int(max_breadth * 0.1))
    valid = breadth[breadth >= min_breadth]
    if valid.empty:
        valid = breadth
    return sorted(valid.index.tolist())


def get_first_trading_day(prices: pd.DataFrame, month: str) -> date:
    return trading_days_for_month(prices, month)[0]


def get_last_trading_day(prices: pd.DataFrame, month: str) -> date:
    return trading_days_for_month(prices, month)[-1]


def get_backtest_months(prices: pd.DataFrame, start_date: date, end_date: date) -> list[str]:
    dates = pd.to_datetime(prices["date"]).dt.date
    filtered = dates[(dates >= start_date) & (dates <= end_date)]
    return sorted(set(pd.Series(filtered).map(lambda value: value.strftime("%Y-%m"))))


def get_market_open_datetime(trading_day: date, market_open_time: str, timezone: str) -> datetime:
    hour, minute = [int(part) for part in market_open_time.split(":")]
    return datetime.combine(trading_day, time(hour, minute), tzinfo=ZoneInfo(timezone))


def _daily_breadth(frame: pd.DataFrame) -> pd.Series:
    if "symbol" not in frame.columns:
        return frame.groupby("date").size()

    if "volume" in frame.columns:
        volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0)
        positive_volume = frame[volume > 0]
        if not positive_volume.empty:
            return positive_volume.groupby("date")["symbol"].nunique()

    return frame.groupby("date")["symbol"].nunique()

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

_TRADING_DAYS_BY_MONTH_CACHE: dict[int, dict[str, list[date]]] = {}


def trading_days_for_month(prices: pd.DataFrame, month: str) -> list[date]:
    return _trading_days_by_month(prices).get(month, [])


def get_first_trading_day(prices: pd.DataFrame, month: str) -> date:
    return trading_days_for_month(prices, month)[0]


def get_last_trading_day(prices: pd.DataFrame, month: str) -> date:
    return trading_days_for_month(prices, month)[-1]


def get_backtest_months(prices: pd.DataFrame, start_date: date, end_date: date) -> list[str]:
    daily_dates = _daily_trading_dates(prices)
    filtered = [value for value in daily_dates if start_date <= value <= end_date]
    return sorted({value.strftime("%Y-%m") for value in filtered})


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


def _daily_trading_dates(prices: pd.DataFrame) -> list[date]:
    return sorted(_daily_breadth(_normalized_price_dates(prices)).index.tolist())


def _trading_days_by_month(prices: pd.DataFrame) -> dict[str, list[date]]:
    cache_key = id(prices)
    cached = _TRADING_DAYS_BY_MONTH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    frame = _normalized_price_dates(prices)
    breadth = _daily_breadth(frame)
    if breadth.empty:
        _TRADING_DAYS_BY_MONTH_CACHE[cache_key] = {}
        return {}

    grouped: dict[str, list[date]] = {}
    for month, series in breadth.groupby(lambda day: day.strftime("%Y-%m")):
        max_breadth = int(series.max())
        min_breadth = max(3, int(max_breadth * 0.1))
        valid = series[series >= min_breadth]
        if valid.empty:
            valid = series
        grouped[month] = sorted(valid.index.tolist())

    _TRADING_DAYS_BY_MONTH_CACHE[cache_key] = grouped
    return grouped


def _normalized_price_dates(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices
    sample = prices["date"]
    first_valid = next((value for value in sample.tolist() if pd.notna(value)), None)
    if not isinstance(first_valid, date) or isinstance(first_valid, datetime):
        frame = prices.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
        return frame
    return prices

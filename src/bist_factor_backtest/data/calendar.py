from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd


def trading_days_for_month(prices: pd.DataFrame, month: str) -> list[date]:
    price_dates = pd.to_datetime(prices["date"]).dt.date
    months = pd.Series(price_dates).map(lambda value: value.strftime("%Y-%m"))
    return sorted(set(pd.Series(price_dates)[months == month]))


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


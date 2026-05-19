from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from bist_factor_backtest.data.price_loader_yfinance import normalize_yahoo_symbol, to_yahoo_symbol


class YFinanceOpenPriceCaptureLoader:
    def load(
        self,
        symbols: list[str],
        trade_date: date,
        *,
        market_open_time: str = "10:00",
        timezone: str = "Europe/Istanbul",
        interval: str = "1m",
        yahoo_suffix: str | None = ".IS",
    ) -> pd.DataFrame:
        frames: list[dict[str, object]] = []
        yahoo_symbols = [to_yahoo_symbol(symbol, yahoo_suffix) for symbol in symbols]
        start = trade_date
        end = trade_date + timedelta(days=1)
        for chunk in _chunked(yahoo_symbols, 30):
            data = yf.download(
                chunk,
                start=start,
                end=end,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=True,
                prepost=False,
                group_by="ticker",
            )
            for yahoo_symbol in chunk:
                symbol = normalize_yahoo_symbol(yahoo_symbol, yahoo_suffix)
                symbol_data = _extract_symbol_frame(data, yahoo_symbol)
                row = _build_capture_row(
                    symbol_data=symbol_data,
                    symbol=symbol,
                    trade_date=trade_date,
                    market_open_time=market_open_time,
                    timezone=timezone,
                    interval=interval,
                )
                frames.append(row)
        return pd.DataFrame(frames)


def _build_capture_row(
    *,
    symbol_data: pd.DataFrame,
    symbol: str,
    trade_date: date,
    market_open_time: str,
    timezone: str,
    interval: str,
) -> dict[str, object]:
    if symbol_data.empty:
        return _empty_capture_row(
            symbol=symbol,
            trade_date=trade_date,
            market_open_time=market_open_time,
            interval=interval,
            message="no_intraday_data",
        )
    prepared = symbol_data.reset_index().copy()
    datetime_column = next(
        (column for column in prepared.columns if str(column).lower() in {"datetime", "date"}),
        None,
    )
    if datetime_column is None or "Open" not in prepared.columns:
        return _empty_capture_row(
            symbol=symbol,
            trade_date=trade_date,
            market_open_time=market_open_time,
            interval=interval,
            message="missing_datetime_or_open",
        )
    selected = _select_first_regular_session_bar(
        prepared[[datetime_column, "Open"]].rename(columns={datetime_column: "bar_timestamp", "Open": "open"}),
        trade_date=trade_date,
        market_open_time=market_open_time,
        timezone=timezone,
    )
    if selected is None:
        return _empty_capture_row(
            symbol=symbol,
            trade_date=trade_date,
            market_open_time=market_open_time,
            interval=interval,
            message="no_bar_after_market_open",
        )
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "bar_timestamp": selected["bar_timestamp"],
        "market_open_time": market_open_time,
        "open_price": float(selected["open"]),
        "source": "yfinance_intraday",
        "interval": interval,
        "source_status": "captured",
        "source_message": None,
        "captured_at": datetime.now(UTC),
    }


def _select_first_regular_session_bar(
    frame: pd.DataFrame,
    *,
    trade_date: date,
    market_open_time: str,
    timezone: str,
) -> dict[str, object] | None:
    if frame.empty:
        return None
    timestamps = pd.to_datetime(frame["bar_timestamp"], errors="coerce")
    if timestamps.isna().all():
        return None
    tz = ZoneInfo(timezone)
    if getattr(timestamps.dt, "tz", None) is None:
        localized = timestamps.dt.tz_localize(tz)
    else:
        localized = timestamps.dt.tz_convert(tz)
    normalized = frame.copy()
    normalized["bar_timestamp"] = localized
    normalized = normalized.dropna(subset=["bar_timestamp", "open"])
    open_hour, open_minute = [int(part) for part in market_open_time.split(":")]
    session_start = datetime.combine(trade_date, time(open_hour, open_minute), tzinfo=tz)
    matching = normalized[
        (normalized["bar_timestamp"].dt.date == trade_date) & (normalized["bar_timestamp"] >= session_start)
    ].sort_values("bar_timestamp")
    if matching.empty:
        return None
    row = matching.iloc[0]
    return {
        "bar_timestamp": row["bar_timestamp"].isoformat(),
        "open": row["open"],
    }


def _empty_capture_row(
    *,
    symbol: str,
    trade_date: date,
    market_open_time: str,
    interval: str,
    message: str,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "bar_timestamp": None,
        "market_open_time": market_open_time,
        "open_price": None,
        "source": "yfinance_intraday",
        "interval": interval,
        "source_status": "missing",
        "source_message": message,
        "captured_at": datetime.now(UTC),
    }


def _chunked(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _extract_symbol_frame(data: pd.DataFrame, yahoo_symbol: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        if yahoo_symbol in data.columns.get_level_values(0):
            return data[yahoo_symbol]
        if yahoo_symbol in data.columns.get_level_values(-1):
            return data.xs(yahoo_symbol, axis=1, level=-1)
    return data

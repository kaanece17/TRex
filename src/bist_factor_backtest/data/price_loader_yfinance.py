from __future__ import annotations

from datetime import date

import pandas as pd
import yfinance as yf


def to_yahoo_symbol(symbol: str, suffix: str | None = ".IS") -> str:
    normalized = symbol.upper()
    return f"{normalized}{suffix}" if suffix else normalized


def normalize_yahoo_symbol(yahoo_symbol: str, suffix: str | None = ".IS") -> str:
    if suffix:
        return yahoo_symbol.replace(suffix, "").upper()
    return yahoo_symbol.upper()


class YFinancePriceLoader:
    def load(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        *,
        yahoo_suffix: str | None = ".IS",
    ) -> pd.DataFrame:
        frames = []
        yahoo_symbols = [to_yahoo_symbol(symbol, yahoo_suffix) for symbol in symbols]
        for chunk in _chunked(yahoo_symbols, 30):
            data = yf.download(
                chunk,
                start=start_date,
                end=end_date,
                auto_adjust=False,
                progress=False,
                threads=True,
                group_by="ticker",
            )
            if data.empty:
                continue
            for yahoo_symbol in chunk:
                symbol_data = _extract_symbol_frame(data, yahoo_symbol)
                if symbol_data.empty:
                    continue
                symbol_data = symbol_data.reset_index()
                symbol_data.columns = [_normalize_column_name(column) for column in symbol_data.columns]
                symbol_data["symbol"] = normalize_yahoo_symbol(yahoo_symbol, yahoo_suffix)
                symbol_data = symbol_data.rename(columns={"adj_close": "adjusted_close"})
                required_columns = ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"]
                if not set(required_columns).issubset(symbol_data.columns):
                    continue
                symbol_data = symbol_data.dropna(subset=["open", "close"], how="any")
                frames.append(symbol_data[required_columns])
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_column_name(column) -> str:
    if isinstance(column, tuple):
        return str(column[0]).lower().replace(" ", "_")
    return str(column).lower().replace(" ", "_")


def _chunked(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _extract_symbol_frame(data: pd.DataFrame, yahoo_symbol: str) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        if yahoo_symbol in data.columns.get_level_values(0):
            return data[yahoo_symbol]
        if yahoo_symbol in data.columns.get_level_values(-1):
            return data.xs(yahoo_symbol, axis=1, level=-1)
    return data

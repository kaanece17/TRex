from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def load_symbol_aliases(path: str | Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    if data.empty:
        return pd.DataFrame(columns=["canonical_symbol", "symbol", "valid_from", "valid_to"])
    data["canonical_symbol"] = data["canonical_symbol"].astype(str).str.upper()
    data["symbol"] = data["symbol"].astype(str).str.upper()
    data["valid_from"] = pd.to_datetime(data["valid_from"], errors="coerce").dt.date
    data["valid_to"] = pd.to_datetime(data["valid_to"], errors="coerce").map(
        lambda value: None if pd.isna(value) else value.date()
    )
    return data


def canonical_symbol_map(aliases: pd.DataFrame) -> dict[str, str]:
    if aliases.empty:
        return {}
    return {
        symbol: canonical
        for symbol, canonical in aliases[["symbol", "canonical_symbol"]].drop_duplicates().itertuples(index=False)
    }


def apply_symbol_aliases(data: pd.DataFrame, aliases: pd.DataFrame, column: str = "symbol") -> pd.DataFrame:
    if aliases.empty or data.empty or column not in data.columns:
        return data.copy()
    result = data.copy()
    mapping = canonical_symbol_map(aliases)
    normalized = result[column].astype(str).str.upper()
    result[column] = normalized.map(lambda value: mapping.get(value, value))
    return result


def canonicalize_symbol_list(symbols: list[str], aliases: pd.DataFrame) -> list[str]:
    if aliases.empty:
        return [symbol.upper() for symbol in symbols]
    mapping = canonical_symbol_map(aliases)
    canonical = [mapping.get(symbol.upper(), symbol.upper()) for symbol in symbols]
    return list(dict.fromkeys(canonical))


def canonical_symbol_as_of(symbol: str, aliases: pd.DataFrame, as_of_date: date | None = None) -> str:
    normalized = str(symbol).upper()
    if aliases.empty:
        return normalized
    matches = aliases[aliases["symbol"] == normalized]
    if matches.empty:
        return normalized
    if as_of_date is None:
        return str(matches["canonical_symbol"].iloc[0]).upper()
    dated = matches[
        (matches["valid_from"].isna() | (matches["valid_from"] <= as_of_date))
        & (matches["valid_to"].isna() | (matches["valid_to"] >= as_of_date))
    ]
    if dated.empty:
        return str(matches["canonical_symbol"].iloc[0]).upper()
    return str(dated["canonical_symbol"].iloc[0]).upper()

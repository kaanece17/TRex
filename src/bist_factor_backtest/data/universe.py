from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from bist_factor_backtest.data.symbol_aliases import (
    apply_symbol_aliases,
    canonicalize_symbol_list,
    load_symbol_aliases,
)


def load_static_universe(path: str | Path, symbol_aliases_file: str | Path | None = None) -> list[str]:
    data = pd.read_csv(path)
    symbols = data["symbol"].astype(str).str.upper().tolist()
    if symbol_aliases_file is None or not Path(symbol_aliases_file).exists():
        return symbols
    aliases = load_symbol_aliases(symbol_aliases_file)
    return canonicalize_symbol_list(symbols, aliases)


def load_universe_membership(path: str | Path, symbol_aliases_file: str | Path | None = None) -> pd.DataFrame:
    data = pd.read_csv(path)
    data["start_date"] = pd.to_datetime(data["start_date"]).dt.date
    data["end_date"] = _to_date_or_none(data["end_date"])
    data["symbol"] = data["symbol"].astype(str).str.upper()
    for column, default in {"source_type": "unknown", "source_url": None, "confidence": "low"}.items():
        if column not in data.columns:
            data[column] = default
    if symbol_aliases_file is not None and Path(symbol_aliases_file).exists():
        aliases = load_symbol_aliases(symbol_aliases_file)
        data = apply_symbol_aliases(data, aliases)
    return data


def get_universe_for_date(
    membership: pd.DataFrame,
    universe_name: str,
    as_of_date: date,
) -> list[str]:
    data = membership[membership["universe_name"] == universe_name].copy()
    if data.empty:
        return []
    data["start_date"] = pd.to_datetime(data["start_date"]).dt.date
    data["end_date"] = _to_date_or_none(data["end_date"])
    active = data[
        (data["start_date"] <= as_of_date)
        & (data["end_date"].isna() | (data["end_date"] >= as_of_date))
    ]
    return list(dict.fromkeys(active["symbol"].tolist()))


def parse_cnbce_bist_codes(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    symbols = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/borsa/hisseler/" not in href:
            continue
        symbol = _symbol_from_hisse_url(href)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def fetch_current_static_xusin_membership(
    url: str = "https://www.cnbce.com/borsa/hisseler/bist-sinai-hisseleri",
    start_date: date = date(1900, 1, 1),
) -> pd.DataFrame:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    symbols = parse_cnbce_bist_codes(response.text)
    return build_current_static_membership(symbols, start_date, url)


def build_current_static_membership(symbols: list[str], start_date: date, source_url: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol.upper(),
                "universe_name": "BIST_SANAYI",
                "start_date": start_date,
                "end_date": None,
                "source_type": "current_static",
                "source_url": source_url,
                "confidence": "medium",
            }
            for symbol in symbols
        ]
    )


def reconstruct_membership_from_current(
    current_symbols: list[str],
    changes: pd.DataFrame,
    today: date,
    start_date: date,
    universe_name: str = "BIST_SANAYI",
) -> pd.DataFrame:
    active = {
        symbol.upper(): {
            "end_date": None,
            "source_type": "manual_seed",
            "source_url": None,
            "confidence": "medium",
        }
        for symbol in current_symbols
    }
    intervals = []
    if changes.empty:
        return pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "universe_name": universe_name,
                    "start_date": start_date,
                    "end_date": item["end_date"],
                    "source_type": item["source_type"],
                    "source_url": item["source_url"],
                    "confidence": item["confidence"],
                }
                for symbol, item in active.items()
            ]
        )

    data = changes.copy()
    data["effective_date"] = pd.to_datetime(data["effective_date"]).dt.date
    for change in data.sort_values("effective_date", ascending=False).to_dict("records"):
        symbol = str(change["symbol"]).upper()
        action = change["action"]
        effective_date = change["effective_date"]
        previous_day = (pd.Timestamp(effective_date) - pd.Timedelta(days=1)).date()
        source_type = change.get("source_type", "kap_announcement")
        source_url = change.get("source_url")
        confidence = change.get("confidence", "medium")
        if action == "add" and symbol in active:
            intervals.append(
                {
                    "symbol": symbol,
                    "universe_name": universe_name,
                    "start_date": effective_date,
                    "end_date": active[symbol]["end_date"],
                    "source_type": source_type,
                    "source_url": source_url,
                    "confidence": confidence,
                }
            )
            del active[symbol]
        if action == "remove" and symbol not in active:
            active[symbol] = {
                "end_date": previous_day,
                "source_type": source_type,
                "source_url": source_url,
                "confidence": confidence,
            }
    intervals.extend(
        [
            {
                "symbol": symbol,
                "universe_name": universe_name,
                "start_date": start_date,
                "end_date": item["end_date"],
                "source_type": item["source_type"],
                "source_url": item["source_url"],
                "confidence": item["confidence"],
            }
            for symbol, item in active.items()
        ]
    )
    return pd.DataFrame(intervals)


def build_universe_monthly_snapshot(
    membership: pd.DataFrame,
    rebalance_dates: pd.DataFrame,
    universe_name: str,
) -> pd.DataFrame:
    rows = []
    for item in rebalance_dates.to_dict("records"):
        rebalance_date = pd.to_datetime(item["rebalance_date"]).date()
        symbols = get_universe_for_date(membership, universe_name, rebalance_date)
        source_quality = _source_quality_for_date(membership, universe_name, rebalance_date)
        for symbol in symbols:
            rows.append(
                {
                    "month": item["month"],
                    "rebalance_date": rebalance_date,
                    "universe_name": universe_name,
                    "symbol": symbol,
                    "source_quality": source_quality,
                }
            )
    return pd.DataFrame(rows)


def _to_date_or_none(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").map(lambda value: None if pd.isna(value) else value.date())


def _symbol_from_hisse_url(href: str) -> str | None:
    slug = urljoin("https://www.cnbce.com", href).rstrip("/").split("/")[-1]
    if "-" not in slug:
        return None
    symbol = slug.split("-", 1)[0].upper()
    return symbol if symbol.isalnum() else None


def _source_quality_for_date(membership: pd.DataFrame, universe_name: str, as_of_date: date) -> str:
    data = membership[membership["universe_name"] == universe_name].copy()
    data["start_date"] = pd.to_datetime(data["start_date"]).dt.date
    data["end_date"] = _to_date_or_none(data["end_date"])
    active = data[
        (data["start_date"] <= as_of_date)
        & (data["end_date"].isna() | (data["end_date"] >= as_of_date))
    ]
    confidence = set(active.get("confidence", pd.Series(dtype=str)).dropna().tolist())
    if "low" in confidence:
        return "low"
    if "medium" in confidence:
        return "medium"
    return "high"

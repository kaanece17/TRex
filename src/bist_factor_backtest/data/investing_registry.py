from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.data.symbol_aliases import canonical_symbol_as_of, load_symbol_aliases


REQUIRED_COLUMNS = ["symbol"]
OPTIONAL_COLUMNS = ["investing_slug", "earnings_url", "is_active", "notes"]


def load_investing_registry(
    path: str | Path,
    symbol_aliases_file: str | Path | None = None,
) -> pd.DataFrame:
    data = pd.read_csv(path)
    for column in REQUIRED_COLUMNS:
        if column not in data.columns:
            raise ValueError(f"missing required column: {column}")
    for column in OPTIONAL_COLUMNS:
        if column not in data.columns:
            data[column] = None
    result = data.copy()
    result["symbol"] = result["symbol"].astype(str).str.upper()
    result["investing_slug"] = result["investing_slug"].map(_normalize_optional_text)
    result["earnings_url"] = result["earnings_url"].map(_normalize_optional_text)
    result["is_active"] = result["is_active"].map(_coerce_bool_or_none)
    result["notes"] = result["notes"].map(_normalize_optional_text)
    if symbol_aliases_file is not None and Path(symbol_aliases_file).exists():
        aliases = load_symbol_aliases(symbol_aliases_file)
        result["symbol"] = result["symbol"].map(lambda symbol: canonical_symbol_as_of(symbol, aliases))
        result = _collapse_canonical_duplicates(result)
    return result


def validate_investing_registry(registry: pd.DataFrame) -> list[str]:
    if registry.empty:
        return []
    issues: list[str] = []
    for _, row in registry.iterrows():
        symbol = str(row["symbol"]).upper()
        has_slug = _normalize_optional_text(row.get("investing_slug")) is not None
        has_url = _normalize_optional_text(row.get("earnings_url")) is not None
        if not has_slug and not has_url:
            issues.append(f"{symbol}: missing investing_slug_or_earnings_url")
    duplicates = registry[registry["symbol"].duplicated(keep=False)]["symbol"].astype(str).tolist()
    for symbol in sorted(set(duplicates)):
        issues.append(f"{symbol}: duplicate_symbol")
    duplicate_slugs = (
        registry[registry["investing_slug"].notna()]["investing_slug"]
        .duplicated(keep=False)
    )
    if duplicate_slugs.any():
        slugs = registry[registry["investing_slug"].notna()]["investing_slug"]
        for slug in sorted(set(slugs[duplicate_slugs].astype(str).tolist())):
            issues.append(f"{slug}: duplicate_investing_slug")
    return issues


def build_registry_urls(registry: pd.DataFrame) -> pd.DataFrame:
    result = registry.copy()
    result["earnings_url"] = result.apply(
        lambda row: _coalesce_url_or_slug(row["earnings_url"], row["investing_slug"]),
        axis=1,
    )
    return result


def bootstrap_investing_registry(
    symbols: list[str],
    existing_registry: pd.DataFrame | None = None,
) -> pd.DataFrame:
    base = pd.DataFrame({"symbol": [str(symbol).upper() for symbol in symbols]})
    base = base.drop_duplicates().sort_values("symbol").reset_index(drop=True)
    for column in OPTIONAL_COLUMNS:
        base[column] = None
    if existing_registry is None or existing_registry.empty:
        return base
    existing = existing_registry.copy()
    existing["symbol"] = existing["symbol"].astype(str).str.upper()
    for column in OPTIONAL_COLUMNS:
        if column not in existing.columns:
            existing[column] = None
    existing = existing[["symbol", *OPTIONAL_COLUMNS]].drop_duplicates(subset=["symbol"], keep="first")
    merged = base.merge(existing, on="symbol", how="left", suffixes=("_base", ""))
    for column in OPTIONAL_COLUMNS:
        base_column = f"{column}_base"
        if base_column in merged.columns:
            merged = merged.drop(columns=[base_column])
    return merged[["symbol", *OPTIONAL_COLUMNS]]


def _url_from_slug(slug: str | None) -> str | None:
    if slug is None:
        return None
    return f"https://tr.investing.com/equities/{slug}-earnings"


def _coalesce_url_or_slug(earnings_url, slug):
    normalized_url = _normalize_optional_text(earnings_url)
    return normalized_url if normalized_url is not None else _url_from_slug(_normalize_optional_text(slug))


def _normalize_optional_text(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _coerce_bool_or_none(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "evet"}


def _collapse_canonical_duplicates(registry: pd.DataFrame) -> pd.DataFrame:
    if registry.empty or not registry["symbol"].duplicated().any():
        return registry.reset_index(drop=True)

    collapsed_rows: list[dict] = []
    for symbol, group in registry.groupby("symbol", sort=False, dropna=False):
        merged = {"symbol": symbol}
        merged["investing_slug"] = _first_present(group["investing_slug"].tolist())
        merged["earnings_url"] = _first_present(group["earnings_url"].tolist())
        merged["is_active"] = _first_present(group["is_active"].tolist())
        merged["notes"] = _merge_notes(group["notes"].tolist())
        collapsed_rows.append(merged)
    return pd.DataFrame(collapsed_rows, columns=["symbol", *OPTIONAL_COLUMNS])


def _first_present(values: list):
    for value in values:
        if value is None or pd.isna(value):
            continue
        return value
    return None


def _merge_notes(values: list) -> str | None:
    seen: list[str] = []
    for value in values:
        normalized = _normalize_optional_text(value)
        if normalized is None or normalized in seen:
            continue
        seen.append(normalized)
    if not seen:
        return None
    return " | ".join(seen)

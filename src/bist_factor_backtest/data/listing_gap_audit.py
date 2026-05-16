from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def load_listing_dates(path: str | Path) -> pd.DataFrame:
    listing_path = Path(path)
    if not listing_path.exists():
        return pd.DataFrame(columns=["symbol", "listing_date", "source", "notes"])
    result = pd.read_csv(listing_path)
    if result.empty:
        return pd.DataFrame(columns=["symbol", "listing_date", "source", "notes"])
    if "symbol" not in result.columns:
        raise ValueError("listing dates file must include a symbol column")
    if "listing_date" not in result.columns:
        raise ValueError("listing dates file must include a listing_date column")
    for column in ["source", "notes"]:
        if column not in result.columns:
            result[column] = None
    result["symbol"] = result["symbol"].astype(str).str.upper()
    result["listing_date"] = pd.to_datetime(result["listing_date"], errors="coerce").dt.date
    return result


def build_listing_gap_audit(
    snapshots: pd.DataFrame,
    listing_dates: pd.DataFrame,
    audit_start_date: date,
) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "listing_date",
                "listing_source",
                "listing_notes",
                "first_statement_period",
                "first_announcement_period",
                "missing_periods_2019_plus",
                "pre_listing_expected_gap_count",
                "post_listing_fetch_gap_count",
                "unknown_gap_count",
                "first_missing_period",
                "last_missing_period",
                "listing_gap_class",
            ]
        )
    normalized = snapshots.copy()
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper()
    normalized["period_end"] = pd.to_datetime(normalized["period_end"], errors="coerce").dt.date
    normalized["announcement_date"] = pd.to_datetime(normalized["announcement_date"], errors="coerce").dt.date
    normalized = (
        normalized.sort_values(["symbol", "period_end", "announcement_date"], na_position="last")
        .groupby(["symbol", "period_end"], as_index=False)
        .agg({"announcement_date": "first"})
    )

    listings = listing_dates.copy() if not listing_dates.empty else pd.DataFrame(columns=["symbol", "listing_date", "source", "notes"])
    if not listings.empty:
        listings["symbol"] = listings["symbol"].astype(str).str.upper()

    rows: list[dict] = []
    for symbol, group in normalized.groupby("symbol"):
        group = group.sort_values("period_end").copy()
        missing = group[(group["period_end"] >= audit_start_date) & (group["announcement_date"].isna())].copy()
        if missing.empty:
            continue

        listing_row = listings[listings["symbol"] == symbol].head(1)
        listing_date = None if listing_row.empty else listing_row.iloc[0].get("listing_date")
        listing_source = None if listing_row.empty else listing_row.iloc[0].get("source")
        listing_notes = None if listing_row.empty else listing_row.iloc[0].get("notes")
        listing_period = _listing_period_marker(listing_date) if listing_date is not None else None

        first_statement_period = _min_date(group["period_end"])
        first_announcement_period = _min_date(group.loc[group["announcement_date"].notna(), "period_end"])

        if listing_period is not None:
            pre_listing_expected_gap_count = int((missing["period_end"] < listing_period).sum())
            post_listing_fetch_gap_count = int((missing["period_end"] >= listing_period).sum())
            unknown_gap_count = 0
        elif first_announcement_period is not None and first_announcement_period < audit_start_date:
            pre_listing_expected_gap_count = 0
            post_listing_fetch_gap_count = len(missing)
            unknown_gap_count = 0
        else:
            pre_listing_expected_gap_count = 0
            post_listing_fetch_gap_count = 0
            unknown_gap_count = len(missing)

        rows.append(
            {
                "symbol": symbol,
                "listing_date": listing_date,
                "listing_source": listing_source,
                "listing_notes": listing_notes,
                "first_statement_period": first_statement_period,
                "first_announcement_period": first_announcement_period,
                "missing_periods_2019_plus": len(missing),
                "pre_listing_expected_gap_count": pre_listing_expected_gap_count,
                "post_listing_fetch_gap_count": post_listing_fetch_gap_count,
                "unknown_gap_count": unknown_gap_count,
                "first_missing_period": _min_date(missing["period_end"]),
                "last_missing_period": _max_date(missing["period_end"]),
                "listing_gap_class": _listing_gap_class(
                    pre_listing_expected_gap_count=pre_listing_expected_gap_count,
                    post_listing_fetch_gap_count=post_listing_fetch_gap_count,
                    unknown_gap_count=unknown_gap_count,
                ),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "listing_date",
                "listing_source",
                "listing_notes",
                "first_statement_period",
                "first_announcement_period",
                "missing_periods_2019_plus",
                "pre_listing_expected_gap_count",
                "post_listing_fetch_gap_count",
                "unknown_gap_count",
                "first_missing_period",
                "last_missing_period",
                "listing_gap_class",
            ]
        )

    return pd.DataFrame(rows).sort_values(
        ["post_listing_fetch_gap_count", "unknown_gap_count", "pre_listing_expected_gap_count", "symbol"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)


def _listing_period_marker(listing_date: date | None) -> date | None:
    if listing_date is None:
        return None
    quarter_end_month = ((listing_date.month - 1) // 3 + 1) * 3
    return date(listing_date.year, quarter_end_month, 1)


def _listing_gap_class(
    pre_listing_expected_gap_count: int,
    post_listing_fetch_gap_count: int,
    unknown_gap_count: int,
) -> str:
    if unknown_gap_count > 0:
        return "listing_date_unknown"
    if pre_listing_expected_gap_count > 0 and post_listing_fetch_gap_count > 0:
        return "mixed_pre_listing_and_post_listing_gap"
    if post_listing_fetch_gap_count > 0:
        return "post_listing_fetch_gap_only"
    return "pre_listing_expected_only"


def _min_date(values: pd.Series) -> date | None:
    if values.empty:
        return None
    cleaned = pd.to_datetime(values, errors="coerce").dropna()
    if cleaned.empty:
        return None
    return cleaned.min().date()


def _max_date(values: pd.Series) -> date | None:
    if values.empty:
        return None
    cleaned = pd.to_datetime(values, errors="coerce").dropna()
    if cleaned.empty:
        return None
    return cleaned.max().date()

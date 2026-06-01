from __future__ import annotations

from datetime import date

import pandas as pd


def attach_latest_analyst_snapshot(
    candidates: pd.DataFrame,
    analyst_snapshots: pd.DataFrame,
    buy_date: date,
    period: str = "0q",
) -> pd.DataFrame:
    result = candidates.copy()
    if result.empty or analyst_snapshots.empty:
        result["analyst_revision_balance"] = pd.NA
        result["recommendation_score"] = pd.NA
        return result

    snapshots = analyst_snapshots.copy()
    snapshots["symbol"] = snapshots["symbol"].astype(str).str.upper()
    snapshots["as_of_date"] = pd.to_datetime(snapshots["as_of_date"], errors="coerce").dt.date
    snapshots = snapshots[
        (snapshots["period"].astype(str) == period)
        & snapshots["as_of_date"].notna()
        & (snapshots["as_of_date"] < buy_date)
    ].copy()
    if snapshots.empty:
        return result
    snapshots = snapshots.sort_values(["symbol", "as_of_date"]).drop_duplicates(["symbol"], keep="last")
    snapshots["analyst_revision_balance"] = (
        pd.to_numeric(snapshots["up_last7days"], errors="coerce").fillna(0.0)
        + pd.to_numeric(snapshots["up_last30days"], errors="coerce").fillna(0.0)
        - pd.to_numeric(snapshots["down_last7days"], errors="coerce").fillna(0.0)
        - pd.to_numeric(snapshots["down_last30days"], errors="coerce").fillna(0.0)
    )
    total = (
        pd.to_numeric(snapshots["strong_buy"], errors="coerce").fillna(0.0)
        + pd.to_numeric(snapshots["buy"], errors="coerce").fillna(0.0)
        + pd.to_numeric(snapshots["hold"], errors="coerce").fillna(0.0)
        + pd.to_numeric(snapshots["sell"], errors="coerce").fillna(0.0)
        + pd.to_numeric(snapshots["strong_sell"], errors="coerce").fillna(0.0)
    )
    total = total.where(total != 0)
    snapshots["recommendation_score"] = (
        pd.to_numeric(snapshots["strong_buy"], errors="coerce").fillna(0.0)
        + pd.to_numeric(snapshots["buy"], errors="coerce").fillna(0.0)
        - pd.to_numeric(snapshots["sell"], errors="coerce").fillna(0.0)
        - pd.to_numeric(snapshots["strong_sell"], errors="coerce").fillna(0.0)
    ) / total
    merged = result.merge(
        snapshots[["symbol", "analyst_revision_balance", "recommendation_score"]],
        on="symbol",
        how="left",
    )
    if "analyst_revision_balance" not in merged.columns:
        merged["analyst_revision_balance"] = pd.NA
    if "recommendation_score" not in merged.columns:
        merged["recommendation_score"] = pd.NA
    return merged

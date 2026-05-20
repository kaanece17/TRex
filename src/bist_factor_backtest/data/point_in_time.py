from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def get_latest_known_financials(
    financials: pd.DataFrame,
    rebalance_datetime: datetime,
    first_trading_day: date | None = None,
    date_only_fallback: bool = True,
) -> pd.DataFrame:
    data = financials.copy()
    data["announcement_datetime"] = pd.to_datetime(data["announcement_datetime"], errors="coerce")
    if pd.api.types.is_datetime64tz_dtype(data["announcement_datetime"]):
        data["announcement_datetime"] = data["announcement_datetime"].dt.tz_localize(None)
    data["announcement_date"] = pd.to_datetime(data["announcement_date"], errors="coerce").dt.date
    cutoff = pd.Timestamp(rebalance_datetime)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    known_by_datetime = data[data["announcement_datetime"].notna() & (data["announcement_datetime"] <= cutoff)]

    if date_only_fallback and first_trading_day is not None:
        known_by_date = data[
            data["announcement_datetime"].isna()
            & data["announcement_date"].notna()
            & (data["announcement_date"] < first_trading_day)
        ]
        known = pd.concat([known_by_datetime, known_by_date], ignore_index=True)
    else:
        known = known_by_datetime

    if known.empty:
        return known

    return (
        known.sort_values(["symbol", "period_end", "announcement_datetime", "announcement_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def get_latest_known_annual_financials(
    financials: pd.DataFrame,
    rebalance_datetime: datetime,
    first_trading_day: date | None = None,
    date_only_fallback: bool = True,
    use_all_annuals_for_previous_reference: bool = True,
) -> pd.DataFrame:
    annuals = financials.copy()
    annuals = annuals[annuals["fiscal_quarter"] == 4].copy()
    latest = get_latest_known_financials(
        annuals,
        rebalance_datetime=rebalance_datetime,
        first_trading_day=first_trading_day,
        date_only_fallback=date_only_fallback,
    )
    if latest.empty:
        return latest

    previous_source = annuals if use_all_annuals_for_previous_reference else latest
    previous = previous_source[["symbol", "fiscal_year", "net_income", "operating_profit"]].copy()
    previous["fiscal_year"] = previous["fiscal_year"] + 1
    previous = previous.rename(
        columns={
            "net_income": "previous_annual_net_income",
            "operating_profit": "previous_annual_operating_profit",
        }
    )
    latest = latest.merge(previous, on=["symbol", "fiscal_year"], how="left")
    # Reuse existing filter pipeline by exposing annual fields through the same names.
    latest["net_income_ttm"] = latest["net_income"]
    latest["previous_net_income_ttm"] = latest["previous_annual_net_income"]
    latest["operating_profit_ttm"] = latest["operating_profit"]
    return latest


def get_latest_known_annual_financials_with_stale_replacement(
    financials: pd.DataFrame,
    rebalance_datetime: datetime,
    first_trading_day: date | None = None,
    date_only_fallback: bool = True,
    use_all_annuals_for_previous_reference: bool = True,
    max_allowed_quarter_lag: int = 4,
) -> pd.DataFrame:
    annual_latest = get_latest_known_annual_financials(
        financials,
        rebalance_datetime=rebalance_datetime,
        first_trading_day=first_trading_day,
        date_only_fallback=date_only_fallback,
        use_all_annuals_for_previous_reference=use_all_annuals_for_previous_reference,
    )
    if annual_latest.empty:
        return annual_latest

    result = annual_latest.copy()
    result["annual_base_original_period_end"] = result.get("period_end")
    result["annual_base_original_fiscal_year"] = result.get("fiscal_year")
    result["annual_base_original_fiscal_quarter"] = result.get("fiscal_quarter")
    result["annual_base_replaced"] = False
    result["financial_base_correction"] = pd.NA

    buy_ts = pd.Timestamp(first_trading_day)
    buy_year = buy_ts.year
    buy_quarter = ((buy_ts.month - 1) // 3) + 1
    fiscal_year = pd.to_numeric(result.get("fiscal_year"), errors="coerce")
    fiscal_quarter = pd.to_numeric(result.get("fiscal_quarter"), errors="coerce")
    lag = ((buy_year - fiscal_year) * 4) + (buy_quarter - fiscal_quarter)
    stale_mask = lag.ge(max_allowed_quarter_lag + 1).fillna(False)
    if not stale_mask.any():
        return result

    latest_known = get_latest_known_financials(
        financials,
        rebalance_datetime=rebalance_datetime,
        first_trading_day=first_trading_day,
        date_only_fallback=date_only_fallback,
    )
    if latest_known.empty:
        return result

    latest_known = latest_known.rename(
        columns={column: f"{column}__latest" for column in latest_known.columns if column != "symbol"}
    )
    merged = result.merge(latest_known, on="symbol", how="left")
    latest_period_end = pd.to_datetime(merged.get("period_end__latest"), errors="coerce")
    current_period_end = pd.to_datetime(merged.get("period_end"), errors="coerce")
    replace_mask = stale_mask & latest_period_end.notna() & (latest_period_end > current_period_end)
    if not replace_mask.any():
        return merged.drop(columns=[column for column in merged.columns if column.endswith("__latest")], errors="ignore")

    replaceable_columns = [
        "period_end",
        "fiscal_year",
        "fiscal_period",
        "fiscal_quarter",
        "announcement_datetime",
        "announcement_date",
        "net_income",
        "equity",
        "operating_profit",
        "cash",
        "total_debt",
        "shares_outstanding",
        "shares_announcement_datetime",
        "shares_source_url",
        "net_income_ttm",
        "operating_profit_ttm",
        "previous_net_income_ttm",
        "net_income_growth",
        "source_statement_id",
        "source_url",
        "announcement_source_url",
        "raw_hash",
    ]
    for column in replaceable_columns:
        latest_column = f"{column}__latest"
        if latest_column not in merged.columns or column not in merged.columns:
            continue
        merged.loc[replace_mask, column] = merged.loc[replace_mask, latest_column]

    merged.loc[replace_mask, "annual_base_replaced"] = True
    merged.loc[replace_mask, "financial_base_correction"] = "replaced_stale_annual_with_latest_known"
    return merged.drop(columns=[column for column in merged.columns if column.endswith("__latest")], errors="ignore")

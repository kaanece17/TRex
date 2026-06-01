from __future__ import annotations

import pandas as pd


def add_quarterly_values(cumulative: pd.DataFrame) -> pd.DataFrame:
    data = cumulative.copy()
    data = data.sort_values(["symbol", "fiscal_year", "fiscal_quarter"])
    for column in ["net_income", "operating_profit", "revenue", "operating_cash_flow"]:
        if column not in data.columns:
            continue
        previous = data.groupby(["symbol", "fiscal_year"])[column].shift(1).fillna(0)
        data[f"quarterly_{column}"] = data[column] - previous
    return data


def _fill_ttm_from_cumulative_fallback(data: pd.DataFrame, cumulative_column: str, ttm_column: str) -> pd.DataFrame:
    # For Q1-Q3 cumulative reports, TTM can be reconstructed as:
    # previous annual cumulative + current cumulative - previous-year same-quarter cumulative.
    previous_same_quarter = data[["symbol", "fiscal_year", "fiscal_quarter", cumulative_column]].copy()
    previous_same_quarter["fiscal_year"] = previous_same_quarter["fiscal_year"] + 1
    previous_same_quarter = previous_same_quarter.rename(columns={cumulative_column: f"previous_{cumulative_column}"})

    previous_annual = data[data["fiscal_quarter"] == 4][["symbol", "fiscal_year", cumulative_column]].copy()
    previous_annual["fiscal_year"] = previous_annual["fiscal_year"] + 1
    previous_annual = previous_annual.rename(columns={cumulative_column: f"previous_annual_{cumulative_column}"})

    merged = data.merge(
        previous_same_quarter,
        on=["symbol", "fiscal_year", "fiscal_quarter"],
        how="left",
    ).merge(
        previous_annual,
        on=["symbol", "fiscal_year"],
        how="left",
    )

    fallback_mask = (
        merged[ttm_column].isna()
        & merged["fiscal_quarter"].isin([1, 2, 3])
        & merged[f"previous_{cumulative_column}"].notna()
        & merged[f"previous_annual_{cumulative_column}"].notna()
    )
    merged.loc[fallback_mask, ttm_column] = (
        merged.loc[fallback_mask, f"previous_annual_{cumulative_column}"]
        + merged.loc[fallback_mask, cumulative_column]
        - merged.loc[fallback_mask, f"previous_{cumulative_column}"]
    )
    return merged.drop(columns=[f"previous_{cumulative_column}", f"previous_annual_{cumulative_column}"])


def add_ttm_values(cumulative: pd.DataFrame) -> pd.DataFrame:
    data = cumulative.copy()
    data = data.drop(
        columns=[
            "quarterly_net_income",
            "quarterly_operating_profit",
            "quarterly_revenue",
            "quarterly_operating_cash_flow",
            "net_income_ttm",
            "operating_profit_ttm",
            "revenue_ttm",
            "operating_cash_flow_ttm",
            "previous_net_income_ttm",
            "previous_revenue_ttm",
            "net_income_growth",
        ],
        errors="ignore",
    )
    data = add_quarterly_values(data)
    data = data.sort_values(["symbol", "period_end"])
    for cumulative_column, quarterly_column, ttm_column in [
        ("net_income", "quarterly_net_income", "net_income_ttm"),
        ("operating_profit", "quarterly_operating_profit", "operating_profit_ttm"),
        ("revenue", "quarterly_revenue", "revenue_ttm"),
        ("operating_cash_flow", "quarterly_operating_cash_flow", "operating_cash_flow_ttm"),
    ]:
        if quarterly_column not in data.columns:
            continue
        data[ttm_column] = (
            data.groupby("symbol")[quarterly_column].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
        )
        q4_mask = data["fiscal_quarter"] == 4
        q4_fill = q4_mask & data[ttm_column].isna()
        if cumulative_column in data.columns:
            data.loc[q4_fill, ttm_column] = data.loc[q4_fill, cumulative_column]
            data = _fill_ttm_from_cumulative_fallback(data, cumulative_column=cumulative_column, ttm_column=ttm_column)
    previous = data[["symbol", "fiscal_year", "fiscal_quarter", "net_income_ttm"]].copy()
    previous["fiscal_year"] = previous["fiscal_year"] + 1
    previous = previous.rename(columns={"net_income_ttm": "previous_net_income_ttm"})
    data = data.merge(previous, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    if "revenue_ttm" in data.columns:
        previous_revenue = data[["symbol", "fiscal_year", "fiscal_quarter", "revenue_ttm"]].copy()
        previous_revenue["fiscal_year"] = previous_revenue["fiscal_year"] + 1
        previous_revenue = previous_revenue.rename(columns={"revenue_ttm": "previous_revenue_ttm"})
        data = data.merge(previous_revenue, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    data["net_income_growth"] = (data["net_income_ttm"] - data["previous_net_income_ttm"]) / data["previous_net_income_ttm"]
    return data


def add_earnings_momentum_features(cumulative: pd.DataFrame) -> pd.DataFrame:
    data = cumulative.copy()
    data = data.drop(
        columns=[
            "ni_ttm_growth_yoy",
            "op_ttm_growth_yoy",
            "revenue_ttm_growth_yoy",
            "revenue_acceleration",
            "asset_growth_yoy",
            "accruals_ratio",
            "filing_lag_days",
            "earnings_acceleration",
            "profitability_quality_combo",
        ],
        errors="ignore",
    )
    data = data.sort_values(["symbol", "period_end"]).reset_index(drop=True)
    data["ni_ttm_growth_yoy"] = (data["net_income_ttm"] - data["previous_net_income_ttm"]) / data["previous_net_income_ttm"]

    previous_op = data[["symbol", "fiscal_year", "fiscal_quarter", "operating_profit_ttm"]].copy()
    previous_op["fiscal_year"] = previous_op["fiscal_year"] + 1
    previous_op = previous_op.rename(columns={"operating_profit_ttm": "previous_operating_profit_ttm"})
    data = data.merge(previous_op, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    data["op_ttm_growth_yoy"] = (
        data["operating_profit_ttm"] - data["previous_operating_profit_ttm"]
    ) / data["previous_operating_profit_ttm"]

    data["previous_ni_ttm_growth_yoy"] = data.groupby("symbol")["ni_ttm_growth_yoy"].shift(1)
    data["earnings_acceleration"] = data["ni_ttm_growth_yoy"] - data["previous_ni_ttm_growth_yoy"]
    if "revenue_ttm" in data.columns and "previous_revenue_ttm" in data.columns:
        data["revenue_ttm_growth_yoy"] = (data["revenue_ttm"] - data["previous_revenue_ttm"]) / data["previous_revenue_ttm"]
        data["previous_revenue_ttm_growth_yoy"] = data.groupby("symbol")["revenue_ttm_growth_yoy"].shift(1)
        data["revenue_acceleration"] = data["revenue_ttm_growth_yoy"] - data["previous_revenue_ttm_growth_yoy"]
    if "total_assets" in data.columns:
        previous_assets = data[["symbol", "fiscal_year", "fiscal_quarter", "total_assets"]].copy()
        previous_assets["fiscal_year"] = previous_assets["fiscal_year"] + 1
        previous_assets = previous_assets.rename(columns={"total_assets": "previous_total_assets"})
        data = data.merge(previous_assets, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
        data["asset_growth_yoy"] = (data["total_assets"] - data["previous_total_assets"]) / data["previous_total_assets"]
        if "operating_cash_flow_ttm" in data.columns:
            avg_assets = (pd.to_numeric(data["total_assets"], errors="coerce") + pd.to_numeric(data["previous_total_assets"], errors="coerce")) / 2.0
            avg_assets = avg_assets.where(avg_assets != 0)
            data["accruals_ratio"] = (
                pd.to_numeric(data["net_income_ttm"], errors="coerce")
                - pd.to_numeric(data["operating_cash_flow_ttm"], errors="coerce")
            ) / avg_assets
    if "announcement_date" in data.columns and "period_end" in data.columns:
        announcement_dates = pd.to_datetime(data["announcement_date"], errors="coerce")
        period_end = pd.to_datetime(data["period_end"], errors="coerce")
        data["filing_lag_days"] = (announcement_dates - period_end).dt.days

    profitability_score = pd.concat(
        [
            data["net_income_ttm"].gt(0),
            data["previous_net_income_ttm"].gt(0),
            data["operating_profit_ttm"].gt(0),
        ],
        axis=1,
    ).mean(axis=1)
    positive_growth = pd.concat(
        [
            data["ni_ttm_growth_yoy"].clip(lower=0),
            data["op_ttm_growth_yoy"].clip(lower=0),
        ],
        axis=1,
    ).mean(axis=1, skipna=True)
    data["profitability_quality_combo"] = profitability_score * (1 + positive_growth.fillna(0.0))

    return data.drop(
        columns=[
            "previous_operating_profit_ttm",
            "previous_ni_ttm_growth_yoy",
            "previous_revenue_ttm_growth_yoy",
            "previous_total_assets",
        ],
        errors="ignore",
    )

from __future__ import annotations

import pandas as pd


def add_quarterly_values(cumulative: pd.DataFrame) -> pd.DataFrame:
    data = cumulative.copy()
    data = data.sort_values(["symbol", "fiscal_year", "fiscal_quarter"])
    for column in ["net_income", "operating_profit"]:
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
        columns=["quarterly_net_income", "quarterly_operating_profit", "net_income_ttm", "operating_profit_ttm", "previous_net_income_ttm", "net_income_growth"],
        errors="ignore",
    )
    data = add_quarterly_values(data)
    data = data.sort_values(["symbol", "period_end"])
    data["net_income_ttm"] = (
        data.groupby("symbol")["quarterly_net_income"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    )
    data["operating_profit_ttm"] = (
        data.groupby("symbol")["quarterly_operating_profit"].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    )
    # For year-end cumulative reports, the full-year cumulative value is itself a valid
    # TTM anchor even when one of the earlier quarterly filings is unavailable.
    q4_mask = data["fiscal_quarter"] == 4
    q4_net_income_fill = q4_mask & data["net_income_ttm"].isna()
    q4_operating_fill = q4_mask & data["operating_profit_ttm"].isna()
    data.loc[q4_net_income_fill, "net_income_ttm"] = data.loc[q4_net_income_fill, "net_income"]
    data.loc[q4_operating_fill, "operating_profit_ttm"] = data.loc[q4_operating_fill, "operating_profit"]
    data = _fill_ttm_from_cumulative_fallback(data, cumulative_column="net_income", ttm_column="net_income_ttm")
    data = _fill_ttm_from_cumulative_fallback(data, cumulative_column="operating_profit", ttm_column="operating_profit_ttm")
    previous = data[["symbol", "fiscal_year", "fiscal_quarter", "net_income_ttm"]].copy()
    previous["fiscal_year"] = previous["fiscal_year"] + 1
    previous = previous.rename(columns={"net_income_ttm": "previous_net_income_ttm"})
    data = data.merge(previous, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    data["net_income_growth"] = (data["net_income_ttm"] - data["previous_net_income_ttm"]) / data["previous_net_income_ttm"]
    return data


def add_earnings_momentum_features(cumulative: pd.DataFrame) -> pd.DataFrame:
    data = cumulative.copy()
    data = data.sort_values(["symbol", "period_end"]).reset_index(drop=True)

    def _series(name: str) -> pd.Series:
        if name not in data.columns:
            return pd.Series(float("nan"), index=data.index, dtype="float64")
        return pd.to_numeric(data[name], errors="coerce")

    previous_year = data[
        [
            "symbol",
            "fiscal_year",
            "fiscal_quarter",
            "net_income_ttm",
            "operating_profit_ttm",
            "net_income_growth",
        ]
    ].copy()
    previous_year["fiscal_year"] = previous_year["fiscal_year"] + 1
    previous_year = previous_year.rename(
        columns={
            "net_income_ttm": "previous_year_net_income_ttm",
            "operating_profit_ttm": "previous_year_operating_profit_ttm",
            "net_income_growth": "previous_year_net_income_growth",
        }
    )
    data = data.merge(previous_year, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")

    data["ni_ttm_growth_yoy"] = (
        _series("net_income_ttm")
        - pd.to_numeric(data["previous_year_net_income_ttm"], errors="coerce")
    ) / pd.to_numeric(data["previous_year_net_income_ttm"], errors="coerce")
    data["op_ttm_growth_yoy"] = (
        _series("operating_profit_ttm")
        - pd.to_numeric(data["previous_year_operating_profit_ttm"], errors="coerce")
    ) / pd.to_numeric(data["previous_year_operating_profit_ttm"], errors="coerce")
    data["earnings_acceleration"] = (
        _series("net_income_growth")
        - pd.to_numeric(data["previous_year_net_income_growth"], errors="coerce")
    )

    profitability = _series("net_income_ttm") / _series("equity")
    quality_strength = _series("operating_profit_ttm") / _series("firm_value")
    earnings_strength = pd.to_numeric(data["ni_ttm_growth_yoy"], errors="coerce")
    data["profitability_quality_combo"] = profitability + quality_strength + earnings_strength.fillna(0.0)

    return data.drop(
        columns=[
            "previous_year_net_income_ttm",
            "previous_year_operating_profit_ttm",
            "previous_year_net_income_growth",
        ],
        errors="ignore",
    )

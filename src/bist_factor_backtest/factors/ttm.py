from __future__ import annotations

import pandas as pd


def add_quarterly_values(cumulative: pd.DataFrame) -> pd.DataFrame:
    data = cumulative.copy()
    data = data.sort_values(["symbol", "fiscal_year", "fiscal_quarter"])
    for column in ["net_income", "operating_profit"]:
        previous = data.groupby(["symbol", "fiscal_year"])[column].shift(1).fillna(0)
        data[f"quarterly_{column}"] = data[column] - previous
    return data


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
    previous = data[["symbol", "fiscal_year", "fiscal_quarter", "net_income_ttm"]].copy()
    previous["fiscal_year"] = previous["fiscal_year"] + 1
    previous = previous.rename(columns={"net_income_ttm": "previous_net_income_ttm"})
    data = data.merge(previous, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    data["net_income_growth"] = (data["net_income_ttm"] - data["previous_net_income_ttm"]) / data["previous_net_income_ttm"]
    return data

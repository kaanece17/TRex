from __future__ import annotations

import pandas as pd

from bist_factor_backtest.config import ScoringConfig


MIN_GROWTH = -0.95
MAX_GROWTH = 3.0


def calculate_scores(data: pd.DataFrame, scoring: ScoringConfig | None = None) -> pd.DataFrame:
    result = data.copy()
    formula = scoring.formula if scoring is not None else "x1_plus_x2"
    if formula == "note_exact":
        raw_growth = (result["net_income"] - result["previous_annual_net_income"]) / result["previous_annual_net_income"]
        result["net_income_growth"] = raw_growth
        result["x1"] = (result["net_income"] / result["equity"]) * (1 + result["net_income_growth"])
        result["x2"] = result["operating_profit"] / result["firm_value"]
        result["score"] = result["x1"] + result["x2"]
        return result
    if formula == "note_best_fit":
        raw_growth = (
            result["latest_cum_net_income"] - result["previous_same_quarter_cum_net_income"]
        ) / result["previous_same_quarter_cum_net_income"]
        result["net_income_growth"] = raw_growth
        result["x1"] = (result["net_income"] / result["equity"]) * (1 + result["net_income_growth"])
        result["x2"] = result["operating_profit"] / result["firm_value"]
        result["score"] = result["x1"] + result["x2"]
        return result
    raw_growth = (
        result["net_income_ttm"] - result["previous_net_income_ttm"]
    ) / result["previous_net_income_ttm"]
    growth_mode = scoring.growth_mode if scoring is not None else "normalized_percent_cap"
    if growth_mode == "raw":
        result["net_income_growth"] = raw_growth
    elif growth_mode == "normalized_percent_cap":
        normalized_growth = raw_growth.where(raw_growth <= 1.0, raw_growth / 100.0)
        result["net_income_growth"] = normalized_growth.clip(lower=MIN_GROWTH, upper=MAX_GROWTH)
    else:
        raise ValueError(f"Unsupported growth mode: {growth_mode}")
    result["x1"] = (result["net_income_ttm"] / result["equity"]) * (1 + result["net_income_growth"])
    result["x2"] = result["operating_profit_ttm"] / result["firm_value"]
    result["score"] = result["x1"] + result["x2"]
    return result

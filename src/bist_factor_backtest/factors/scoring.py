from __future__ import annotations

import pandas as pd


MIN_GROWTH = -0.95
MAX_GROWTH = 3.0


def calculate_scores(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    raw_growth = (
        result["net_income_ttm"] - result["previous_net_income_ttm"]
    ) / result["previous_net_income_ttm"]
    normalized_growth = raw_growth.where(raw_growth <= 1.0, raw_growth / 100.0)
    result["net_income_growth"] = normalized_growth.clip(lower=MIN_GROWTH, upper=MAX_GROWTH)
    result["x1"] = (result["net_income_ttm"] / result["equity"]) * (1 + result["net_income_growth"])
    result["x2"] = result["operating_profit_ttm"] / result["firm_value"]
    result["score"] = result["x1"] + result["x2"]
    return result

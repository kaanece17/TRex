from __future__ import annotations

import pandas as pd

from bist_factor_backtest.config import ScoringConfig


MIN_GROWTH = -0.95
MAX_GROWTH = 3.0


def calculate_scores(data: pd.DataFrame, scoring: ScoringConfig | None = None) -> pd.DataFrame:
    result = data.copy()
    formula = scoring.formula if scoring is not None else "x1_plus_x2"
    x1_weight = scoring.x1_weight if scoring is not None else 1.0
    x2_weight = scoring.x2_weight if scoring is not None else 1.0
    if formula == "note_exact":
        raw_growth = (result["net_income"] - result["previous_annual_net_income"]) / result["previous_annual_net_income"]
        result["net_income_growth"] = raw_growth
        result["x1"] = (result["net_income"] / result["equity"]) * (1 + result["net_income_growth"])
        result["x2"] = result["operating_profit"] / result["firm_value"]
        _apply_component_caps(result, scoring)
        _attach_component_shares(result)
        result["score"] = (result["x1"] * x1_weight) + (result["x2"] * x2_weight)
        _attach_selection_score(result, scoring)
        return result
    if formula == "note_best_fit":
        raw_growth = (
            result["latest_cum_net_income"] - result["previous_same_quarter_cum_net_income"]
        ) / result["previous_same_quarter_cum_net_income"]
        result["net_income_growth"] = raw_growth
        result["x1"] = (result["net_income"] / result["equity"]) * (1 + result["net_income_growth"])
        result["x2"] = result["operating_profit"] / result["firm_value"]
        _apply_component_caps(result, scoring)
        _attach_component_shares(result)
        result["score"] = (result["x1"] * x1_weight) + (result["x2"] * x2_weight)
        _attach_selection_score(result, scoring)
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
    _apply_component_caps(result, scoring)
    _attach_component_shares(result)
    result["score"] = (result["x1"] * x1_weight) + (result["x2"] * x2_weight)
    _attach_selection_score(result, scoring)
    return result


def _apply_component_caps(result: pd.DataFrame, scoring: ScoringConfig | None) -> None:
    if scoring is None:
        return
    _cap_series_at_quantile(result, "x1", scoring.x1_cap_quantile)
    _cap_series_at_quantile(result, "x2", scoring.x2_cap_quantile)


def _attach_component_shares(result: pd.DataFrame) -> None:
    denominator = result["x1"] + result["x2"]
    denominator = denominator.where(denominator != 0)
    result["x1_share"] = result["x1"] / denominator
    result["x2_share"] = result["x2"] / denominator


def _attach_selection_score(result: pd.DataFrame, scoring: ScoringConfig | None) -> None:
    result["selection_score"] = result["score"]
    if scoring is None or scoring.momentum_rank_weight == 0:
        return
    if "recent_return_20d" not in result.columns:
        return
    momentum = pd.to_numeric(result["recent_return_20d"], errors="coerce")
    if momentum.notna().sum() == 0:
        return
    momentum_pct = momentum.rank(method="average", pct=True)
    momentum_bonus = (momentum_pct - 0.5).fillna(0.0) * scoring.momentum_rank_weight
    result["selection_score"] = result["score"] + momentum_bonus


def _cap_series_at_quantile(result: pd.DataFrame, column: str, quantile: float | None) -> None:
    if quantile is None:
        return
    if quantile <= 0 or quantile >= 1:
        return
    series = pd.to_numeric(result[column], errors="coerce")
    if series.notna().sum() == 0:
        return
    cap_value = float(series.quantile(quantile))
    result[column] = series.clip(upper=cap_value)

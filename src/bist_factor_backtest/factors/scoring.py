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
    raw_growth = (result["net_income_ttm"] - result["previous_net_income_ttm"]) / result["previous_net_income_ttm"]
    result["net_income_growth"] = _normalize_growth_series(raw_growth, scoring)
    result["x1"] = (result["net_income_ttm"] / result["equity"]) * (1 + result["net_income_growth"])
    result["x2"] = result["operating_profit_ttm"] / result["firm_value"]
    _apply_component_caps(result, scoring)
    _attach_component_shares(result)
    base_score = (result["x1"] * x1_weight) + (result["x2"] * x2_weight)
    if formula == "quality_plus_earnings":
        earnings_weight = scoring.earnings_weight if scoring is not None else 1.0
        earnings_signal = _build_earnings_signal(
            result,
            scoring,
            feature_names=[
                "ni_ttm_growth_yoy",
                "op_ttm_growth_yoy",
                "earnings_acceleration",
                "profitability_quality_combo",
            ],
        )
        result["earnings_signal"] = earnings_signal
        result["score"] = base_score + (earnings_signal * earnings_weight)
    elif formula == "quality_plus_op_growth":
        earnings_weight = scoring.earnings_weight if scoring is not None else 1.0
        earnings_signal = _build_earnings_signal(
            result,
            scoring,
            feature_names=[
                "op_ttm_growth_yoy",
            ],
        )
        result["earnings_signal"] = earnings_signal
        result["score"] = base_score + (earnings_signal * earnings_weight)
    else:
        result["score"] = base_score
    _attach_selection_score(result, scoring)
    return result


def _apply_component_caps(result: pd.DataFrame, scoring: ScoringConfig | None) -> None:
    if scoring is None:
        return
    _cap_series_at_quantile(result, "x1", scoring.x1_cap_quantile)
    _cap_series_at_quantile(result, "x2", scoring.x2_cap_quantile)


def _normalize_growth_series(series: pd.Series, scoring: ScoringConfig | None) -> pd.Series:
    growth_mode = scoring.growth_mode if scoring is not None else "normalized_percent_cap"
    if growth_mode == "raw":
        return series
    if growth_mode == "normalized_percent_cap":
        normalized_growth = series.where(series <= 1.0, series / 100.0)
        return normalized_growth.clip(lower=MIN_GROWTH, upper=MAX_GROWTH)
    raise ValueError(f"Unsupported growth mode: {growth_mode}")


def _build_earnings_signal(
    result: pd.DataFrame,
    scoring: ScoringConfig | None,
    feature_names: list[str] | None = None,
) -> pd.Series:
    def _series(name: str) -> pd.Series:
        if name not in result.columns:
            return pd.Series(pd.NA, index=result.index, dtype="float64")
        return pd.to_numeric(result[name], errors="coerce")

    feature_map = {
        "ni_ttm_growth_yoy": _normalize_growth_series(_series("ni_ttm_growth_yoy"), scoring),
        "op_ttm_growth_yoy": _normalize_growth_series(_series("op_ttm_growth_yoy"), scoring),
        "earnings_acceleration": _normalize_growth_series(_series("earnings_acceleration"), scoring),
        "profitability_quality_combo": _series("profitability_quality_combo"),
    }
    selected_names = feature_names or list(feature_map.keys())
    ranked_features: list[pd.Series] = []
    for name in selected_names:
        series = feature_map[name]
        working = pd.to_numeric(series, errors="coerce")
        if name != "profitability_quality_combo":
            working = working.clip(lower=MIN_GROWTH, upper=MAX_GROWTH)
        if working.notna().sum() == 0:
            continue
        ranked = working.rank(method="average", pct=True)
        ranked_features.append(ranked)
    if not ranked_features:
        return pd.Series(0.0, index=result.index)
    combined_rank = pd.concat(ranked_features, axis=1).mean(axis=1, skipna=True)
    return (combined_rank.fillna(0.5) - 0.5) * 2.0


def _attach_component_shares(result: pd.DataFrame) -> None:
    denominator = result["x1"] + result["x2"]
    denominator = denominator.where(denominator != 0)
    result["x1_share"] = result["x1"] / denominator
    result["x2_share"] = result["x2"] / denominator


def _attach_selection_score(result: pd.DataFrame, scoring: ScoringConfig | None) -> None:
    result["selection_score"] = result["score"]
    if scoring is None:
        return

    if scoring.momentum_rank_weight != 0 and "recent_return_20d" in result.columns:
        momentum = pd.to_numeric(result["recent_return_20d"], errors="coerce")
        if momentum.notna().sum() > 0:
            momentum_pct = momentum.rank(method="average", pct=True)
            momentum_bonus = (momentum_pct - 0.5).fillna(0.0) * scoring.momentum_rank_weight
            result["selection_score"] = result["selection_score"] + momentum_bonus

    if (
        scoring.cheap_value_trap_penalty != 0
        and scoring.cheap_value_trap_fv_to_equity_threshold is not None
        and scoring.x1_dominant_value_penalty_share_threshold is not None
        and "firm_value" in result.columns
        and "equity" in result.columns
        and "x1_share" in result.columns
    ):
        fv_to_equity = pd.to_numeric(result["firm_value"], errors="coerce") / pd.to_numeric(result["equity"], errors="coerce")
        penalty_mask = (
            (result["x1_share"] >= scoring.x1_dominant_value_penalty_share_threshold)
            & (fv_to_equity >= 0)
            & (fv_to_equity < scoring.cheap_value_trap_fv_to_equity_threshold)
        )
        result["selection_score"] = result["selection_score"] - penalty_mask.fillna(False).astype(float) * scoring.cheap_value_trap_penalty


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

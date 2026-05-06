from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd

from bist_factor_backtest.backtest.execution import calculate_position_return_open_to_open
from bist_factor_backtest.backtest.portfolio import build_equal_weight_positions
from bist_factor_backtest.config import BacktestConfig
from bist_factor_backtest.data.calendar import (
    get_backtest_months,
    get_first_trading_day,
    get_last_trading_day,
    get_market_open_datetime,
)
from bist_factor_backtest.data.point_in_time import get_latest_known_financials
from bist_factor_backtest.data.universe import get_universe_for_date
from bist_factor_backtest.factors.filters import FilterSettings, apply_filters
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value
from bist_factor_backtest.factors.liquidity import attach_avg_turnover_20d
from bist_factor_backtest.factors.scoring import calculate_scores


def run_monthly_rotation_backtest(
    config: BacktestConfig,
    prices: pd.DataFrame,
    financial_snapshots: pd.DataFrame,
    universe_membership: pd.DataFrame,
) -> dict[str, pd.DataFrame | str]:
    run_id = str(uuid4())
    prepared_prices = prices.copy()
    prepared_prices["date"] = pd.to_datetime(prepared_prices["date"]).dt.date
    feature_prices = prepared_prices
    known_symbols = set(financial_snapshots["symbol"].dropna().astype(str).unique())
    if known_symbols:
        feature_prices = prepared_prices[prepared_prices["symbol"].isin(known_symbols)].copy()
    feature_months = get_backtest_months(feature_prices, config.backtest.start_date, config.backtest.end_date)
    if feature_months:
        calendar_prices = feature_prices
        months = feature_months
    else:
        calendar_prices = prepared_prices
        months = get_backtest_months(calendar_prices, config.backtest.start_date, config.backtest.end_date)
    monthly_results = []
    selected_positions = []
    rejected_candidates = []
    portfolio_value = config.backtest.initial_capital

    for month in months:
        buy_date = get_first_trading_day(calendar_prices, month)
        sell_date = get_last_trading_day(calendar_prices, month)
        rebalance_datetime = get_market_open_datetime(
            buy_date,
            config.strategy.market_open_time,
            config.project.timezone,
        )
        known = get_latest_known_financials(financial_snapshots, rebalance_datetime, buy_date)
        universe = get_universe_for_date(universe_membership, config.universe.name, buy_date)
        candidates = known[known["symbol"].isin(universe)].copy()
        candidates = _attach_universe_metadata(candidates, universe_membership, config.universe.name, buy_date)
        if candidates.empty:
            selected = candidates
        else:
            candidates = attach_avg_turnover_20d(candidates, feature_prices, buy_date)
            candidates = attach_market_cap_firm_value(candidates, feature_prices, rebalance_datetime)
            candidates = calculate_scores(candidates)
            filter_settings = FilterSettings(**config.filters.model_dump())
            filtered, rejected = apply_filters(candidates, filter_settings)
            rejected["month"] = month
            rejected_candidates.append(rejected)
            selected = filtered.sort_values("score", ascending=False).head(config.strategy.top_n)
        positions = build_equal_weight_positions(selected)
        position_returns = []
        for position in positions.to_dict("records"):
            position_return = calculate_position_return_open_to_open(
                calendar_prices,
                position["symbol"],
                buy_date,
                sell_date,
                config.costs.commission_rate,
            )
            if position_return is None:
                position["reason"] = "missing_price"
                rejected_candidates.append(pd.DataFrame([position]).assign(month=month))
                continue
            position.update(position_return)
            position_returns.append(position)

        positions_result = pd.DataFrame(position_returns)
        if positions_result.empty:
            gross_return = 0.0
            net_return = 0.0
            selected_symbols = ""
        else:
            gross_return = float((positions_result["weight"] * positions_result["gross_return"]).sum())
            net_return = float((positions_result["weight"] * positions_result["net_return"]).sum())
            selected_symbols = ",".join(positions_result["symbol"].tolist())
            positions_result["run_id"] = run_id
            positions_result["month"] = month
            positions_result["used_period_end"] = positions_result["period_end"]
            positions_result["used_announcement_datetime"] = positions_result["announcement_datetime"]
            selected_positions.append(positions_result)

        start_value = portfolio_value
        portfolio_value = portfolio_value * (1 + net_return)
        monthly_results.append(
            {
                "run_id": run_id,
                "month": month,
                "rebalance_datetime": rebalance_datetime,
                "buy_date": buy_date,
                "sell_date": sell_date,
                "gross_return": gross_return,
                "net_return": net_return,
                "portfolio_value_start": start_value,
                "portfolio_value_end": portfolio_value,
                "selected_symbols": selected_symbols,
            }
        )

    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "monthly_results": pd.DataFrame(monthly_results),
        "selected_positions": pd.concat(selected_positions, ignore_index=True) if selected_positions else pd.DataFrame(),
        "rejected_candidates": pd.concat(rejected_candidates, ignore_index=True) if rejected_candidates else pd.DataFrame(),
    }


def _attach_universe_metadata(
    candidates: pd.DataFrame,
    universe_membership: pd.DataFrame,
    universe_name: str,
    as_of_date,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    membership = universe_membership.copy()
    for column, default in {"source_type": "unknown", "source_url": None, "confidence": "low"}.items():
        if column not in membership.columns:
            membership[column] = default
    membership["start_date"] = pd.to_datetime(membership["start_date"]).dt.date
    membership["end_date"] = pd.to_datetime(membership["end_date"], errors="coerce").map(
        lambda value: None if pd.isna(value) else value.date()
    )
    active = membership[
        (membership["universe_name"] == universe_name)
        & (membership["start_date"] <= as_of_date)
        & (membership["end_date"].isna() | (membership["end_date"] >= as_of_date))
    ]
    metadata = active[["symbol", "source_type", "source_url", "confidence"]].rename(
        columns={
            "source_type": "universe_source_type",
            "source_url": "universe_source_url",
            "confidence": "universe_confidence",
        }
    )
    return candidates.merge(metadata, on="symbol", how="left")

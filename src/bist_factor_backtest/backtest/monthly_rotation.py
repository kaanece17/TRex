from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd

from bist_factor_backtest.backtest.execution import calculate_position_return_open_to_open
from bist_factor_backtest.backtest.portfolio import build_positions
from bist_factor_backtest.config import BacktestConfig
from bist_factor_backtest.data.calendar import (
    get_backtest_months,
    get_first_trading_day,
    get_last_trading_day,
    get_market_open_datetime,
)
from bist_factor_backtest.data.point_in_time import get_latest_known_annual_financials, get_latest_known_financials
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
    previous_held_symbols: set[str] = set()
    selection_plan: list[dict] = []

    for month_index, month in enumerate(months):
        buy_date = get_first_trading_day(calendar_prices, month)
        sell_date = _resolve_sell_date(
            calendar_prices,
            months,
            month_index,
            month,
            config.strategy.execution_mode,
        )
        rebalance_datetime = get_market_open_datetime(
            buy_date,
            config.strategy.market_open_time,
            config.project.timezone,
        )
        if config.scoring.formula in {"note_exact", "note_best_fit"}:
            known = get_latest_known_annual_financials(financial_snapshots, rebalance_datetime, buy_date)
            if config.scoring.formula == "note_best_fit" and not known.empty:
                known = _attach_note_best_fit_growth_inputs(known, financial_snapshots, rebalance_datetime, buy_date)
        else:
            known = get_latest_known_financials(financial_snapshots, rebalance_datetime, buy_date)
        universe = get_universe_for_date(universe_membership, config.universe.name, buy_date)
        candidates = known[known["symbol"].isin(universe)].copy()
        candidates = _attach_universe_metadata(candidates, universe_membership, config.universe.name, buy_date)
        if candidates.empty:
            selected = candidates
        else:
            candidates = attach_avg_turnover_20d(candidates, feature_prices, buy_date)
            candidates = attach_market_cap_firm_value(candidates, feature_prices, rebalance_datetime)
            candidates = calculate_scores(candidates, config.scoring)
            filter_settings = FilterSettings(**config.filters.model_dump())
            filtered, rejected = apply_filters(candidates, filter_settings)
            rejected["month"] = month
            rejected_candidates.append(rejected)
            ranked = filtered.sort_values("score", ascending=False)
            selected = _apply_hold_buffer_rule(
                ranked,
                previous_held_symbols,
                config.strategy.top_n,
                config.strategy.hold_buffer_rank,
            )
        positions = build_positions(
            selected,
            weighting=config.strategy.weighting,
            score_weight_cap=config.strategy.score_weight_cap,
        )
        selection_plan.append(
            {
                "month": month,
                "rebalance_datetime": rebalance_datetime,
                "buy_date": buy_date,
                "sell_date": sell_date,
                "positions": positions,
            }
        )
        previous_held_symbols = set(positions["symbol"].astype(str).tolist()) if not positions.empty else set()

    for plan_index, plan in enumerate(selection_plan):
        positions = plan["positions"]
        prev_symbols = (
            set(selection_plan[plan_index - 1]["positions"]["symbol"].astype(str).tolist())
            if plan_index > 0 and not selection_plan[plan_index - 1]["positions"].empty
            else set()
        )
        next_symbols = (
            set(selection_plan[plan_index + 1]["positions"]["symbol"].astype(str).tolist())
            if plan_index + 1 < len(selection_plan) and not selection_plan[plan_index + 1]["positions"].empty
            else set()
        )

        position_returns = []
        for position in positions.to_dict("records"):
            symbol = str(position["symbol"])
            buy_commission_rate = 0.0 if symbol in prev_symbols else config.costs.commission_rate
            sell_commission_rate = 0.0 if symbol in next_symbols else config.costs.commission_rate
            position_return = calculate_position_return_open_to_open(
                calendar_prices,
                symbol,
                plan["buy_date"],
                plan["sell_date"],
                buy_commission_rate,
                sell_commission_rate,
            )
            if position_return is None:
                position["reason"] = "missing_price"
                rejected_candidates.append(pd.DataFrame([position]).assign(month=plan["month"]))
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
            positions_result["month"] = plan["month"]
            positions_result["used_period_end"] = positions_result["period_end"]
            positions_result["used_announcement_datetime"] = positions_result["announcement_datetime"]
            selected_positions.append(positions_result)

        start_value = portfolio_value
        portfolio_value = portfolio_value * (1 + net_return)
        monthly_results.append(
            {
                "run_id": run_id,
                "month": plan["month"],
                "rebalance_datetime": plan["rebalance_datetime"],
                "buy_date": plan["buy_date"],
                "sell_date": plan["sell_date"],
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


def _resolve_sell_date(
    prices: pd.DataFrame,
    months: list[str],
    month_index: int,
    month: str,
    execution_mode: str,
):
    if execution_mode == "rebalance_open_to_open" and month_index + 1 < len(months):
        next_month = months[month_index + 1]
        return get_first_trading_day(prices, next_month)
    return get_last_trading_day(prices, month)


def _apply_hold_buffer_rule(
    ranked: pd.DataFrame,
    previous_held_symbols: set[str],
    top_n: int,
    hold_buffer_rank: int | None,
) -> pd.DataFrame:
    if ranked.empty:
        return ranked
    if not previous_held_symbols or hold_buffer_rank is None or hold_buffer_rank <= top_n:
        return ranked.head(top_n)

    buffer_pool = ranked.head(hold_buffer_rank)
    retained = buffer_pool[buffer_pool["symbol"].astype(str).isin(previous_held_symbols)]
    remaining_slots = max(top_n - len(retained), 0)
    if remaining_slots == 0:
        return retained.sort_values("score", ascending=False).head(top_n)

    additions = ranked[~ranked["symbol"].astype(str).isin(retained["symbol"].astype(str))].head(remaining_slots)
    selected = pd.concat([retained, additions], ignore_index=True).drop_duplicates(subset=["symbol"])
    return selected.sort_values("score", ascending=False).head(top_n)


def _attach_note_best_fit_growth_inputs(
    annual_known: pd.DataFrame,
    financial_snapshots: pd.DataFrame,
    rebalance_datetime,
    buy_date,
) -> pd.DataFrame:
    cutoff = pd.Timestamp(rebalance_datetime)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    latest = get_latest_known_financials(financial_snapshots, rebalance_datetime, buy_date)
    if latest.empty:
        enriched = annual_known.copy()
        enriched["latest_cum_net_income"] = pd.NA
        enriched["previous_same_quarter_cum_net_income"] = pd.NA
        return enriched

    known = financial_snapshots.copy()
    known["announcement_datetime"] = pd.to_datetime(known["announcement_datetime"], errors="coerce")
    if isinstance(known["announcement_datetime"].dtype, pd.DatetimeTZDtype):
        known["announcement_datetime"] = known["announcement_datetime"].dt.tz_localize(None)
    known["announcement_date"] = pd.to_datetime(known["announcement_date"], errors="coerce").dt.date
    known_dt = known[known["announcement_datetime"].notna() & (known["announcement_datetime"] <= cutoff)]
    known_date = known[
        known["announcement_datetime"].isna()
        & known["announcement_date"].notna()
        & (known["announcement_date"] < buy_date)
    ]
    known = pd.concat([known_dt, known_date], ignore_index=True)

    previous_same_quarter = known[["symbol", "fiscal_year", "fiscal_quarter", "net_income"]].copy()
    previous_same_quarter["fiscal_year"] = previous_same_quarter["fiscal_year"] + 1
    previous_same_quarter = previous_same_quarter.rename(
        columns={"net_income": "previous_same_quarter_cum_net_income"}
    )
    latest = latest.merge(previous_same_quarter, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    latest = latest.rename(columns={"net_income": "latest_cum_net_income"})

    enriched = annual_known.merge(
        latest[["symbol", "latest_cum_net_income", "previous_same_quarter_cum_net_income"]],
        on="symbol",
        how="left",
    )
    return enriched


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

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
from bist_factor_backtest.data.point_in_time import (
    get_latest_known_annual_financials_with_stale_replacement,
    get_latest_known_financials,
)
from bist_factor_backtest.data.universe import get_universe_for_date
from bist_factor_backtest.factors.filters import FilterSettings, apply_filters
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value
from bist_factor_backtest.factors.liquidity import (
    attach_avg_turnover_20d,
    attach_recent_return_20d,
    attach_recent_return_60d,
)
from bist_factor_backtest.factors.scoring import calculate_scores


def run_monthly_rotation_backtest(
    config: BacktestConfig,
    prices: pd.DataFrame,
    financial_snapshots: pd.DataFrame,
    universe_membership: pd.DataFrame,
    collect_diagnostics: bool = True,
    collect_positions: bool = True,
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
    months = _apply_rebalance_frequency(months, config.strategy.rebalance_frequency)
    monthly_results = []
    selected_positions = []
    planned_positions = []
    rejected_candidates = []
    candidate_diagnostics = []
    portfolio_value = config.backtest.initial_capital
    previous_held_symbols: set[str] = set()
    selection_plan: list[dict] = []
    realized_symbol_history: dict[str, list[tuple[pd.Period, float]]] = {}
    cooldown_symbol_history: dict[str, list[tuple[pd.Period, float]]] = {}

    for month_index, month in enumerate(months):
        if config.strategy.execution_mode == "rebalance_open_to_open" and month_index + 1 >= len(months):
            break
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
        if config.scoring.formula in {
            "note_exact",
            "note_best_fit",
            "note_best_fit_plus_earnings",
            "note_best_fit_product",
            "note_best_fit_signed_sqrt_product",
            "note_best_fit_harmonic",
            "note_best_fit_soft_quality_tilt",
            "note_best_fit_x1_quality_tilt",
            "note_best_fit_x2_quality_tilt",
        }:
            known = get_latest_known_annual_financials_with_stale_replacement(
                financial_snapshots,
                rebalance_datetime,
                buy_date,
            )
            if config.scoring.formula in {
                "note_best_fit",
                "note_best_fit_plus_earnings",
                "note_best_fit_product",
                "note_best_fit_signed_sqrt_product",
                "note_best_fit_harmonic",
                "note_best_fit_soft_quality_tilt",
                "note_best_fit_x1_quality_tilt",
                "note_best_fit_x2_quality_tilt",
            } and not known.empty:
                known = _attach_note_best_fit_growth_inputs(known, financial_snapshots, rebalance_datetime, buy_date)
        else:
            known = get_latest_known_financials(financial_snapshots, rebalance_datetime, buy_date)
        universe = get_universe_for_date(universe_membership, config.universe.name, buy_date)
        candidates = known[known["symbol"].isin(universe)].copy()
        candidates = _attach_universe_metadata(candidates, universe_membership, config.universe.name, buy_date)
        effective_top_n = _resolve_effective_top_n(config, feature_prices, universe, buy_date)
        if candidates.empty:
            selected = candidates
        else:
            candidates = attach_avg_turnover_20d(candidates, feature_prices, buy_date)
            candidates = attach_recent_return_20d(candidates, feature_prices, buy_date)
            candidates = attach_recent_return_60d(candidates, feature_prices, buy_date)
            candidates = attach_market_cap_firm_value(candidates, feature_prices, rebalance_datetime)
            candidates = calculate_scores(candidates, config.scoring)
            candidates = _apply_x1_soft_penalty_rule(candidates, config)
            candidates = _apply_earnings_quality_soft_penalty_rule(candidates, config)
            if collect_diagnostics:
                ranked_all = candidates.sort_values(["selection_score", "score"], ascending=False).reset_index(drop=True)
                ranked_all["month"] = month
                ranked_all["rebalance_datetime"] = rebalance_datetime
                ranked_all["buy_date"] = buy_date
                ranked_all["sell_date"] = sell_date
                ranked_all["effective_top_n"] = effective_top_n
                ranked_all["provisional_rank"] = ranked_all.index + 1
                candidate_diagnostics.append(ranked_all)
            filter_settings = FilterSettings(**config.filters.model_dump())
            filtered, rejected = apply_filters(candidates, filter_settings)
            if collect_diagnostics:
                rejected["month"] = month
                rejected_candidates.append(rejected)
            ranked = filtered.sort_values(["selection_score", "score"], ascending=False)
            ranked = _apply_symbol_cooldown_exclusion_rule(
                ranked,
                config,
                month,
                cooldown_symbol_history,
            )
            selected = _apply_hold_buffer_rule(
                ranked,
                previous_held_symbols,
                effective_top_n,
                config.strategy.hold_buffer_rank,
            )
        positions = build_positions(
            selected,
            weighting=config.strategy.weighting,
            score_weight_cap=config.strategy.score_weight_cap,
        )
        positions = _apply_earnings_quality_weight_scaling_rule(positions, config)
        positions = _apply_technical_confirmation_rule(positions, config)
        _record_symbol_cooldown_history(
            cooldown_symbol_history,
            positions,
            prepared_prices,
            plan_month=month,
            buy_date=buy_date,
            sell_date=sell_date,
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
                if collect_diagnostics:
                    rejected_candidates.append(pd.DataFrame([position]).assign(month=plan["month"]))
                continue
            position.update(position_return)
            position_returns.append(position)

        positions_result = pd.DataFrame(position_returns)
        positions_result = _apply_symbol_cooldown_weight_scaling_rule(
            positions_result,
            config,
            plan["month"],
            realized_symbol_history,
        )
        if collect_diagnostics and not positions.empty:
            planned_snapshot = positions.copy()
            planned_snapshot["run_id"] = run_id
            planned_snapshot["month"] = plan["month"]
            planned_snapshot["rebalance_datetime"] = plan["rebalance_datetime"]
            planned_snapshot["buy_date"] = plan["buy_date"]
            planned_snapshot["sell_date"] = plan["sell_date"]
            planned_snapshot["used_period_end"] = planned_snapshot["period_end"]
            planned_snapshot["used_announcement_datetime"] = planned_snapshot.get("announcement_datetime")
            planned_positions.append(planned_snapshot)
        if positions_result.empty:
            gross_return = 0.0
            net_return = 0.0
            selected_symbols = ""
        else:
            gross_return = float((positions_result["weight"] * positions_result["gross_return"]).sum())
            net_return = float((positions_result["weight"] * positions_result["net_return"]).sum())
            selected_symbols = ",".join(positions_result["symbol"].tolist())
            month_period = pd.Period(plan["month"], freq="M")
            for row in positions_result[["symbol", "net_return"]].itertuples(index=False):
                symbol = str(row.symbol)
                history = realized_symbol_history.setdefault(symbol, [])
                history.append((month_period, float(row.net_return)))
            if collect_positions:
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
        "selected_positions": pd.concat(selected_positions, ignore_index=True) if collect_positions and selected_positions else pd.DataFrame(),
        "planned_positions": pd.concat(planned_positions, ignore_index=True) if collect_diagnostics and planned_positions else pd.DataFrame(),
        "rejected_candidates": pd.concat(rejected_candidates, ignore_index=True) if collect_diagnostics and rejected_candidates else pd.DataFrame(),
        "candidate_diagnostics": pd.concat(candidate_diagnostics, ignore_index=True) if collect_diagnostics and candidate_diagnostics else pd.DataFrame(),
    }


def _apply_rebalance_frequency(months: list[str], rebalance_frequency: str) -> list[str]:
    if not months:
        return months

    normalized = str(rebalance_frequency or "monthly").strip().lower()
    if normalized == "monthly":
        step = 1
    elif normalized in {"bimonthly", "every_2_months", "two_months"}:
        step = 2
    elif normalized in {"quarterly", "every_3_months", "three_months"}:
        step = 3
    else:
        step = 1
    return months[::step]


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
        return retained.sort_values(["selection_score", "score"], ascending=False).head(top_n)

    additions = ranked[~ranked["symbol"].astype(str).isin(retained["symbol"].astype(str))].head(remaining_slots)
    selected = pd.concat([retained, additions], ignore_index=True).drop_duplicates(subset=["symbol"])
    return selected.sort_values(["selection_score", "score"], ascending=False).head(top_n)


def _resolve_effective_top_n(
    config: BacktestConfig,
    prices: pd.DataFrame,
    universe: list[str],
    buy_date,
) -> int:
    base_top_n = config.strategy.top_n
    if (
        config.strategy.regime_filter_mode != "breadth_sma"
        or config.strategy.regime_filter_top_n is None
        or config.strategy.regime_filter_top_n >= base_top_n
    ):
        return base_top_n

    breadth = _calculate_universe_breadth_above_sma(
        prices=prices,
        symbols=universe,
        as_of_date=buy_date,
        lookback_days=config.strategy.regime_filter_lookback_days,
    )
    if breadth is None:
        return base_top_n
    if breadth < config.strategy.regime_filter_breadth_threshold:
        return config.strategy.regime_filter_top_n
    return base_top_n


def _apply_technical_confirmation_rule(
    positions: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    mode = config.strategy.technical_confirmation_mode
    if positions.empty or not mode:
        return positions
    if mode != "high_score_negative_momentum_veto":
        return positions

    rank_threshold = config.strategy.technical_confirmation_rank_threshold
    if rank_threshold is None or rank_threshold <= 0:
        return positions

    lookback_days = config.strategy.technical_confirmation_lookback_days
    if lookback_days == 20:
        return_column = "recent_return_20d"
    elif lookback_days == 60:
        return_column = "recent_return_60d"
    else:
        return positions
    if return_column not in positions.columns:
        return positions

    result = positions.copy()
    result["technical_score_rank"] = result["score"].rank(method="first", ascending=False).astype(int)
    veto_mask = (
        (result["technical_score_rank"] <= rank_threshold)
        & pd.to_numeric(result[return_column], errors="coerce").lt(
            config.strategy.technical_confirmation_return_threshold
        )
    )
    if not veto_mask.any():
        return result

    survivors = result[~veto_mask].copy()
    if survivors.empty:
        return survivors

    if config.strategy.technical_confirmation_redistribute:
        survivors["weight"] = survivors["weight"] / survivors["weight"].sum()

    return survivors


def _apply_symbol_cooldown_exclusion_rule(
    ranked: pd.DataFrame,
    config: BacktestConfig,
    month: str,
    cooldown_symbol_history: dict[str, list[tuple[pd.Period, float]]],
) -> pd.DataFrame:
    mode = config.strategy.symbol_cooldown_exclusion_mode
    if ranked.empty or not mode:
        return ranked
    if mode not in {
        "prior_high_return_same_symbol_exclude",
        "prior_high_return_x1_heavy_same_symbol_exclude",
    }:
        return ranked

    lookback_months = config.strategy.symbol_cooldown_exclusion_lookback_months
    return_threshold = config.strategy.symbol_cooldown_exclusion_return_threshold
    x1_share_threshold = config.strategy.symbol_cooldown_exclusion_x1_share_threshold
    if lookback_months <= 0:
        return ranked

    current_period = pd.Period(month, freq="M")
    exclude_mask = []
    for symbol in ranked["symbol"].astype(str):
        history = cooldown_symbol_history.get(symbol, [])
        normalized_history: list[tuple[pd.Period, float, float | None]] = []
        for item in history:
            if len(item) == 2:
                prior_period, prior_return = item
                normalized_history.append((prior_period, prior_return, None))
            else:
                prior_period, prior_return, prior_x1_share = item
                normalized_history.append((prior_period, prior_return, prior_x1_share))
        has_recent_high_return = any(
            0 < (current_period - prior_period).n <= lookback_months
            and prior_return >= return_threshold
            and (
                mode != "prior_high_return_x1_heavy_same_symbol_exclude"
                or x1_share_threshold is None
                or (prior_x1_share is not None and prior_x1_share >= x1_share_threshold)
            )
            for prior_period, prior_return, prior_x1_share in normalized_history
        )
        exclude_mask.append(has_recent_high_return)
    exclude_mask = pd.Series(exclude_mask, index=ranked.index)
    if not exclude_mask.any():
        return ranked

    return ranked.loc[~exclude_mask].copy()


def _apply_x1_soft_penalty_rule(
    candidates: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    mode = config.strategy.x1_soft_penalty_mode
    if candidates.empty or not mode:
        return candidates
    if mode != "x1_heavy_low_60d_penalty":
        return candidates

    share_threshold = config.strategy.x1_soft_penalty_share_threshold
    return_60d_threshold = config.strategy.x1_soft_penalty_return_60d_threshold
    penalty = config.strategy.x1_soft_penalty_amount
    if (
        share_threshold is None
        or return_60d_threshold is None
        or penalty <= 0
        or "recent_return_60d" not in candidates.columns
    ):
        return candidates

    result = candidates.copy()
    x_total = pd.to_numeric(result["x1"], errors="coerce") + pd.to_numeric(result["x2"], errors="coerce")
    x1_share = pd.to_numeric(result["x1"], errors="coerce") / x_total
    guard_mask = (
        x1_share.ge(share_threshold)
        & pd.to_numeric(result["recent_return_60d"], errors="coerce").lt(return_60d_threshold)
    )
    if not guard_mask.any():
        return result

    result.loc[guard_mask, "selection_score"] = (
        pd.to_numeric(result.loc[guard_mask, "selection_score"], errors="coerce") - penalty
    )
    return result


def _record_symbol_cooldown_history(
    cooldown_symbol_history: dict[str, list[tuple[pd.Period, float]]],
    positions: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    plan_month: str,
    buy_date,
    sell_date,
) -> None:
    if positions.empty:
        return
    month_period = pd.Period(plan_month, freq="M")
    for symbol in positions["symbol"].astype(str):
        position_return = calculate_position_return_open_to_open(
            prices,
            symbol,
            buy_date,
            sell_date,
            0.0,
            0.0,
        )
        if position_return is None:
            continue
        history = cooldown_symbol_history.setdefault(symbol, [])
        x1_value = pd.to_numeric(
            positions.loc[positions["symbol"].astype(str) == symbol, "x1"],
            errors="coerce",
        )
        x2_value = pd.to_numeric(
            positions.loc[positions["symbol"].astype(str) == symbol, "x2"],
            errors="coerce",
        )
        x1_share = None
        if not x1_value.empty and not x2_value.empty:
            denom = float(x1_value.iloc[0]) + float(x2_value.iloc[0])
            if denom != 0:
                x1_share = float(x1_value.iloc[0]) / denom
        history.append((month_period, float(position_return["gross_return"]), x1_share))


def _apply_earnings_quality_soft_penalty_rule(
    candidates: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    mode = config.strategy.earnings_quality_soft_penalty_mode
    if candidates.empty or not mode:
        return candidates
    if mode not in {
        "extreme_growth_or_accel_penalty",
        "extreme_growth_and_accel_penalty",
    }:
        return candidates

    max_growth = config.strategy.earnings_quality_max_ni_ttm_growth_yoy
    max_accel = config.strategy.earnings_quality_max_acceleration
    penalty = config.strategy.earnings_quality_soft_penalty_amount
    if penalty <= 0:
        return candidates

    result = candidates.copy()
    growth_mask = pd.Series(False, index=result.index)
    accel_mask = pd.Series(False, index=result.index)
    if max_growth is not None and "ni_ttm_growth_yoy" in result.columns:
        growth_mask = pd.to_numeric(result["ni_ttm_growth_yoy"], errors="coerce").gt(max_growth)
    if max_accel is not None and "earnings_acceleration" in result.columns:
        accel_mask = pd.to_numeric(result["earnings_acceleration"], errors="coerce").gt(max_accel)

    if mode == "extreme_growth_or_accel_penalty":
        penalty_mask = growth_mask | accel_mask
    else:
        penalty_mask = growth_mask & accel_mask

    if not penalty_mask.any():
        return result

    result.loc[penalty_mask, "selection_score"] = (
        pd.to_numeric(result.loc[penalty_mask, "selection_score"], errors="coerce") - penalty
    )
    return result


def _apply_earnings_quality_weight_scaling_rule(
    positions: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    mode = config.strategy.earnings_quality_weight_scale_mode
    if positions.empty or not mode:
        return positions
    if mode not in {
        "extreme_growth_and_accel_scale",
        "extreme_growth_or_accel_scale",
    }:
        return positions

    max_growth = config.strategy.earnings_quality_max_ni_ttm_growth_yoy
    max_accel = config.strategy.earnings_quality_max_acceleration
    scale_factor = config.strategy.earnings_quality_weight_scale_factor
    if scale_factor <= 0 or scale_factor >= 1:
        return positions

    result = positions.copy()
    growth_mask = pd.Series(False, index=result.index)
    accel_mask = pd.Series(False, index=result.index)
    if max_growth is not None and "ni_ttm_growth_yoy" in result.columns:
        growth_mask = pd.to_numeric(result["ni_ttm_growth_yoy"], errors="coerce").gt(max_growth)
    if max_accel is not None and "earnings_acceleration" in result.columns:
        accel_mask = pd.to_numeric(result["earnings_acceleration"], errors="coerce").gt(max_accel)

    if mode == "extreme_growth_or_accel_scale":
        scale_mask = growth_mask | accel_mask
    else:
        scale_mask = growth_mask & accel_mask

    if not scale_mask.any():
        return result

    result.loc[scale_mask, "weight"] = pd.to_numeric(result.loc[scale_mask, "weight"], errors="coerce") * scale_factor
    total_weight = pd.to_numeric(result["weight"], errors="coerce").sum()
    if total_weight > 0:
        result["weight"] = pd.to_numeric(result["weight"], errors="coerce") / total_weight
    return result


def _apply_symbol_cooldown_weight_scaling_rule(
    positions: pd.DataFrame,
    config: BacktestConfig,
    month: str,
    realized_symbol_history: dict[str, list[tuple[pd.Period, float]]],
) -> pd.DataFrame:
    mode = config.strategy.symbol_cooldown_weight_scale_mode
    if positions.empty or not mode:
        return positions
    if mode != "prior_negative_same_symbol_scale":
        return positions

    lookback_months = config.strategy.symbol_cooldown_lookback_months
    negative_threshold = config.strategy.symbol_cooldown_negative_return_threshold
    scale_factor = config.strategy.symbol_cooldown_weight_scale_factor
    if lookback_months <= 0 or scale_factor <= 0 or scale_factor >= 1:
        return positions

    current_period = pd.Period(month, freq="M")
    result = positions.copy()
    scale_mask = []
    for symbol in result["symbol"].astype(str):
        history = realized_symbol_history.get(symbol, [])
        has_recent_negative = any(
            0 < (current_period - prior_period).n <= lookback_months and prior_return < negative_threshold
            for prior_period, prior_return in history
        )
        scale_mask.append(has_recent_negative)
    scale_mask = pd.Series(scale_mask, index=result.index)
    if not scale_mask.any():
        return result

    result.loc[scale_mask, "weight"] = pd.to_numeric(result.loc[scale_mask, "weight"], errors="coerce") * scale_factor
    total_weight = pd.to_numeric(result["weight"], errors="coerce").sum()
    if total_weight > 0:
        result["weight"] = pd.to_numeric(result["weight"], errors="coerce") / total_weight
    return result


def _calculate_universe_breadth_above_sma(
    prices: pd.DataFrame,
    symbols: list[str],
    as_of_date,
    lookback_days: int,
) -> float | None:
    if lookback_days <= 1 or not symbols:
        return None
    universe_prices = prices[prices["symbol"].isin(symbols)].copy()
    if universe_prices.empty:
        return None
    universe_prices = universe_prices[universe_prices["date"] < as_of_date].copy()
    if universe_prices.empty:
        return None
    universe_prices = universe_prices.sort_values(["symbol", "date"])
    close_col = "adjusted_close" if "adjusted_close" in universe_prices.columns else "close"
    universe_prices["sma"] = (
        universe_prices.groupby("symbol")[close_col]
        .transform(lambda s: s.rolling(lookback_days, min_periods=lookback_days).mean())
    )
    latest = universe_prices.groupby("symbol", as_index=False).tail(1)
    latest = latest[latest["sma"].notna()].copy()
    if latest.empty:
        return None
    return float((latest[close_col] > latest["sma"]).mean())


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
    previous_year_ttm = known[
        [
            "symbol",
            "fiscal_year",
            "fiscal_quarter",
            "net_income_ttm",
            "operating_profit_ttm",
            "net_income_growth",
        ]
    ].copy()
    previous_year_ttm["fiscal_year"] = previous_year_ttm["fiscal_year"] + 1
    previous_year_ttm = previous_year_ttm.rename(
        columns={
            "net_income_ttm": "previous_year_net_income_ttm",
            "operating_profit_ttm": "previous_year_operating_profit_ttm",
            "net_income_growth": "previous_year_net_income_growth",
        }
    )
    latest = latest.merge(previous_same_quarter, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    latest = latest.merge(previous_year_ttm, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")
    latest = latest.rename(columns={"net_income": "latest_cum_net_income"})
    latest["ni_ttm_growth_yoy"] = (
        pd.to_numeric(latest.get("net_income_ttm"), errors="coerce")
        - pd.to_numeric(latest.get("previous_year_net_income_ttm"), errors="coerce")
    ) / pd.to_numeric(latest.get("previous_year_net_income_ttm"), errors="coerce")
    latest["op_ttm_growth_yoy"] = (
        pd.to_numeric(latest.get("operating_profit_ttm"), errors="coerce")
        - pd.to_numeric(latest.get("previous_year_operating_profit_ttm"), errors="coerce")
    ) / pd.to_numeric(latest.get("previous_year_operating_profit_ttm"), errors="coerce")
    latest["earnings_acceleration"] = (
        pd.to_numeric(latest.get("net_income_growth"), errors="coerce")
        - pd.to_numeric(latest.get("previous_year_net_income_growth"), errors="coerce")
    )

    annual_known = annual_known.drop(
        columns=[
            "ni_ttm_growth_yoy",
            "op_ttm_growth_yoy",
            "earnings_acceleration",
        ],
        errors="ignore",
    )
    enriched = annual_known.merge(
        latest[
            [
                "symbol",
                "latest_cum_net_income",
                "previous_same_quarter_cum_net_income",
                "ni_ttm_growth_yoy",
                "op_ttm_growth_yoy",
                "earnings_acceleration",
            ]
        ],
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

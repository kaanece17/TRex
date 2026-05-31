from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pandas as pd

from bist_factor_backtest.factors.analyst_signals import attach_latest_analyst_snapshot
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
from bist_factor_backtest.factors.liquidity import (
    attach_avg_turnover_20d,
    attach_recent_return_20d,
    attach_recent_return_60d,
)
from bist_factor_backtest.factors.pit_signals import (
    attach_announcement_age_days,
    attach_announcement_drift_return,
)
from bist_factor_backtest.factors.scoring import calculate_scores


def run_monthly_rotation_backtest(
    config: BacktestConfig,
    prices: pd.DataFrame,
    financial_snapshots: pd.DataFrame,
    universe_membership: pd.DataFrame,
    analyst_snapshots: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | str]:
    run_id = str(uuid4())
    prepared_prices = prices.copy()
    prepared_prices["date"] = pd.to_datetime(prepared_prices["date"]).dt.date
    feature_prices = prepared_prices
    known_symbols = set(financial_snapshots["symbol"].dropna().astype(str).unique())
    if config.strategy.qqq_regime_weight_scale_mode:
        known_symbols.add("QQQ")
    if config.strategy.marketbox_risk_on_filter_mode:
        known_symbols.update({str(config.strategy.marketbox_risk_on_symbol or "XLK"), "SPY", "BTC-USD", "GC=F"})
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
        effective_top_n = _resolve_effective_top_n(config, feature_prices, universe, buy_date)
        if candidates.empty:
            selected = candidates
        else:
            candidates = attach_avg_turnover_20d(candidates, feature_prices, buy_date)
            candidates = attach_recent_return_20d(candidates, feature_prices, buy_date)
            candidates = attach_recent_return_60d(candidates, feature_prices, buy_date)
            candidates = attach_announcement_age_days(candidates, buy_date)
            candidates = attach_announcement_drift_return(
                candidates,
                feature_prices,
                buy_date,
                lookback_days=config.scoring.announcement_drift_lookback_days,
            )
            if analyst_snapshots is not None and not analyst_snapshots.empty:
                candidates = attach_latest_analyst_snapshot(candidates, analyst_snapshots, buy_date)
            candidates = attach_market_cap_firm_value(candidates, feature_prices, rebalance_datetime)
            candidates = calculate_scores(candidates, config.scoring)
            candidates = _apply_x1_soft_penalty_rule(candidates, config)
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
            rejected["month"] = month
            rejected_candidates.append(rejected)
            ranked = filtered.sort_values(["selection_score", "score"], ascending=False)
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
        positions = _apply_technical_confirmation_rule(positions, config)
        positions = _apply_position_quality_guard_rule(positions, config)
        positions = _apply_marketbox_risk_on_filter_rule(
            positions,
            config,
            buy_date,
            calendar_prices,
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
        positions = _apply_qqq_regime_weight_scaling_rule(
            positions,
            config,
            plan["buy_date"],
            calendar_prices,
        )
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
        positions_result = _apply_dynamic_repeater_weight_scaling_rule(
            positions_result,
            config,
            plan["month"],
            realized_symbol_history,
        )
        if not positions.empty:
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
                history = realized_symbol_history.setdefault(str(row.symbol), [])
                history.append((month_period, float(row.net_return)))
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
        "planned_positions": pd.concat(planned_positions, ignore_index=True) if planned_positions else pd.DataFrame(),
        "rejected_candidates": pd.concat(rejected_candidates, ignore_index=True) if rejected_candidates else pd.DataFrame(),
        "candidate_diagnostics": pd.concat(candidate_diagnostics, ignore_index=True) if candidate_diagnostics else pd.DataFrame(),
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


def _apply_position_quality_guard_rule(
    positions: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    mode = config.strategy.position_quality_guard_mode
    if positions.empty or not mode:
        return positions
    if mode != "symbol_group_negative_60d_cash_veto":
        return positions
    if "recent_return_60d" not in positions.columns:
        return positions

    guard_symbols = {str(symbol).upper() for symbol in config.strategy.position_quality_guard_symbols}
    if not guard_symbols:
        return positions

    result = positions.copy()
    return_60d = pd.to_numeric(result["recent_return_60d"], errors="coerce")
    symbol = result["symbol"].astype(str).str.upper()
    veto_mask = symbol.isin(guard_symbols) & return_60d.lt(
        config.strategy.position_quality_guard_return_60d_threshold
    )
    if not veto_mask.any():
        return result

    survivors = result[~veto_mask].copy()
    if survivors.empty:
        return survivors

    if config.strategy.position_quality_guard_redistribute:
        total_weight = pd.to_numeric(survivors["weight"], errors="coerce").sum()
        if total_weight > 0:
            survivors["weight"] = pd.to_numeric(survivors["weight"], errors="coerce") / total_weight

    return survivors


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


def _apply_dynamic_repeater_weight_scaling_rule(
    positions: pd.DataFrame,
    config: BacktestConfig,
    month: str,
    realized_symbol_history: dict[str, list[tuple[pd.Period, float]]],
) -> pd.DataFrame:
    mode = config.strategy.dynamic_repeater_weight_scale_mode
    if positions.empty or not mode:
        return positions
    if mode != "recent_negative_repeaters_scale":
        return positions

    lookback_months = config.strategy.dynamic_repeater_lookback_months
    min_negative_hits = config.strategy.dynamic_repeater_min_negative_hits
    scale_factor = config.strategy.dynamic_repeater_weight_scale_factor
    if lookback_months <= 0 or min_negative_hits <= 0 or scale_factor <= 0 or scale_factor >= 1:
        return positions

    current_period = pd.Period(month, freq="M")
    result = positions.copy()
    flagged_symbols: set[str] = set()
    for symbol in result["symbol"].astype(str):
        history = realized_symbol_history.get(symbol, [])
        recent = [
            prior_return
            for prior_period, prior_return in history
            if 0 < (current_period - prior_period).n <= lookback_months
        ]
        if not recent:
            continue
        negative_hits = sum(1 for prior_return in recent if prior_return < 0)
        avg_recent = sum(recent) / len(recent)
        if negative_hits >= min_negative_hits and avg_recent < 0:
            flagged_symbols.add(symbol)

    if len(flagged_symbols) < 2:
        return result

    scale_mask = result["symbol"].astype(str).isin(flagged_symbols)
    if not scale_mask.any():
        return result

    result.loc[scale_mask, "weight"] = pd.to_numeric(result.loc[scale_mask, "weight"], errors="coerce") * scale_factor
    total_weight = pd.to_numeric(result["weight"], errors="coerce").sum()
    if total_weight > 0:
        result["weight"] = pd.to_numeric(result["weight"], errors="coerce") / total_weight
    return result


def _apply_qqq_regime_weight_scaling_rule(
    positions: pd.DataFrame,
    config: BacktestConfig,
    buy_date,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    mode = config.strategy.qqq_regime_weight_scale_mode
    if positions.empty or not mode:
        return positions
    if mode not in {"below_200dma_scale", "below_200dma_and_negative_60d_scale"}:
        return positions

    scale_factor = config.strategy.qqq_regime_scale_factor
    if scale_factor <= 0 or scale_factor >= 1:
        return positions

    qqq = prices[prices["symbol"].astype(str) == "QQQ"].copy()
    if qqq.empty:
        return positions
    qqq["date"] = pd.to_datetime(qqq["date"]).dt.date
    qqq = qqq[qqq["date"] < buy_date].sort_values("date").copy()
    if qqq.empty:
        return positions

    lookback_days = config.strategy.qqq_regime_sma_lookback_days
    close_col = "adjusted_close" if "adjusted_close" in qqq.columns else "close"
    qqq["sma"] = qqq[close_col].rolling(lookback_days, min_periods=lookback_days).mean()

    latest = qqq.iloc[-1]
    below_200dma = bool(pd.notna(latest["sma"]) and latest[close_col] < latest["sma"])
    if not below_200dma:
        return positions

    if mode == "below_200dma_and_negative_60d_scale":
        return_lookback_days = config.strategy.qqq_regime_return_lookback_days
        qqq["ret"] = qqq[close_col] / qqq[close_col].shift(return_lookback_days) - 1
        latest = qqq.iloc[-1]
        if not (pd.notna(latest["ret"]) and latest["ret"] < 0):
            return positions

    result = positions.copy()
    result["weight"] = pd.to_numeric(result["weight"], errors="coerce") * scale_factor
    return result


def _apply_marketbox_risk_on_filter_rule(
    positions: pd.DataFrame,
    config: BacktestConfig,
    buy_date,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    mode = config.strategy.marketbox_risk_on_filter_mode
    if positions.empty or not mode:
        return positions
    if str(mode) not in {"xlk_risk_on_only", "xlk_risk_on_score"}:
        return positions

    snapshot = _calculate_marketbox_risk_on_snapshot(
        prices=prices,
        buy_date=buy_date,
        symbol=str(config.strategy.marketbox_risk_on_symbol or "XLK"),
        min_score=float(config.strategy.marketbox_risk_on_min_score),
        stage_conf=float(config.strategy.marketbox_risk_on_stage_confidence),
    )
    if bool(snapshot.get("risk_on")):
        return positions
    return positions.iloc[0:0].copy()


def _calculate_marketbox_risk_on_snapshot(
    *,
    prices: pd.DataFrame,
    buy_date,
    symbol: str = "XLK",
    min_score: float = 0.50,
    stage_conf: float = 1.0,
) -> dict[str, object]:
    score = _calculate_marketbox_risk_on_score(prices, buy_date, symbol=symbol, stage_conf=stage_conf)
    return {
        "symbol": symbol,
        "buy_date": buy_date,
        "risk_on": bool(score is not None and score >= min_score),
        "asset_score_risk_on": score,
        "min_score": float(min_score),
    }


def _calculate_marketbox_risk_on_score(
    prices: pd.DataFrame,
    buy_date,
    *,
    symbol: str = "XLK",
    stage_conf: float = 1.0,
) -> float | None:
    asset = _marketbox_symbol_prices(prices, symbol, buy_date)
    spy = _marketbox_symbol_prices(prices, "SPY", buy_date)
    btc = _marketbox_symbol_prices(prices, "BTC-USD", buy_date)
    gold = _marketbox_symbol_prices(prices, "GC=F", buy_date)
    if asset.empty or spy.empty or btc.empty or gold.empty:
        return None

    flow_score = _marketbox_money_flow_score(asset)
    rs_score = _clip01(((_marketbox_rs_slope(asset, spy) + _marketbox_rs_slope(asset, btc) + _marketbox_rs_slope(asset, gold)) / 3.0) * 100.0 + 0.5)
    vol_penalty = _marketbox_vol_penalty(asset)
    trend_score = _marketbox_trend_score(asset)
    composite = (0.35 * flow_score) + (0.30 * rs_score) - (0.20 * vol_penalty) + (0.35 * trend_score)
    return _clip01(float(stage_conf) * _clip01(composite))


def _marketbox_symbol_prices(prices: pd.DataFrame, symbol: str, buy_date) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    frame = prices[prices["symbol"].astype(str) == str(symbol)].copy()
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame = frame[frame["date"].notna()].copy()
    buy_day = pd.to_datetime(buy_date, errors="coerce")
    if pd.isna(buy_day):
        return pd.DataFrame()
    frame = frame[frame["date"] < buy_day.date()].sort_values("date").copy()
    close_col = "adjusted_close" if "adjusted_close" in frame.columns else "close"
    frame["mb_close"] = pd.to_numeric(frame[close_col], errors="coerce")
    frame["mb_volume"] = pd.to_numeric(frame.get("volume", 0.0), errors="coerce").fillna(0.0)
    return frame.dropna(subset=["mb_close"])


def _marketbox_money_flow_score(asset: pd.DataFrame) -> float:
    close = asset["mb_close"].astype(float)
    volume = asset["mb_volume"].astype(float)
    direction = np.sign(close.diff()).fillna(0.0)
    obv = (direction * volume).cumsum()
    obv_slope = _linreg_slope(obv.tail(63), min_points=20)
    volume_sma = float(volume.tail(63).mean()) if len(volume.tail(63)) else 0.0
    obv_norm = 0.0 if obv_slope is None or volume_sma == 0 else float(obv_slope) / volume_sma

    up_volume = volume.where(close.diff() > 0, 0.0)
    down_volume = volume.where(close.diff() < 0, 0.0)
    up_sum = float(up_volume.tail(21).sum())
    down_sum = float(down_volume.tail(21).sum())
    if down_sum == 0.0 and up_sum > 0.0:
        up_down_ratio = 10.0
    elif down_sum == 0.0:
        up_down_ratio = 0.0
    else:
        up_down_ratio = min(max(up_sum / down_sum, 0.0), 10.0)

    returns = close.pct_change()
    volume_mean = volume.rolling(21).mean()
    volume_std = volume.rolling(21).std()
    volume_z = (volume - volume_mean) / volume_std.replace(0.0, np.nan)
    impact = returns.tail(21).corr(volume_z.tail(21))
    impact = 0.0 if pd.isna(impact) else float(impact)

    obv_component = _clip01((obv_norm * 20.0 + 1.0) / 2.0)
    ratio_component = _clip01(up_down_ratio / 2.0)
    impact_component = _clip01((impact + 1.0) / 2.0)
    return _clip01((0.4 * obv_component) + (0.4 * ratio_component) + (0.2 * impact_component))


def _marketbox_rs_slope(asset: pd.DataFrame, anchor: pd.DataFrame) -> float:
    merged = asset[["date", "mb_close"]].merge(
        anchor[["date", "mb_close"]],
        on="date",
        how="inner",
        suffixes=("_asset", "_anchor"),
    )
    merged = merged[(merged["mb_close_asset"] > 0) & (merged["mb_close_anchor"] > 0)].copy()
    if merged.empty:
        return 0.0
    log_ratio = np.log(merged["mb_close_asset"] / merged["mb_close_anchor"])
    slope = _linreg_slope(log_ratio.tail(63), min_points=20)
    return 0.0 if slope is None else float(slope)


def _marketbox_vol_penalty(asset: pd.DataFrame) -> float:
    close = asset["mb_close"].astype(float)
    returns = close.pct_change()
    rv_21_daily = returns.rolling(21).std()
    rv_21 = float(rv_21_daily.iloc[-1] * np.sqrt(252.0)) if len(rv_21_daily) and pd.notna(rv_21_daily.iloc[-1]) else 0.0
    downside = returns.where(returns < 0.0, 0.0)
    downside_vol = float(downside.rolling(21).std().iloc[-1] * np.sqrt(252.0)) if len(downside) >= 21 else 0.0
    jump_mask = returns.abs() > (2.0 * rv_21_daily)
    jump_rate = float(jump_mask.tail(63).mean()) if len(jump_mask.tail(63)) else 0.0
    return _clip01((rv_21 * 2.0) + downside_vol + jump_rate)


def _marketbox_trend_score(asset: pd.DataFrame) -> float:
    close = asset["mb_close"].astype(float)
    latest = float(close.iloc[-1]) if not close.empty else 0.0
    sma50 = float(close.tail(50).mean()) if len(close) >= 50 else np.nan
    sma200 = float(close.tail(200).mean()) if len(close) >= 200 else np.nan
    close_sma50 = 0.0 if pd.isna(sma50) or sma50 == 0 else (latest / sma50) - 1.0
    close_sma200 = 0.0 if pd.isna(sma200) or sma200 == 0 else (latest / sma200) - 1.0
    log_close = np.log(close[close > 0])
    slope = _linreg_slope(log_close.tail(63), min_points=20)
    trend_log_slope_63 = 0.0 if slope is None else float(slope)
    return _clip01(
        0.35 * ((close_sma50 + 1.0) / 2.0)
        + 0.35 * ((close_sma200 + 1.0) / 2.0)
        + 0.30 * (trend_log_slope_63 * 100.0 + 0.5)
    )


def _linreg_slope(values, *, min_points: int) -> float | None:
    series = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < min_points:
        return None
    x = np.arange(len(series), dtype=float)
    return float(np.polyfit(x, series.to_numpy(dtype=float), 1)[0])


def _clip01(value: float) -> float:
    if pd.isna(value):
        return 0.0
    return float(np.clip(float(value), 0.0, 1.0))


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
    universe_prices["date"] = pd.to_datetime(universe_prices["date"], errors="coerce").dt.date
    universe_prices = universe_prices[universe_prices["date"].notna()].copy()
    if universe_prices.empty:
        return None
    as_of_date = pd.to_datetime(as_of_date, errors="coerce")
    if pd.isna(as_of_date):
        return None
    as_of_date = as_of_date.date()
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

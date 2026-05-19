from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.execution import calculate_position_return_open_to_open
from bist_factor_backtest.backtest.monthly_rotation import (
    _attach_note_best_fit_growth_inputs,
    _attach_universe_metadata,
    _resolve_sell_date,
)
from bist_factor_backtest.backtest.portfolio import build_positions
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.calendar import get_backtest_months, get_market_open_datetime
from bist_factor_backtest.data.point_in_time import get_latest_known_annual_financials, get_latest_known_financials
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.data.universe import get_universe_for_date
from bist_factor_backtest.factors.filters import FilterSettings, apply_filters
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value
from bist_factor_backtest.factors.liquidity import (
    attach_avg_turnover_20d,
    attach_recent_return_20d,
    attach_recent_return_60d,
)
from bist_factor_backtest.factors.scoring import calculate_scores


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.formula_research_momentum.yaml"
OUTPUT_DIR = ROOT / "outputs/formula_research_reference"


def run_variant(
    config: BacktestConfig,
    prices: pd.DataFrame,
    financial_snapshots: pd.DataFrame,
    universe_membership: pd.DataFrame,
    top_n_override: int | None,
    x1_share_threshold: float | None,
    ret60_threshold: float | None,
    penalty: float | None,
) -> dict[str, object]:
    prepared_prices = prices.copy()
    prepared_prices["date"] = pd.to_datetime(prepared_prices["date"]).dt.date
    feature_prices = prepared_prices
    known_symbols = set(financial_snapshots["symbol"].dropna().astype(str).unique())
    if known_symbols:
        feature_prices = prepared_prices[prepared_prices["symbol"].isin(known_symbols)].copy()
    months = get_backtest_months(feature_prices, config.backtest.start_date, config.backtest.end_date)

    selection_plan: list[dict] = []
    portfolio_value = config.backtest.initial_capital
    monthly_rows: list[dict[str, object]] = []

    for month_index, month in enumerate(months):
        buy_date = feature_prices[feature_prices["date"].astype(str).str.startswith(month)].sort_values("date")["date"].iloc[0]
        sell_date = _resolve_sell_date(feature_prices, months, month_index, month, config.strategy.execution_mode)
        rebalance_datetime = get_market_open_datetime(buy_date, config.strategy.market_open_time, config.project.timezone)
        if config.scoring.formula in {"note_exact", "note_best_fit"}:
            known = get_latest_known_annual_financials(financial_snapshots, rebalance_datetime, buy_date)
            if config.scoring.formula == "note_best_fit" and not known.empty:
                known = _attach_note_best_fit_growth_inputs(known, financial_snapshots, rebalance_datetime, buy_date)
        else:
            known = get_latest_known_financials(financial_snapshots, rebalance_datetime, buy_date)

        universe = get_universe_for_date(universe_membership, config.universe.name, buy_date)
        candidates = known[known["symbol"].isin(universe)].copy()
        candidates = _attach_universe_metadata(candidates, universe_membership, config.universe.name, buy_date)
        if not candidates.empty:
            candidates = attach_avg_turnover_20d(candidates, feature_prices, buy_date)
            candidates = attach_recent_return_20d(candidates, feature_prices, buy_date)
            candidates = attach_recent_return_60d(candidates, feature_prices, buy_date)
            candidates = attach_market_cap_firm_value(candidates, feature_prices, rebalance_datetime)
            candidates = calculate_scores(candidates, config.scoring)
            filtered, _ = apply_filters(candidates, FilterSettings(**config.filters.model_dump()))
            ranked = filtered.sort_values(["selection_score", "score"], ascending=False).copy()
            if penalty is not None and not ranked.empty and x1_share_threshold is not None and ret60_threshold is not None:
                ranked["x_total"] = pd.to_numeric(ranked["x1"], errors="coerce") + pd.to_numeric(ranked["x2"], errors="coerce")
                ranked["x1_share"] = pd.to_numeric(ranked["x1"], errors="coerce") / ranked["x_total"]
                guard_mask = (
                    ranked["x1_share"].ge(x1_share_threshold)
                    & pd.to_numeric(ranked["recent_return_60d"], errors="coerce").lt(ret60_threshold)
                )
                ranked.loc[guard_mask, "selection_score"] = pd.to_numeric(
                    ranked.loc[guard_mask, "selection_score"], errors="coerce"
                ) - penalty
                ranked = ranked.sort_values(["selection_score", "score"], ascending=False).copy()
            top_n = top_n_override or config.strategy.top_n
            selected = ranked.head(top_n)
        else:
            selected = candidates

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
                prepared_prices,
                symbol,
                plan["buy_date"],
                plan["sell_date"],
                buy_commission_rate,
                sell_commission_rate,
            )
            if position_return is None:
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
        start_value = portfolio_value
        portfolio_value = portfolio_value * (1 + net_return)
        monthly_rows.append(
            {
                "month": plan["month"],
                "buy_date": plan["buy_date"],
                "sell_date": plan["sell_date"],
                "gross_return": gross_return,
                "net_return": net_return,
                "portfolio_value_start": start_value,
                "portfolio_value_end": portfolio_value,
                "selected_symbols": selected_symbols,
                "position_count": len(positions_result),
            }
        )

    monthly_df = pd.DataFrame(monthly_rows).sort_values("month").reset_index(drop=True)
    returns = pd.to_numeric(monthly_df["net_return"], errors="coerce")
    equity = pd.to_numeric(monthly_df["portfolio_value_end"], errors="coerce")
    drawdown = (equity / equity.cummax()) - 1
    recent = monthly_df[monthly_df["month"].astype(str) >= "2024-01"].copy()
    recent_multiple = (
        float(pd.to_numeric(recent["portfolio_value_end"], errors="coerce").iloc[-1])
        / float(pd.to_numeric(recent["portfolio_value_start"], errors="coerce").iloc[0])
        if not recent.empty
        else None
    )
    return {
        "variant": variant_name(top_n_override, x1_share_threshold, ret60_threshold, penalty),
        "top_n": top_n_override or config.strategy.top_n,
        "x1_share_threshold": x1_share_threshold,
        "ret60_threshold": ret60_threshold,
        "penalty": penalty,
        "final_multiple": float(equity.iloc[-1]) / float(monthly_df["portfolio_value_start"].iloc[0]),
        "win_rate": float((returns > 0).mean()),
        "max_drawdown": float(drawdown.min()),
        "negative_months": int((returns < 0).sum()),
        "multiple_2024_2026": recent_multiple,
        "avg_position_count": float(pd.to_numeric(monthly_df["position_count"], errors="coerce").mean()),
    }


def variant_name(top_n: int | None, x1_share: float | None, ret60: float | None, penalty: float | None) -> str:
    if penalty is None:
        return f"base_top{top_n or 5}"
    return f"top{top_n}_x1_{int((x1_share or 0)*100)}_r60_{int((ret60 or 0)*100)}_pen_{int(penalty*100)}"


def write_readout(summary: pd.DataFrame) -> None:
    best = summary.sort_values(["final_multiple", "max_drawdown"], ascending=[False, False]).iloc[0]
    lines = [
        "# Momentum Soft Penalty + TopN Grid",
        "",
        f"- En iyi varyant: `{best['variant']}`",
        f"- Multiple: `{best['final_multiple']:.2f}x`",
        f"- 2024-2026: `{best['multiple_2024_2026']:.2f}x`",
        f"- Max DD: `{best['max_drawdown']:.2%}`",
        "",
        "- Bu çalışma ana koda dokunmadan, gerçek aylık seçim akışı üstünde research rerun olarak çalıştırıldı.",
    ]
    (OUTPUT_DIR / "momentum_soft_penalty_topn_readout.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config(CONFIG_PATH)
    storage = DuckDbStorage(config.data.duckdb_path)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    membership = storage.read_table("universe_membership")
    storage.close()

    grid = [
        (5, None, None, None),
        (6, None, None, None),
        (7, None, None, None),
        (5, 0.80, 0.20, 0.10),
        (5, 0.80, 0.20, 0.20),
        (6, 0.80, 0.20, 0.10),
        (6, 0.80, 0.20, 0.20),
        (7, 0.80, 0.20, 0.10),
        (7, 0.80, 0.20, 0.20),
    ]
    rows = [
        run_variant(config, prices, financials, membership, top_n, x1_share, ret60, penalty)
        for top_n, x1_share, ret60, penalty in grid
    ]
    summary = pd.DataFrame(rows).sort_values("final_multiple", ascending=False)
    summary.to_csv(OUTPUT_DIR / "momentum_soft_penalty_topn_summary.csv", index=False)
    write_readout(summary)
    print((OUTPUT_DIR / "momentum_soft_penalty_topn_readout.md").as_posix())
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

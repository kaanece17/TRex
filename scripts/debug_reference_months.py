from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import _attach_universe_metadata
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.point_in_time import get_latest_known_financials
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.data.universe import get_universe_for_date, load_universe_membership
from bist_factor_backtest.factors.filters import FilterSettings, apply_filters
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value
from bist_factor_backtest.factors.liquidity import attach_avg_turnover_20d
from bist_factor_backtest.factors.scoring import calculate_scores


EXPECTED = {
    "2024-05": ["VESBE", "KLSYN", "BUCIM", "TTRAK", "BOBET"],
    "2024-06": ["VESBE", "BUCIM", "GENTS", "BRKSN", "BVSAN"],
}


def calculate_raw_scores(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    raw_growth = (result["net_income_ttm"] - result["previous_net_income_ttm"]) / result["previous_net_income_ttm"]
    result["raw_growth"] = raw_growth
    result["net_income_growth"] = raw_growth
    result["x1"] = (result["net_income_ttm"] / result["equity"]) * (1 + result["net_income_growth"])
    result["x2"] = result["operating_profit_ttm"] / result["firm_value"]
    result["score"] = result["x1"] + result["x2"]
    return result


def build_variant_rows(
    month: str,
    variant_name: str,
    scored: pd.DataFrame,
    filtered: pd.DataFrame,
    rejected: pd.DataFrame,
    expected_symbols: list[str],
) -> list[dict]:
    rows: list[dict] = []
    ranked = filtered.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(drop=True).copy()
    ranked["rank"] = ranked.index + 1
    for symbol in expected_symbols:
        base = scored[scored["symbol"] == symbol]
        if base.empty:
            rows.append(
                {
                    "month": month,
                    "variant": variant_name,
                    "symbol": symbol,
                    "status": "not_in_scored",
                }
            )
            continue
        item = base.iloc[0]
        rank_row = ranked[ranked["symbol"] == symbol]
        rejected_row = rejected[rejected["symbol"] == symbol]
        rows.append(
            {
                "month": month,
                "variant": variant_name,
                "symbol": symbol,
                "status": "ranked" if not rank_row.empty else "rejected",
                "rank": int(rank_row.iloc[0]["rank"]) if not rank_row.empty else None,
                "rejected_reason": rejected_row.iloc[0]["reason"] if not rejected_row.empty else None,
                "score": item.get("score"),
                "x1": item.get("x1"),
                "x2": item.get("x2"),
                "net_income_ttm": item.get("net_income_ttm"),
                "previous_net_income_ttm": item.get("previous_net_income_ttm"),
                "net_income_growth": item.get("net_income_growth"),
                "equity": item.get("equity"),
                "operating_profit_ttm": item.get("operating_profit_ttm"),
                "firm_value": item.get("firm_value"),
                "avg_turnover_20d": item.get("avg_turnover_20d"),
            }
        )
    top5 = ranked.head(5)
    for _, row in top5.iterrows():
        rows.append(
            {
                "month": month,
                "variant": variant_name,
                "symbol": str(row["symbol"]),
                "status": "top5",
                "rank": int(row["rank"]),
                "score": row.get("score"),
                "x1": row.get("x1"),
                "x2": row.get("x2"),
            }
        )
    return rows


def main() -> None:
    project_root = Path("/Users/kaanece/projects/TRex")
    settings = load_config(project_root / "config.no_fees.yaml")
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    snapshots = storage.read_table("financial_snapshots")
    prices = storage.read_table("market_prices")
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    membership = load_universe_membership(
        settings.universe.membership_file,
        settings.universe.symbol_aliases_file,
    )

    base_filters = FilterSettings(**settings.filters.model_dump())
    variants = [
        ("baseline", calculate_scores, base_filters),
        (
            "no_prev_ttm_filter",
            calculate_scores,
            replace(base_filters, require_positive_previous_net_income_ttm=False),
        ),
        (
            "no_prev_no_net_filter",
            calculate_scores,
            replace(
                base_filters,
                require_positive_previous_net_income_ttm=False,
                require_positive_net_income_ttm=False,
            ),
        ),
        (
            "raw_no_prev_filter",
            calculate_raw_scores,
            replace(base_filters, require_positive_previous_net_income_ttm=False),
        ),
        (
            "raw_no_prev_no_net_filter",
            calculate_raw_scores,
            replace(
                base_filters,
                require_positive_previous_net_income_ttm=False,
                require_positive_net_income_ttm=False,
            ),
        ),
    ]

    comparison_rows: list[dict] = []
    top_rows: list[dict] = []

    for month, expected_symbols in EXPECTED.items():
        buy_date = pd.Timestamp(prices.loc[prices["date"].astype(str).str.startswith(month), "date"].min()).date()
        rebalance_dt = pd.Timestamp(f"{buy_date} 10:00:00")
        known = get_latest_known_financials(snapshots, rebalance_dt, buy_date)
        universe = get_universe_for_date(membership, settings.universe.name, buy_date)
        candidates = known[known["symbol"].isin(universe)].copy()
        candidates = _attach_universe_metadata(candidates, membership, settings.universe.name, buy_date)
        candidates = attach_avg_turnover_20d(candidates, prices, buy_date)
        candidates = attach_market_cap_firm_value(candidates, prices, rebalance_dt)
        for variant_name, score_fn, filter_settings in variants:
            scored = score_fn(candidates)
            filtered, rejected = apply_filters(scored, filter_settings)
            comparison_rows.extend(
                build_variant_rows(
                    month=month,
                    variant_name=variant_name,
                    scored=scored,
                    filtered=filtered,
                    rejected=rejected,
                    expected_symbols=expected_symbols,
                )
            )
            ranked = filtered.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(drop=True).copy()
            ranked["rank"] = ranked.index + 1
            top = ranked.head(10).copy()
            top["month"] = month
            top["variant"] = variant_name
            top_rows.extend(top.to_dict(orient="records"))

    out_dir = project_root / "outputs" / "formula_research_reference"
    out_dir.mkdir(parents=True, exist_ok=True)
    comparison = pd.DataFrame(comparison_rows)
    tops = pd.DataFrame(top_rows)
    comparison.to_csv(out_dir / "reference_month_comparison.csv", index=False)
    tops.to_csv(out_dir / "reference_month_top10.csv", index=False)
    print(out_dir / "reference_month_comparison.csv")
    print(out_dir / "reference_month_top10.csv")


if __name__ == "__main__":
    main()

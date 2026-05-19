from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.point_in_time import (
    get_latest_known_annual_financials,
    get_latest_known_financials,
)
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.data.universe import get_universe_for_date, load_universe_membership
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value


EXPECTED = {
    "2024-05": ["VESBE", "KLSYN", "BUCIM", "TTRAK", "BOBET"],
    "2024-06": ["VESBE", "BUCIM", "GENTS", "BRKSN", "BVSAN"],
}

BASE_COLUMNS = [
    "symbol",
    "buy_date",
    "annual_period_end",
    "annual_announcement_date",
    "latest_period_end",
    "latest_announcement_date",
    "annual_net_income",
    "previous_annual_net_income",
    "equity",
    "annual_operating_profit",
    "firm_value",
    "shares_outstanding",
]

GROWTH_VARIANTS = [
    "annual_net_income_growth_signed",
    "annual_net_income_growth_abs_base",
    "latest_cum_net_income_growth_signed",
    "latest_cum_net_income_growth_abs_base",
    "latest_quarter_net_income_growth_signed",
    "latest_quarter_net_income_growth_abs_base",
    "annual_eps_growth_signed",
    "latest_quarter_eps_growth_signed",
    "annual_operating_profit_growth_signed",
    "latest_quarter_operating_profit_growth_signed",
]


def _safe_growth(current: pd.Series, previous: pd.Series, use_abs_base: bool = False) -> pd.Series:
    denominator = previous.abs() if use_abs_base else previous
    denominator = denominator.where(denominator != 0)
    return (current - previous) / denominator


def _rank_for_growth(data: pd.DataFrame, growth_column: str) -> pd.DataFrame:
    ranked = data.copy()
    ranked["x1_variant"] = (ranked["annual_net_income"] / ranked["equity"]) * (1 + ranked[growth_column])
    ranked["x2_variant"] = ranked["annual_operating_profit"] / ranked["firm_value"]
    ranked["score_variant"] = ranked["x1_variant"] + ranked["x2_variant"]
    ranked = ranked[
        ranked["equity"].notna()
        & ranked["firm_value"].notna()
        & (ranked["equity"] > 0)
        & (ranked["firm_value"] > 0)
        & ranked[growth_column].notna()
    ].copy()
    ranked = ranked.sort_values(["score_variant", "symbol"], ascending=[False, True]).reset_index(drop=True)
    ranked["rank"] = ranked.index + 1
    ranked["growth_variant"] = growth_column
    return ranked


def _build_month_dataset(
    snapshots: pd.DataFrame,
    prices: pd.DataFrame,
    membership,
    universe_name: str,
    month: str,
) -> pd.DataFrame:
    buy_date = pd.Timestamp(prices.loc[prices["date"].astype(str).str.startswith(month), "date"].min()).date()
    rebalance_dt = pd.Timestamp(f"{buy_date} 10:00:00")
    universe = get_universe_for_date(membership, universe_name, buy_date)

    annual = get_latest_known_annual_financials(snapshots, rebalance_dt, buy_date)
    latest = get_latest_known_financials(snapshots, rebalance_dt, buy_date)

    annual = annual[annual["symbol"].isin(universe)].copy()
    latest = latest[latest["symbol"].isin(universe)].copy()
    annual = attach_market_cap_firm_value(annual, prices, rebalance_dt)

    known = snapshots.copy()
    known["announcement_datetime"] = pd.to_datetime(known["announcement_datetime"], errors="coerce")
    if pd.api.types.is_datetime64tz_dtype(known["announcement_datetime"]):
        known["announcement_datetime"] = known["announcement_datetime"].dt.tz_localize(None)
    known["announcement_date"] = pd.to_datetime(known["announcement_date"], errors="coerce").dt.date
    cutoff = rebalance_dt
    first_trading_day = buy_date
    known_dt = known[known["announcement_datetime"].notna() & (known["announcement_datetime"] <= cutoff)]
    known_date = known[
        known["announcement_datetime"].isna()
        & known["announcement_date"].notna()
        & (known["announcement_date"] < first_trading_day)
    ]
    known = pd.concat([known_dt, known_date], ignore_index=True)

    previous_quarter = known[
        [
            "symbol",
            "fiscal_year",
            "fiscal_quarter",
            "net_income",
            "quarterly_net_income",
            "operating_profit",
            "quarterly_operating_profit",
            "shares_outstanding",
        ]
    ].copy()
    previous_quarter["fiscal_year"] = previous_quarter["fiscal_year"] + 1
    previous_quarter = previous_quarter.rename(
        columns={
            "net_income": "previous_same_quarter_cum_net_income",
            "quarterly_net_income": "previous_same_quarter_quarterly_net_income",
            "operating_profit": "previous_same_quarter_cum_operating_profit",
            "quarterly_operating_profit": "previous_same_quarter_quarterly_operating_profit",
            "shares_outstanding": "previous_same_quarter_shares_outstanding",
        }
    )

    latest = latest.merge(previous_quarter, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")

    dataset = annual.merge(
        latest[
            [
                "symbol",
                "period_end",
                "announcement_date",
                "fiscal_year",
                "fiscal_quarter",
                "net_income",
                "quarterly_net_income",
                "operating_profit",
                "quarterly_operating_profit",
                "shares_outstanding",
                "previous_same_quarter_cum_net_income",
                "previous_same_quarter_quarterly_net_income",
                "previous_same_quarter_cum_operating_profit",
                "previous_same_quarter_quarterly_operating_profit",
                "previous_same_quarter_shares_outstanding",
            ]
        ].rename(
            columns={
                "period_end": "latest_period_end",
                "announcement_date": "latest_announcement_date",
                "net_income": "latest_cum_net_income",
                "quarterly_net_income": "latest_quarter_net_income",
                "operating_profit": "latest_cum_operating_profit",
                "quarterly_operating_profit": "latest_quarter_operating_profit",
                "shares_outstanding": "latest_shares_outstanding",
            }
        ),
        on=["symbol", "fiscal_year", "fiscal_quarter"],
        how="left",
    )

    dataset = dataset.rename(
        columns={
            "period_end": "annual_period_end",
            "announcement_date": "annual_announcement_date",
            "net_income": "annual_net_income",
            "previous_annual_net_income": "previous_annual_net_income",
            "operating_profit": "annual_operating_profit",
        }
    )
    dataset["buy_date"] = buy_date

    dataset["annual_net_income_growth_signed"] = _safe_growth(
        dataset["annual_net_income"], dataset["previous_annual_net_income"]
    )
    dataset["annual_net_income_growth_abs_base"] = _safe_growth(
        dataset["annual_net_income"], dataset["previous_annual_net_income"], use_abs_base=True
    )
    dataset["latest_cum_net_income_growth_signed"] = _safe_growth(
        dataset["latest_cum_net_income"], dataset["previous_same_quarter_cum_net_income"]
    )
    dataset["latest_cum_net_income_growth_abs_base"] = _safe_growth(
        dataset["latest_cum_net_income"], dataset["previous_same_quarter_cum_net_income"], use_abs_base=True
    )
    dataset["latest_quarter_net_income_growth_signed"] = _safe_growth(
        dataset["latest_quarter_net_income"], dataset["previous_same_quarter_quarterly_net_income"]
    )
    dataset["latest_quarter_net_income_growth_abs_base"] = _safe_growth(
        dataset["latest_quarter_net_income"], dataset["previous_same_quarter_quarterly_net_income"], use_abs_base=True
    )

    annual_eps = dataset["annual_net_income"] / dataset["shares_outstanding"]
    previous_annual_eps = dataset["previous_annual_net_income"] / dataset["shares_outstanding"]
    latest_quarter_eps = dataset["latest_quarter_net_income"] / dataset["latest_shares_outstanding"]
    previous_quarter_eps = (
        dataset["previous_same_quarter_quarterly_net_income"] / dataset["previous_same_quarter_shares_outstanding"]
    )
    dataset["annual_eps_growth_signed"] = _safe_growth(annual_eps, previous_annual_eps)
    dataset["latest_quarter_eps_growth_signed"] = _safe_growth(latest_quarter_eps, previous_quarter_eps)

    dataset["annual_operating_profit_growth_signed"] = _safe_growth(
        dataset["annual_operating_profit"], dataset["previous_annual_operating_profit"]
    )
    dataset["latest_quarter_operating_profit_growth_signed"] = _safe_growth(
        dataset["latest_quarter_operating_profit"], dataset["previous_same_quarter_quarterly_operating_profit"]
    )

    return dataset


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

    expected_rows: list[dict] = []
    rank_rows: list[dict] = []
    top_rows: list[dict] = []

    for month, expected_symbols in EXPECTED.items():
        dataset = _build_month_dataset(snapshots, prices, membership, settings.universe.name, month)

        for growth_variant in GROWTH_VARIANTS:
            ranked = _rank_for_growth(dataset, growth_variant)
            top_rows.extend(
                ranked.head(10)[["symbol", "rank", "score_variant", "x1_variant", "x2_variant"]]
                .assign(month=month, growth_variant=growth_variant)
                .to_dict(orient="records")
            )
            expected_ranked = ranked[ranked["symbol"].isin(expected_symbols)][
                ["symbol", "rank", "score_variant", "x1_variant", "x2_variant"]
            ].copy()
            expected_ranked["month"] = month
            expected_ranked["growth_variant"] = growth_variant
            rank_rows.extend(expected_ranked.to_dict(orient="records"))

        expected_data = dataset[dataset["symbol"].isin(expected_symbols)].copy()
        expected_data["month"] = month
        expected_rows.extend((expected_data[["month", *BASE_COLUMNS, *GROWTH_VARIANTS]]).to_dict(orient="records"))

    out_dir = project_root / "outputs" / "formula_research_reference"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(expected_rows).to_csv(out_dir / "reference_growth_candidates.csv", index=False)
    pd.DataFrame(rank_rows).to_csv(out_dir / "reference_growth_variant_ranks.csv", index=False)
    pd.DataFrame(top_rows).to_csv(out_dir / "reference_growth_variant_top10.csv", index=False)

    print(out_dir / "reference_growth_candidates.csv")
    print(out_dir / "reference_growth_variant_ranks.csv")
    print(out_dir / "reference_growth_variant_top10.csv")


if __name__ == "__main__":
    main()

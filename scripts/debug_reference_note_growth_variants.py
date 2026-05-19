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


def _safe_growth(current: pd.Series, previous: pd.Series) -> pd.Series:
    denominator = previous.where(previous != 0)
    return (current - previous) / denominator


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
    if isinstance(known["announcement_datetime"].dtype, pd.DatetimeTZDtype):
        known["announcement_datetime"] = known["announcement_datetime"].dt.tz_localize(None)
    known["announcement_date"] = pd.to_datetime(known["announcement_date"], errors="coerce").dt.date
    known_dt = known[known["announcement_datetime"].notna() & (known["announcement_datetime"] <= rebalance_dt)]
    known_date = known[
        known["announcement_datetime"].isna()
        & known["announcement_date"].notna()
        & (known["announcement_date"] < buy_date)
    ]
    known = pd.concat([known_dt, known_date], ignore_index=True)

    previous_same_quarter = known[
        ["symbol", "fiscal_year", "fiscal_quarter", "net_income"]
    ].copy()
    previous_same_quarter["fiscal_year"] = previous_same_quarter["fiscal_year"] + 1
    previous_same_quarter = previous_same_quarter.rename(
        columns={"net_income": "previous_same_quarter_cum_net_income"}
    )

    latest = latest.merge(previous_same_quarter, on=["symbol", "fiscal_year", "fiscal_quarter"], how="left")

    dataset = annual.merge(
        latest[
            [
                "symbol",
                "period_end",
                "announcement_date",
                "fiscal_year",
                "fiscal_quarter",
                "net_income",
                "previous_same_quarter_cum_net_income",
            ]
        ].rename(
            columns={
                "period_end": "latest_period_end",
                "announcement_date": "latest_announcement_date",
                "net_income": "latest_cum_net_income",
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
    dataset["annual_growth_signed"] = _safe_growth(
        dataset["annual_net_income"], dataset["previous_annual_net_income"]
    )
    dataset["latest_cum_growth_signed"] = _safe_growth(
        dataset["latest_cum_net_income"], dataset["previous_same_quarter_cum_net_income"]
    )
    return dataset


def _score_with_growth(data: pd.DataFrame, growth_column: str, variant: str) -> pd.DataFrame:
    ranked = data.copy()
    ranked["x1_variant"] = (ranked["annual_net_income"] / ranked["equity"]) * (1 + ranked[growth_column])
    ranked["x2_variant"] = ranked["annual_operating_profit"] / ranked["firm_value"]
    ranked["score_variant"] = ranked["x1_variant"] + ranked["x2_variant"]
    ranked = ranked[
        ranked["annual_net_income"].notna()
        & ranked["previous_annual_net_income"].notna()
        & ranked["equity"].notna()
        & ranked["annual_operating_profit"].notna()
        & ranked["firm_value"].notna()
        & ranked[growth_column].notna()
        & (ranked["equity"] > 0)
        & (ranked["firm_value"] > 0)
    ].copy()
    ranked = ranked.sort_values(["score_variant", "symbol"], ascending=[False, True]).reset_index(drop=True)
    ranked["rank"] = ranked.index + 1
    ranked["variant"] = variant
    return ranked


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

    rank_rows: list[dict] = []
    top_rows: list[dict] = []

    variants = [
        ("note_annual_growth_signed", "annual_growth_signed"),
        ("note_latest_cum_growth_signed", "latest_cum_growth_signed"),
    ]

    for month, expected_symbols in EXPECTED.items():
        dataset = _build_month_dataset(snapshots, prices, membership, settings.universe.name, month)
        for variant_name, growth_column in variants:
            ranked = _score_with_growth(dataset, growth_column, variant_name)
            top_rows.extend(
                ranked.head(10)[
                    [
                        "symbol",
                        "rank",
                        "score_variant",
                        "x1_variant",
                        "x2_variant",
                        "annual_period_end",
                        "latest_period_end",
                        "annual_announcement_date",
                        "latest_announcement_date",
                    ]
                ]
                .assign(month=month)
                .to_dict(orient="records")
            )
            expected_ranked = ranked[ranked["symbol"].isin(expected_symbols)][
                [
                    "symbol",
                    "rank",
                    "score_variant",
                    "x1_variant",
                    "x2_variant",
                    "annual_period_end",
                    "latest_period_end",
                    "annual_growth_signed",
                    "latest_cum_growth_signed",
                ]
            ].copy()
            expected_ranked["month"] = month
            expected_ranked["variant"] = variant_name
            rank_rows.extend(expected_ranked.to_dict(orient="records"))

    out_dir = project_root / "outputs" / "formula_research_reference"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rank_rows).to_csv(out_dir / "reference_note_growth_variant_ranks.csv", index=False)
    pd.DataFrame(top_rows).to_csv(out_dir / "reference_note_growth_variant_top10.csv", index=False)
    print(out_dir / "reference_note_growth_variant_ranks.csv")
    print(out_dir / "reference_note_growth_variant_top10.csv")


if __name__ == "__main__":
    main()

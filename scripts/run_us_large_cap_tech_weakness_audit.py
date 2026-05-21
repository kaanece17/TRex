from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


def _load_inputs():
    settings = load_config(CONFIG_PATH)
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    financials["announcement_datetime"] = pd.to_datetime(financials["announcement_datetime"], errors="coerce")
    financials = (
        financials.sort_values(["symbol", "period_end", "announcement_datetime"])
        .drop_duplicates(["symbol", "period_end", "announcement_datetime"], keep="last")
        .reset_index(drop=True)
    )
    financials = add_earnings_momentum_features(financials)
    membership = _load_membership_for_run(settings)
    storage.close()
    return settings, prices, financials, membership


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)

    monthly = result["monthly_results"].copy()
    positions = result["selected_positions"].copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = _numeric(monthly["net_return"])
    positions["month"] = positions["month"].astype(str)

    numeric_columns = [
        "weight",
        "net_return",
        "selection_score",
        "score",
        "x1_share",
        "x2_share",
        "recent_return_20d",
        "recent_return_60d",
        "net_income_growth",
        "ni_ttm_growth_yoy",
        "op_ttm_growth_yoy",
        "earnings_acceleration",
        "quarterly_operating_profit",
        "operating_profit_ttm",
    ]
    for column in numeric_columns:
        if column in positions.columns:
            positions[column] = _numeric(positions[column])

    worst_months = monthly.nsmallest(15, "net_return").copy()
    worst_month_set = set(worst_months["month"].tolist())
    worst_positions = positions[positions["month"].isin(worst_month_set)].copy()
    all_positions = positions.copy()

    compare_rows = []
    feature_columns = [
        "x1_share",
        "x2_share",
        "recent_return_20d",
        "recent_return_60d",
        "net_income_growth",
        "ni_ttm_growth_yoy",
        "op_ttm_growth_yoy",
        "earnings_acceleration",
        "quarterly_operating_profit",
        "operating_profit_ttm",
        "selection_score",
        "score",
    ]
    for label, frame in [("all_positions", all_positions), ("worst15_positions", worst_positions)]:
        row = {
            "group": label,
            "rows": len(frame),
            "avg_net_return": float(frame["net_return"].mean()),
            "median_net_return": float(frame["net_return"].median()),
            "win_rate": float((frame["net_return"] > 0).mean()),
        }
        for column in feature_columns:
            if column in frame.columns:
                row[f"{column}_mean"] = float(frame[column].mean())
                row[f"{column}_median"] = float(frame[column].median())
        compare_rows.append(row)
    group_compare = pd.DataFrame(compare_rows)

    symbol_damage = (
        worst_positions.groupby("symbol", as_index=False)
        .agg(
            worst_month_hits=("month", "nunique"),
            total_weighted_damage=("net_return", lambda s: float(s.sum())),
            avg_return=("net_return", "mean"),
            median_return=("net_return", "median"),
            win_rate=("net_return", lambda s: float((s > 0).mean())),
        )
        .sort_values(["worst_month_hits", "total_weighted_damage"], ascending=[False, True])
        .reset_index(drop=True)
    )

    repeaters = symbol_damage[symbol_damage["worst_month_hits"] >= 2].copy()
    repeater_rows = worst_positions[worst_positions["symbol"].isin(repeaters["symbol"])].copy()
    repeater_compare = pd.DataFrame(
        [
            {
                "group": "all_worst_month_rows",
                "rows": len(worst_positions),
                "avg_net_return": float(worst_positions["net_return"].mean()),
                "median_net_return": float(worst_positions["net_return"].median()),
                "win_rate": float((worst_positions["net_return"] > 0).mean()),
            },
            {
                "group": "repeater_rows",
                "rows": len(repeater_rows),
                "avg_net_return": float(repeater_rows["net_return"].mean()) if not repeater_rows.empty else None,
                "median_net_return": float(repeater_rows["net_return"].median()) if not repeater_rows.empty else None,
                "win_rate": float((repeater_rows["net_return"] > 0).mean()) if not repeater_rows.empty else None,
            },
        ]
    )

    worst_months.to_csv(OUTPUT_DIR / "us_large_cap_tech_weakness_worst_months.csv", index=False)
    worst_positions.to_csv(OUTPUT_DIR / "us_large_cap_tech_weakness_worst_month_positions.csv", index=False)
    symbol_damage.to_csv(OUTPUT_DIR / "us_large_cap_tech_weakness_symbol_damage.csv", index=False)
    group_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_weakness_group_compare.csv", index=False)
    repeaters.to_csv(OUTPUT_DIR / "us_large_cap_tech_weakness_repeaters.csv", index=False)
    repeater_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_weakness_repeater_compare.csv", index=False)

    lines = [
        "# US Large-Cap Tech Weakness Audit",
        "",
        f"- winner profile: `tech_quality_earnings`",
        f"- full multiple: `{monthly['portfolio_value_end'].iloc[-1] / settings.backtest.initial_capital:.2f}x`",
        f"- max drawdown: `{((monthly['portfolio_value_end'] / monthly['portfolio_value_end'].cummax()) - 1).min():.2%}`",
        "",
        "Worst-month diagnostic:",
        f"- worst months analyzed: `{len(worst_months)}`",
        f"- repeater symbols in worst months: `{len(repeaters)}`",
        "",
        "Group compare:",
    ]
    for row in group_compare.to_dict("records"):
        lines.append(
            f"- `{row['group']}`: avg `{row['avg_net_return']:.2%}`, median `{row['median_net_return']:.2%}`, win `{row['win_rate']:.2%}`"
        )
    lines.append("")
    lines.append("Top damage symbols:")
    for row in symbol_damage.head(10).to_dict("records"):
        lines.append(
            f"- `{row['symbol']}`: hits `{int(row['worst_month_hits'])}`, avg `{row['avg_return']:.2%}`, total `{row['total_weighted_damage']:.2%}`"
        )
    (OUTPUT_DIR / "us_large_cap_tech_weakness_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(group_compare.to_string(index=False))
    print(symbol_damage.head(10).to_string(index=False))


if __name__ == "__main__":
    main()

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


def _bucket_compare(frame: pd.DataFrame, signal: str, mask: pd.Series) -> dict[str, object]:
    flagged = frame[mask].copy()
    other = frame[~mask].copy()
    return {
        "signal": signal,
        "flagged_rows": len(flagged),
        "flagged_mean_return": float(flagged["net_return"].mean()) if not flagged.empty else None,
        "flagged_median_return": float(flagged["net_return"].median()) if not flagged.empty else None,
        "flagged_win_rate": float((flagged["net_return"] > 0).mean()) if not flagged.empty else None,
        "other_rows": len(other),
        "other_mean_return": float(other["net_return"].mean()) if not other.empty else None,
        "other_median_return": float(other["net_return"].median()) if not other.empty else None,
        "other_win_rate": float((other["net_return"] > 0).mean()) if not other.empty else None,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)

    monthly = result["monthly_results"].copy()
    positions = result["selected_positions"].copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = _numeric(monthly["net_return"])
    positions["month"] = positions["month"].astype(str)

    for column in [
        "net_return",
        "x1",
        "x2",
        "x1_share",
        "x2_share",
        "score",
        "selection_score",
        "profitability_quality_combo",
        "operating_profit_ttm",
        "firm_value",
        "earnings_signal",
    ]:
        if column in positions.columns:
            positions[column] = _numeric(positions[column])

    positions["op_to_fv"] = positions["operating_profit_ttm"] / positions["firm_value"]
    positions["profitability_quality_combo_rank"] = positions["profitability_quality_combo"].rank(method="average", pct=True)

    worst_months = monthly.nsmallest(15, "net_return").copy()
    worst_positions = positions[positions["month"].isin(set(worst_months["month"]))].copy()

    compare_rows = []
    feature_columns = [
        "x1_share",
        "x2_share",
        "x1",
        "x2",
        "score",
        "selection_score",
        "profitability_quality_combo",
        "profitability_quality_combo_rank",
        "op_to_fv",
        "earnings_signal",
    ]
    for label, frame in [("all_positions", positions), ("worst15_positions", worst_positions)]:
        row = {
            "group": label,
            "rows": len(frame),
            "avg_net_return": float(frame["net_return"].mean()),
            "median_net_return": float(frame["net_return"].median()),
            "win_rate": float((frame["net_return"] > 0).mean()),
        }
        for column in feature_columns:
            row[f"{column}_mean"] = float(frame[column].mean())
            row[f"{column}_median"] = float(frame[column].median())
        compare_rows.append(row)
    group_compare = pd.DataFrame(compare_rows)

    low_x2_share = positions["x2_share"] <= positions["x2_share"].quantile(0.25)
    low_profitability = positions["profitability_quality_combo"] <= positions["profitability_quality_combo"].quantile(0.25)
    low_op_to_fv = positions["op_to_fv"] <= positions["op_to_fv"].quantile(0.25)
    expensive_growth_combo = low_x2_share & low_profitability

    bucket_compare = pd.DataFrame(
        [
            _bucket_compare(positions, "low_x2_share_q25", low_x2_share.fillna(False)),
            _bucket_compare(positions, "low_profitability_q25", low_profitability.fillna(False)),
            _bucket_compare(positions, "low_op_to_fv_q25", low_op_to_fv.fillna(False)),
            _bucket_compare(positions, "low_x2_and_low_profitability", expensive_growth_combo.fillna(False)),
        ]
    )

    month_exposure = (
        positions.assign(
            low_x2_share=low_x2_share.fillna(False),
            low_profitability=low_profitability.fillna(False),
            low_op_to_fv=low_op_to_fv.fillna(False),
            low_x2_and_low_profitability=expensive_growth_combo.fillna(False),
        )
        .groupby("month", as_index=False)
        .agg(
            x2_share_mean=("x2_share", "mean"),
            profitability_quality_combo_mean=("profitability_quality_combo", "mean"),
            op_to_fv_mean=("op_to_fv", "mean"),
            low_x2_share_share=("low_x2_share", "mean"),
            low_profitability_share=("low_profitability", "mean"),
            low_op_to_fv_share=("low_op_to_fv", "mean"),
            low_x2_and_low_profitability_share=("low_x2_and_low_profitability", "mean"),
        )
        .merge(monthly[["month", "net_return"]], on="month", how="left")
    )

    corr_rows = []
    for column in [
        "x2_share_mean",
        "profitability_quality_combo_mean",
        "op_to_fv_mean",
        "low_x2_share_share",
        "low_profitability_share",
        "low_op_to_fv_share",
        "low_x2_and_low_profitability_share",
    ]:
        corr_rows.append(
            {
                "metric": column,
                "corr_with_month_return": float(month_exposure[column].corr(month_exposure["net_return"])),
            }
        )
    month_corr = pd.DataFrame(corr_rows)

    group_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_value_profitability_group_compare.csv", index=False)
    bucket_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_value_profitability_bucket_compare.csv", index=False)
    month_exposure.to_csv(OUTPUT_DIR / "us_large_cap_tech_value_profitability_month_exposure.csv", index=False)
    month_corr.to_csv(OUTPUT_DIR / "us_large_cap_tech_value_profitability_month_corr.csv", index=False)

    lines = [
        "# US Large-Cap Tech Value / Profitability Audit",
        "",
        "Group compare:",
    ]
    for row in group_compare.to_dict("records"):
        lines.append(
            f"- `{row['group']}`: avg `{row['avg_net_return']:.2%}`, win `{row['win_rate']:.2%}`, "
            f"x2_share_mean `{row['x2_share_mean']:.3f}`, profitability_mean `{row['profitability_quality_combo_mean']:.3f}`, "
            f"op_to_fv_mean `{row['op_to_fv_mean']:.4f}`"
        )
    lines.append("")
    lines.append("Bucket compare:")
    for row in bucket_compare.to_dict("records"):
        lines.append(
            f"- `{row['signal']}`: flagged avg `{row['flagged_mean_return']:.2%}`, other avg `{row['other_mean_return']:.2%}`, "
            f"flagged win `{row['flagged_win_rate']:.2%}`, other win `{row['other_win_rate']:.2%}`"
        )
    lines.append("")
    lines.append("Month-level correlations:")
    for row in month_corr.to_dict("records"):
        lines.append(f"- `{row['metric']}` vs month return: `{row['corr_with_month_return']:.3f}`")
    (OUTPUT_DIR / "us_large_cap_tech_value_profitability_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(group_compare.to_string(index=False))
    print(bucket_compare.to_string(index=False))
    print(month_corr.to_string(index=False))


if __name__ == "__main__":
    main()

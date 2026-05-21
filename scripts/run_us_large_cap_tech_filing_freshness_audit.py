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


def _quarter_lag(period_end: pd.Series, buy_date: pd.Series) -> pd.Series:
    period_dt = pd.to_datetime(period_end, errors="coerce")
    buy_dt = pd.to_datetime(buy_date, errors="coerce")
    period_q = ((period_dt.dt.month - 1) // 3) + 1
    buy_q = ((buy_dt.dt.month - 1) // 3) + 1
    return ((buy_dt.dt.year - period_dt.dt.year) * 4) + (buy_q - period_q)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)

    monthly = result["monthly_results"].copy()
    positions = result["selected_positions"].copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = _numeric(monthly["net_return"])
    positions["month"] = positions["month"].astype(str)
    positions["net_return"] = _numeric(positions["net_return"])

    positions["used_announcement_datetime"] = pd.to_datetime(positions["used_announcement_datetime"], errors="coerce")
    positions["buy_date"] = pd.to_datetime(positions["buy_date"], errors="coerce")
    positions["used_period_end"] = pd.to_datetime(positions["used_period_end"], errors="coerce")

    positions["filing_age_days"] = (positions["buy_date"] - positions["used_announcement_datetime"]).dt.days
    positions["financial_base_quarter_lag"] = _quarter_lag(positions["used_period_end"], positions["buy_date"])
    positions["fresh_30d"] = positions["filing_age_days"].le(30)
    positions["fresh_60d"] = positions["filing_age_days"].le(60)
    positions["stale_120d"] = positions["filing_age_days"].ge(120)
    positions["stale_quarter_base"] = positions["financial_base_quarter_lag"].ge(2)

    worst_months = monthly.nsmallest(15, "net_return").copy()
    worst_positions = positions[positions["month"].isin(set(worst_months["month"]))].copy()

    compare_rows = []
    freshness_columns = [
        "filing_age_days",
        "financial_base_quarter_lag",
        "fresh_30d",
        "fresh_60d",
        "stale_120d",
        "stale_quarter_base",
    ]
    for label, frame in [("all_positions", positions), ("worst15_positions", worst_positions)]:
        row = {
            "group": label,
            "rows": len(frame),
            "avg_net_return": float(frame["net_return"].mean()),
            "median_net_return": float(frame["net_return"].median()),
            "win_rate": float((frame["net_return"] > 0).mean()),
        }
        for column in freshness_columns:
            if column in {"filing_age_days", "financial_base_quarter_lag"}:
                row[f"{column}_mean"] = float(frame[column].mean())
                row[f"{column}_median"] = float(frame[column].median())
            else:
                row[f"{column}_share"] = float(frame[column].mean())
        compare_rows.append(row)
    group_compare = pd.DataFrame(compare_rows)

    bucket_rows = []
    for signal_name, mask in [
        ("fresh_30d", positions["fresh_30d"].fillna(False)),
        ("fresh_60d", positions["fresh_60d"].fillna(False)),
        ("stale_120d", positions["stale_120d"].fillna(False)),
        ("stale_quarter_base", positions["stale_quarter_base"].fillna(False)),
    ]:
        flagged = positions[mask].copy()
        other = positions[~mask].copy()
        bucket_rows.append(
            {
                "signal": signal_name,
                "flagged_rows": len(flagged),
                "flagged_mean_return": float(flagged["net_return"].mean()) if not flagged.empty else None,
                "flagged_median_return": float(flagged["net_return"].median()) if not flagged.empty else None,
                "flagged_win_rate": float((flagged["net_return"] > 0).mean()) if not flagged.empty else None,
                "other_rows": len(other),
                "other_mean_return": float(other["net_return"].mean()) if not other.empty else None,
                "other_median_return": float(other["net_return"].median()) if not other.empty else None,
                "other_win_rate": float((other["net_return"] > 0).mean()) if not other.empty else None,
            }
        )
    bucket_compare = pd.DataFrame(bucket_rows)

    monthly_exposure = (
        positions.groupby("month", as_index=False)
        .agg(
            avg_filing_age_days=("filing_age_days", "mean"),
            avg_quarter_lag=("financial_base_quarter_lag", "mean"),
            fresh_30d_share=("fresh_30d", "mean"),
            fresh_60d_share=("fresh_60d", "mean"),
            stale_120d_share=("stale_120d", "mean"),
            stale_quarter_base_share=("stale_quarter_base", "mean"),
        )
        .merge(monthly[["month", "net_return"]], on="month", how="left")
    )
    corr_rows = []
    for column in [
        "avg_filing_age_days",
        "avg_quarter_lag",
        "fresh_30d_share",
        "fresh_60d_share",
        "stale_120d_share",
        "stale_quarter_base_share",
    ]:
        corr_rows.append(
            {
                "metric": column,
                "corr_with_month_return": float(monthly_exposure[column].corr(monthly_exposure["net_return"])),
            }
        )
    month_corr = pd.DataFrame(corr_rows)

    group_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_filing_freshness_group_compare.csv", index=False)
    bucket_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_filing_freshness_bucket_compare.csv", index=False)
    monthly_exposure.to_csv(OUTPUT_DIR / "us_large_cap_tech_filing_freshness_month_exposure.csv", index=False)
    month_corr.to_csv(OUTPUT_DIR / "us_large_cap_tech_filing_freshness_month_corr.csv", index=False)

    lines = [
        "# US Large-Cap Tech Filing Freshness Audit",
        "",
        "Group compare:",
    ]
    for row in group_compare.to_dict("records"):
        lines.append(
            f"- `{row['group']}`: avg `{row['avg_net_return']:.2%}`, win `{row['win_rate']:.2%}`, "
            f"filing_age_mean `{row['filing_age_days_mean']:.1f}`, quarter_lag_mean `{row['financial_base_quarter_lag_mean']:.2f}`"
        )
    lines.append("")
    lines.append("Freshness buckets:")
    for row in bucket_compare.to_dict("records"):
        lines.append(
            f"- `{row['signal']}`: flagged avg `{row['flagged_mean_return']:.2%}`, other avg `{row['other_mean_return']:.2%}`, "
            f"flagged win `{row['flagged_win_rate']:.2%}`, other win `{row['other_win_rate']:.2%}`"
        )
    lines.append("")
    lines.append("Month-level correlations:")
    for row in month_corr.to_dict("records"):
        lines.append(f"- `{row['metric']}` vs month return: `{row['corr_with_month_return']:.3f}`")
    (OUTPUT_DIR / "us_large_cap_tech_filing_freshness_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(group_compare.to_string(index=False))
    print(bucket_compare.to_string(index=False))
    print(month_corr.to_string(index=False))


if __name__ == "__main__":
    main()

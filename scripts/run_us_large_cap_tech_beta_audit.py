from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.price_loader_yfinance import YFinancePriceLoader
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
LOOKBACK_DAYS = 60


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


def _load_benchmark_prices(settings) -> pd.DataFrame:
    loader = YFinancePriceLoader()
    benchmark_prices = loader.load(
        ["QQQ", "XLK"],
        settings.data.price_preload_start or settings.backtest.start_date,
        settings.backtest.end_date,
        yahoo_suffix=settings.data.price_symbol_suffix,
    )
    benchmark_prices["date"] = pd.to_datetime(benchmark_prices["date"]).dt.date
    return benchmark_prices


def _prepare_returns(prices: pd.DataFrame) -> pd.DataFrame:
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.date
    close_col = "adjusted_close" if "adjusted_close" in data.columns else "close"
    data = data.sort_values(["symbol", "date"]).copy()
    data["daily_return"] = data.groupby("symbol")[close_col].pct_change()
    return data[["symbol", "date", "daily_return"]].dropna().reset_index(drop=True)


def _trailing_beta(symbol_returns: pd.DataFrame, benchmark_returns: pd.DataFrame, buy_date, lookback_days: int) -> float | None:
    merged = symbol_returns.merge(benchmark_returns, on="date", how="inner", suffixes=("_stock", "_bench"))
    merged = merged[merged["date"] < buy_date].sort_values("date").tail(lookback_days)
    if len(merged) < max(20, lookback_days // 2):
        return None
    bench_var = float(merged["daily_return_bench"].var(ddof=0))
    if not np.isfinite(bench_var) or bench_var <= 0:
        return None
    cov = float(np.cov(merged["daily_return_stock"], merged["daily_return_bench"], ddof=0)[0, 1])
    beta = cov / bench_var
    return float(beta) if np.isfinite(beta) else None


def _attach_betas(positions: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    enriched = positions.copy()
    returns_map = {symbol: frame[["date", "daily_return"]].copy() for symbol, frame in returns.groupby("symbol")}
    qqq_returns = returns_map.get("QQQ")
    xlk_returns = returns_map.get("XLK")
    qqq_betas: list[float | None] = []
    xlk_betas: list[float | None] = []
    for row in enriched.itertuples(index=False):
        symbol_returns = returns_map.get(str(row.symbol))
        buy_date = pd.to_datetime(row.buy_date).date()
        qqq_betas.append(
            _trailing_beta(symbol_returns, qqq_returns, buy_date, LOOKBACK_DAYS)
            if symbol_returns is not None and qqq_returns is not None
            else None
        )
        xlk_betas.append(
            _trailing_beta(symbol_returns, xlk_returns, buy_date, LOOKBACK_DAYS)
            if symbol_returns is not None and xlk_returns is not None
            else None
        )
    enriched["beta_qqq_60d"] = qqq_betas
    enriched["beta_xlk_60d"] = xlk_betas
    return enriched


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)

    benchmark_prices = _load_benchmark_prices(settings)
    all_returns = _prepare_returns(pd.concat([prices, benchmark_prices], ignore_index=True))

    monthly = result["monthly_results"].copy()
    positions = result["selected_positions"].copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = pd.to_numeric(monthly["net_return"], errors="coerce")
    positions["month"] = positions["month"].astype(str)
    positions["net_return"] = pd.to_numeric(positions["net_return"], errors="coerce")
    positions["weight"] = pd.to_numeric(positions["weight"], errors="coerce")
    positions = _attach_betas(positions, all_returns)

    worst_months = monthly.nsmallest(15, "net_return").copy()
    worst_month_set = set(worst_months["month"].tolist())
    worst_positions = positions[positions["month"].isin(worst_month_set)].copy()

    compare = pd.DataFrame(
        [
            {
                "group": "all_positions",
                "rows": len(positions),
                "avg_net_return": float(positions["net_return"].mean()),
                "win_rate": float((positions["net_return"] > 0).mean()),
                "beta_qqq_60d_mean": float(positions["beta_qqq_60d"].mean()),
                "beta_qqq_60d_median": float(positions["beta_qqq_60d"].median()),
                "beta_xlk_60d_mean": float(positions["beta_xlk_60d"].mean()),
                "beta_xlk_60d_median": float(positions["beta_xlk_60d"].median()),
            },
            {
                "group": "worst15_positions",
                "rows": len(worst_positions),
                "avg_net_return": float(worst_positions["net_return"].mean()),
                "win_rate": float((worst_positions["net_return"] > 0).mean()),
                "beta_qqq_60d_mean": float(worst_positions["beta_qqq_60d"].mean()),
                "beta_qqq_60d_median": float(worst_positions["beta_qqq_60d"].median()),
                "beta_xlk_60d_mean": float(worst_positions["beta_xlk_60d"].mean()),
                "beta_xlk_60d_median": float(worst_positions["beta_xlk_60d"].median()),
            },
        ]
    )

    positions["high_beta_qqq_q75"] = positions["beta_qqq_60d"] >= positions["beta_qqq_60d"].quantile(0.75)
    positions["high_beta_xlk_q75"] = positions["beta_xlk_60d"] >= positions["beta_xlk_60d"].quantile(0.75)
    bucket_rows = []
    for flag in ["high_beta_qqq_q75", "high_beta_xlk_q75"]:
        flagged = positions[positions[flag]].copy()
        other = positions[~positions[flag]].copy()
        bucket_rows.append(
            {
                "flag": flag,
                "flagged_rows": len(flagged),
                "flagged_avg_return": float(flagged["net_return"].mean()),
                "flagged_win_rate": float((flagged["net_return"] > 0).mean()),
                "other_rows": len(other),
                "other_avg_return": float(other["net_return"].mean()),
                "other_win_rate": float((other["net_return"] > 0).mean()),
            }
        )
    bucket_compare = pd.DataFrame(bucket_rows)

    month_beta = (
        positions.groupby("month", as_index=False)
        .agg(
            portfolio_beta_qqq_60d=("beta_qqq_60d", lambda s: float(s.mean())),
            portfolio_beta_xlk_60d=("beta_xlk_60d", lambda s: float(s.mean())),
            weighted_beta_qqq_60d=("beta_qqq_60d", lambda s: float(np.nanmean(s))),
            high_beta_qqq_share=("high_beta_qqq_q75", lambda s: float(s.mean())),
            high_beta_xlk_share=("high_beta_xlk_q75", lambda s: float(s.mean())),
        )
        .merge(monthly[["month", "net_return"]], on="month", how="left")
    )
    corr = pd.DataFrame(
        [
            {"metric": "portfolio_beta_qqq_60d", "corr_with_month_return": float(month_beta["portfolio_beta_qqq_60d"].corr(month_beta["net_return"]))},
            {"metric": "portfolio_beta_xlk_60d", "corr_with_month_return": float(month_beta["portfolio_beta_xlk_60d"].corr(month_beta["net_return"]))},
            {"metric": "high_beta_qqq_share", "corr_with_month_return": float(month_beta["high_beta_qqq_share"].corr(month_beta["net_return"]))},
            {"metric": "high_beta_xlk_share", "corr_with_month_return": float(month_beta["high_beta_xlk_share"].corr(month_beta["net_return"]))},
        ]
    )

    worst_months.to_csv(OUTPUT_DIR / "us_large_cap_tech_beta_worst_months.csv", index=False)
    positions.to_csv(OUTPUT_DIR / "us_large_cap_tech_beta_rows.csv", index=False)
    compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_beta_group_compare.csv", index=False)
    bucket_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_beta_bucket_compare.csv", index=False)
    month_beta.to_csv(OUTPUT_DIR / "us_large_cap_tech_beta_month_compare.csv", index=False)
    corr.to_csv(OUTPUT_DIR / "us_large_cap_tech_beta_corr.csv", index=False)

    lines = [
        "# US Large-Cap Tech Beta Audit",
        "",
        f"- profile: `tech_quality_earnings`",
        f"- trailing beta lookback: `{LOOKBACK_DAYS}d`",
        "",
    ]
    for row in compare.to_dict("records"):
        lines.append(
            f"- `{row['group']}`: avg `{row['avg_net_return']:.2%}`, win `{row['win_rate']:.2%}`, "
            f"QQQ beta mean `{row['beta_qqq_60d_mean']:.2f}`, XLK beta mean `{row['beta_xlk_60d_mean']:.2f}`"
        )
    lines.append("")
    lines.append("Bucket compare:")
    for row in bucket_compare.to_dict("records"):
        lines.append(
            f"- `{row['flag']}`: flagged avg `{row['flagged_avg_return']:.2%}`, other avg `{row['other_avg_return']:.2%}`, "
            f"flagged win `{row['flagged_win_rate']:.2%}`, other win `{row['other_win_rate']:.2%}`"
        )
    lines.append("")
    lines.append("Month correlation:")
    for row in corr.to_dict("records"):
        lines.append(f"- `{row['metric']}` vs month return: `{row['corr_with_month_return']:.3f}`")
    (OUTPUT_DIR / "us_large_cap_tech_beta_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(compare.to_string(index=False))
    print(bucket_compare.to_string(index=False))
    print(corr.to_string(index=False))


if __name__ == "__main__":
    main()

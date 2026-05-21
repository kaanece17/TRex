from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import (
    _calculate_universe_breadth_above_sma,
    run_monthly_rotation_backtest,
)
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.calendar import get_first_trading_day
from bist_factor_backtest.data.price_loader_yfinance import YFinancePriceLoader
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
BENCHMARKS = ["QQQ", "XLK"]


def _load_inputs():
    settings = load_config(CONFIG_PATH)
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
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


def _benchmark_monthly(symbol: str, base_monthly: pd.DataFrame, settings) -> pd.DataFrame:
    loader = YFinancePriceLoader()
    benchmark_prices = loader.load(
        [symbol],
        settings.data.price_preload_start or settings.backtest.start_date,
        settings.backtest.end_date,
        yahoo_suffix=settings.data.price_symbol_suffix,
    )
    benchmark_prices["date"] = pd.to_datetime(benchmark_prices["date"]).dt.date

    months = base_monthly["month"].astype(str).tolist()
    rows: list[dict[str, object]] = []
    portfolio_value = settings.backtest.initial_capital
    for idx, month in enumerate(months):
        buy_date = get_first_trading_day(benchmark_prices, month)
        if idx + 1 < len(months):
            sell_date = get_first_trading_day(benchmark_prices, months[idx + 1])
        else:
            sell_date = pd.to_datetime(base_monthly.iloc[idx]["sell_date"]).date()
        buy_row = benchmark_prices[(benchmark_prices["symbol"] == symbol) & (benchmark_prices["date"] == buy_date)]
        sell_row = benchmark_prices[(benchmark_prices["symbol"] == symbol) & (benchmark_prices["date"] == sell_date)]
        if buy_row.empty or sell_row.empty:
            continue
        buy_open = float(buy_row["open"].iloc[0])
        sell_open = float(sell_row["open"].iloc[0])
        net_return = (sell_open / buy_open) - 1 if buy_open > 0 else 0.0
        start_value = portfolio_value
        portfolio_value = portfolio_value * (1 + net_return)
        rows.append(
            {
                "month": month,
                "buy_date": buy_date,
                "sell_date": sell_date,
                "net_return": net_return,
                "portfolio_value_start": start_value,
                "portfolio_value_end": portfolio_value,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    monthly = result["monthly_results"].copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = pd.to_numeric(monthly["net_return"], errors="coerce")

    universe_symbols = sorted(membership["symbol"].astype(str).unique().tolist())

    regime_rows: list[dict[str, object]] = []
    for row in monthly.to_dict("records"):
        buy_date = pd.to_datetime(row["buy_date"]).date()
        breadth_200d = _calculate_universe_breadth_above_sma(prices, universe_symbols, buy_date, 200)
        breadth_60d = _calculate_universe_breadth_above_sma(prices, universe_symbols, buy_date, 60)
        regime_rows.append(
            {
                "month": row["month"],
                "buy_date": buy_date,
                "breadth_200d": breadth_200d,
                "breadth_60d": breadth_60d,
                "tech_return": float(row["net_return"]),
            }
        )
    regime = pd.DataFrame(regime_rows)

    benchmark_frames = []
    for symbol in BENCHMARKS:
        bench = _benchmark_monthly(symbol, monthly, settings)
        bench = bench.rename(columns={"net_return": f"{symbol.lower()}_return"})
        benchmark_frames.append(bench[["month", f"{symbol.lower()}_return"]])
    for frame in benchmark_frames:
        regime = regime.merge(frame, on="month", how="left")

    regime["qqq_negative"] = regime["qqq_return"] < 0
    regime["xlk_negative"] = regime["xlk_return"] < 0
    regime["weak_breadth_200d"] = regime["breadth_200d"] < 0.50
    regime["weak_breadth_60d"] = regime["breadth_60d"] < 0.50
    regime["double_risk_off"] = regime["qqq_negative"] & regime["weak_breadth_200d"]

    worst_months = regime.nsmallest(15, "tech_return").copy()

    group_compare = pd.DataFrame(
        [
            {
                "group": "all_months",
                "rows": len(regime),
                "avg_tech_return": float(regime["tech_return"].mean()),
                "median_tech_return": float(regime["tech_return"].median()),
                "breadth_200d_mean": float(regime["breadth_200d"].mean()),
                "breadth_60d_mean": float(regime["breadth_60d"].mean()),
                "qqq_return_mean": float(regime["qqq_return"].mean()),
                "xlk_return_mean": float(regime["xlk_return"].mean()),
                "qqq_negative_share": float(regime["qqq_negative"].mean()),
                "xlk_negative_share": float(regime["xlk_negative"].mean()),
                "weak_breadth_200d_share": float(regime["weak_breadth_200d"].mean()),
                "weak_breadth_60d_share": float(regime["weak_breadth_60d"].mean()),
                "double_risk_off_share": float(regime["double_risk_off"].mean()),
            },
            {
                "group": "worst15_months",
                "rows": len(worst_months),
                "avg_tech_return": float(worst_months["tech_return"].mean()),
                "median_tech_return": float(worst_months["tech_return"].median()),
                "breadth_200d_mean": float(worst_months["breadth_200d"].mean()),
                "breadth_60d_mean": float(worst_months["breadth_60d"].mean()),
                "qqq_return_mean": float(worst_months["qqq_return"].mean()),
                "xlk_return_mean": float(worst_months["xlk_return"].mean()),
                "qqq_negative_share": float(worst_months["qqq_negative"].mean()),
                "xlk_negative_share": float(worst_months["xlk_negative"].mean()),
                "weak_breadth_200d_share": float(worst_months["weak_breadth_200d"].mean()),
                "weak_breadth_60d_share": float(worst_months["weak_breadth_60d"].mean()),
                "double_risk_off_share": float(worst_months["double_risk_off"].mean()),
            },
        ]
    )

    bucket_compare_rows = []
    for signal in ["qqq_negative", "xlk_negative", "weak_breadth_200d", "weak_breadth_60d", "double_risk_off"]:
        flagged = regime[regime[signal]].copy()
        other = regime[~regime[signal]].copy()
        bucket_compare_rows.append(
            {
                "signal": signal,
                "flagged_rows": len(flagged),
                "flagged_mean_return": float(flagged["tech_return"].mean()) if not flagged.empty else None,
                "flagged_median_return": float(flagged["tech_return"].median()) if not flagged.empty else None,
                "flagged_win_rate": float((flagged["tech_return"] > 0).mean()) if not flagged.empty else None,
                "other_rows": len(other),
                "other_mean_return": float(other["tech_return"].mean()) if not other.empty else None,
                "other_median_return": float(other["tech_return"].median()) if not other.empty else None,
                "other_win_rate": float((other["tech_return"] > 0).mean()) if not other.empty else None,
            }
        )
    bucket_compare = pd.DataFrame(bucket_compare_rows)

    corr_rows = []
    for column in ["breadth_200d", "breadth_60d", "qqq_return", "xlk_return"]:
        corr_rows.append(
            {
                "metric": column,
                "corr_with_tech_return": float(regime[column].corr(regime["tech_return"])),
            }
        )
    corr = pd.DataFrame(corr_rows)

    regime.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_months.csv", index=False)
    worst_months.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_worst_months.csv", index=False)
    group_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_group_compare.csv", index=False)
    bucket_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_bucket_compare.csv", index=False)
    corr.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_corr.csv", index=False)

    lines = [
        "# US Large-Cap Tech Regime Audit",
        "",
        "Group compare:",
    ]
    for row in group_compare.to_dict("records"):
        lines.append(
            f"- `{row['group']}`: avg tech `{row['avg_tech_return']:.2%}`, breadth200 `{row['breadth_200d_mean']:.2%}`, "
            f"breadth60 `{row['breadth_60d_mean']:.2%}`, QQQ `{row['qqq_return_mean']:.2%}`, XLK `{row['xlk_return_mean']:.2%}`"
        )
    lines.append("")
    lines.append("Bucket compare:")
    for row in bucket_compare.to_dict("records"):
        lines.append(
            f"- `{row['signal']}`: flagged avg `{row['flagged_mean_return']:.2%}`, other avg `{row['other_mean_return']:.2%}`, "
            f"flagged win `{row['flagged_win_rate']:.2%}`, other win `{row['other_win_rate']:.2%}`"
        )
    lines.append("")
    lines.append("Correlations:")
    for row in corr.to_dict("records"):
        lines.append(f"- `{row['metric']}` vs tech return: `{row['corr_with_tech_return']:.3f}`")
    (OUTPUT_DIR / "us_large_cap_tech_regime_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(group_compare.to_string(index=False))
    print(bucket_compare.to_string(index=False))
    print(corr.to_string(index=False))


if __name__ == "__main__":
    main()

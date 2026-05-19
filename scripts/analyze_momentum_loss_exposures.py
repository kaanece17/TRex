from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.storage import DuckDbStorage


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.formula_research_momentum.yaml"
OUTPUT_DIR = ROOT / "outputs/formula_research_reference"


def latest_run_id(storage: DuckDbStorage, config_path: Path) -> str:
    runs = storage.read_table("backtest_runs")
    runs = runs[runs["notes"].astype(str) == str(config_path)].copy()
    runs["created_at"] = pd.to_datetime(runs["created_at"], errors="coerce")
    runs = runs.sort_values("created_at")
    if runs.empty:
        raise RuntimeError(f"No run found for {config_path}")
    return str(runs.iloc[-1]["run_id"])


def build_price_features(prices: pd.DataFrame) -> pd.DataFrame:
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.date
    close_col = "adjusted_close" if "adjusted_close" in data.columns else "close"
    data = data.sort_values(["symbol", "date"]).copy()
    data["turnover"] = pd.to_numeric(data["close"], errors="coerce") * pd.to_numeric(data["volume"], errors="coerce")
    data["daily_return"] = data.groupby("symbol")[close_col].pct_change()
    data["avg_turnover_20d"] = (
        data.groupby("symbol")["turnover"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    )
    data["recent_return_20d"] = (
        data.groupby("symbol")[close_col].transform(lambda s: s.shift(1) / s.shift(21) - 1)
    )
    data["recent_return_60d"] = (
        data.groupby("symbol")[close_col].transform(lambda s: s.shift(1) / s.shift(61) - 1)
    )
    data["volatility_20d"] = (
        data.groupby("symbol")["daily_return"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).std(ddof=0))
    )
    return data[["symbol", "date", "avg_turnover_20d", "recent_return_20d", "recent_return_60d", "volatility_20d"]]


def attach_exposures(selected: pd.DataFrame, monthly: pd.DataFrame, price_features: pd.DataFrame) -> pd.DataFrame:
    enriched = selected.copy()
    enriched["buy_date"] = pd.to_datetime(enriched["buy_date"], errors="coerce").dt.date
    enriched["month"] = enriched["month"].astype(str)
    monthly = monthly.copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["loss_month"] = pd.to_numeric(monthly["net_return"], errors="coerce") < 0
    enriched = enriched.merge(monthly[["month", "net_return", "loss_month"]], on="month", how="left", suffixes=("", "_month"))
    enriched = enriched.merge(price_features, left_on=["symbol", "buy_date"], right_on=["symbol", "date"], how="left")
    enriched["market_cap_proxy"] = (
        pd.to_numeric(enriched["firm_value"], errors="coerce")
        - pd.to_numeric(enriched["total_debt"], errors="coerce")
        + pd.to_numeric(enriched["cash"], errors="coerce")
    )
    return enriched


def weighted_mean(frame: pd.DataFrame, column: str) -> float | None:
    values = pd.to_numeric(frame[column], errors="coerce")
    weights = pd.to_numeric(frame["weight"], errors="coerce")
    valid = values.notna() & weights.notna()
    if not valid.any():
        return None
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def summarize_by_month_type(enriched: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, subset in [
        ("loss_months", enriched[enriched["loss_month"] == True]),
        ("non_loss_months", enriched[enriched["loss_month"] == False]),
        ("all_months", enriched),
    ]:
        rows.append(
            {
                "segment": label,
                "rows": len(subset),
                "months": int(subset["month"].nunique()) if not subset.empty else 0,
                "mean_position_return": pd.to_numeric(subset["net_return"], errors="coerce").mean(),
                "median_position_return": pd.to_numeric(subset["net_return"], errors="coerce").median(),
                "weighted_score": weighted_mean(subset, "score"),
                "weighted_x1": weighted_mean(subset, "x1"),
                "weighted_x2": weighted_mean(subset, "x2"),
                "weighted_market_cap_proxy": weighted_mean(subset, "market_cap_proxy"),
                "weighted_firm_value": weighted_mean(subset, "firm_value"),
                "weighted_avg_turnover_20d": weighted_mean(subset, "avg_turnover_20d"),
                "weighted_recent_return_20d": weighted_mean(subset, "recent_return_20d"),
                "weighted_recent_return_60d": weighted_mean(subset, "recent_return_60d"),
                "weighted_volatility_20d": weighted_mean(subset, "volatility_20d"),
            }
        )
    return pd.DataFrame(rows)


def summarize_loss_months(enriched: pd.DataFrame) -> pd.DataFrame:
    loss = enriched[enriched["loss_month"] == True].copy()
    grouped_rows = []
    for month, subset in loss.groupby("month", dropna=False):
        grouped_rows.append(
            {
                "month": month,
                "month_net_return": pd.to_numeric(subset["net_return_month"], errors="coerce").iloc[0],
                "symbols": ",".join(subset["symbol"].astype(str).tolist()),
                "weighted_market_cap_proxy": weighted_mean(subset, "market_cap_proxy"),
                "weighted_avg_turnover_20d": weighted_mean(subset, "avg_turnover_20d"),
                "weighted_recent_return_20d": weighted_mean(subset, "recent_return_20d"),
                "weighted_recent_return_60d": weighted_mean(subset, "recent_return_60d"),
                "weighted_volatility_20d": weighted_mean(subset, "volatility_20d"),
            }
        )
    return pd.DataFrame(grouped_rows).sort_values("month")


def bucketize(values: pd.Series, labels: list[str]) -> pd.Series:
    ranked = values.rank(method="first", pct=True)
    bins = [0.0, 1 / 3, 2 / 3, 1.0]
    return pd.cut(ranked, bins=bins, labels=labels, include_lowest=True)


def summarize_loss_buckets(enriched: pd.DataFrame) -> pd.DataFrame:
    data = enriched.copy()
    data["size_bucket"] = bucketize(pd.to_numeric(data["market_cap_proxy"], errors="coerce"), ["small", "mid", "large"])
    data["liquidity_bucket"] = bucketize(pd.to_numeric(data["avg_turnover_20d"], errors="coerce"), ["illiquid", "mid", "liquid"])
    data["vol_bucket"] = bucketize(pd.to_numeric(data["volatility_20d"], errors="coerce"), ["low_vol", "mid_vol", "high_vol"])
    rows = []
    for column in ["size_bucket", "liquidity_bucket", "vol_bucket"]:
        subset = data[data[column].notna()].copy()
        for bucket, frame in subset.groupby(column, dropna=False):
            rows.append(
                {
                    "dimension": column,
                    "bucket": str(bucket),
                    "rows": len(frame),
                    "loss_month_share": float((frame["loss_month"] == True).mean()),
                    "mean_position_return": pd.to_numeric(frame["net_return"], errors="coerce").mean(),
                    "median_position_return": pd.to_numeric(frame["net_return"], errors="coerce").median(),
                }
            )
    return pd.DataFrame(rows).sort_values(["dimension", "bucket"])


def build_symbol_frequency(enriched: pd.DataFrame) -> pd.DataFrame:
    loss = enriched[enriched["loss_month"] == True].copy()
    grouped = (
        loss.groupby("symbol", dropna=False)
        .agg(
            loss_month_count=("month", "nunique"),
            mean_return=("net_return", "mean"),
            mean_score=("score", "mean"),
        )
        .reset_index()
        .sort_values(["loss_month_count", "mean_return"], ascending=[False, True])
    )
    return grouped


def write_readout(summary: pd.DataFrame, loss_months: pd.DataFrame, buckets: pd.DataFrame, symbols: pd.DataFrame) -> None:
    loss_row = summary[summary["segment"] == "loss_months"].iloc[0]
    non_loss_row = summary[summary["segment"] == "non_loss_months"].iloc[0]
    lines = [
        "# Momentum Loss-Month Exposure Audit",
        "",
        f"- İncelenen negatif ay sayısı: `{int(loss_row['months'])}`",
        f"- Negatif ay seçili satır sayısı: `{int(loss_row['rows'])}`",
        f"- Negatif aylarda ağırlıklı market cap proxy: `{loss_row['weighted_market_cap_proxy']:.2f}`",
        f"- Diğer aylarda ağırlıklı market cap proxy: `{non_loss_row['weighted_market_cap_proxy']:.2f}`",
        f"- Negatif aylarda ağırlıklı 20g turnover: `{loss_row['weighted_avg_turnover_20d']:.2f}`",
        f"- Diğer aylarda ağırlıklı 20g turnover: `{non_loss_row['weighted_avg_turnover_20d']:.2f}`",
        f"- Negatif aylarda ağırlıklı 20g volatility: `{loss_row['weighted_volatility_20d']:.4f}`",
        f"- Diğer aylarda ağırlıklı 20g volatility: `{non_loss_row['weighted_volatility_20d']:.4f}`",
        "",
        "## İlk Okuma",
        "",
    ]
    if loss_row["weighted_market_cap_proxy"] < non_loss_row["weighted_market_cap_proxy"]:
        lines.append("- Negatif aylarda portföy daha küçük ölçekli isimlere kaymış görünüyor.")
    else:
        lines.append("- Negatif aylarda ölçek tarafında belirgin bir küçük-hisse kayması görünmüyor.")
    if loss_row["weighted_avg_turnover_20d"] < non_loss_row["weighted_avg_turnover_20d"]:
        lines.append("- Negatif aylarda likidite daha zayıf; bu, satış rejimlerinde kırılganlığı artırmış olabilir.")
    else:
        lines.append("- Negatif aylarda likidite belirgin biçimde bozulmuyor.")
    if loss_row["weighted_volatility_20d"] > non_loss_row["weighted_volatility_20d"]:
        lines.append("- Negatif aylarda seçilen isimler daha yüksek kısa dönem volatilite taşıyor.")
    else:
        lines.append("- Negatif aylarda volatilite tarafında belirgin ekstra risk görünmüyor.")
    top_symbol = symbols.iloc[0] if not symbols.empty else None
    if top_symbol is not None:
        lines.extend(
            [
                "",
                "## Tekrarlayan İsim",
                "",
                f"- En sık görünen sembol: `{top_symbol['symbol']}` (`{int(top_symbol['loss_month_count'])}` zarar ayında)",
            ]
        )
    (OUTPUT_DIR / "momentum_loss_exposure_readout.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings = load_config(CONFIG_PATH)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    run_id = latest_run_id(storage, CONFIG_PATH)
    monthly = storage.read_table("backtest_monthly_results")
    selected = storage.read_table("backtest_selected_positions")
    prices = storage.read_table("market_prices")
    storage.close()

    monthly = monthly[monthly["run_id"].astype(str) == run_id].copy()
    selected = selected[selected["run_id"].astype(str) == run_id].copy()
    price_features = build_price_features(prices)
    enriched = attach_exposures(selected, monthly, price_features)

    summary = summarize_by_month_type(enriched)
    loss_months = summarize_loss_months(enriched)
    buckets = summarize_loss_buckets(enriched)
    symbols = build_symbol_frequency(enriched)

    summary.to_csv(OUTPUT_DIR / "momentum_loss_exposure_summary.csv", index=False)
    loss_months.to_csv(OUTPUT_DIR / "momentum_loss_exposure_months.csv", index=False)
    buckets.to_csv(OUTPUT_DIR / "momentum_loss_exposure_buckets.csv", index=False)
    symbols.to_csv(OUTPUT_DIR / "momentum_loss_exposure_symbols.csv", index=False)
    write_readout(summary, loss_months, buckets, symbols)

    print("run_id", run_id)
    print((OUTPUT_DIR / "momentum_loss_exposure_readout.md").as_posix())


if __name__ == "__main__":
    main()

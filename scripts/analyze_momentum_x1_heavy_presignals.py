from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.storage import DuckDbStorage


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.formula_research_momentum.yaml"
OUTPUT_DIR = ROOT / "outputs/formula_research_reference"
REGIME_PATH = ROOT / "outputs/dashboard/momentum_watchlist/monthly_regimes.json"


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
    data["daily_return"] = data.groupby("symbol")[close_col].pct_change()
    data["recent_return_20d"] = data.groupby("symbol")[close_col].transform(lambda s: s.shift(1) / s.shift(21) - 1)
    data["recent_return_60d"] = data.groupby("symbol")[close_col].transform(lambda s: s.shift(1) / s.shift(61) - 1)
    data["volatility_20d"] = data.groupby("symbol")["daily_return"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=20).std(ddof=0)
    )
    return data[["symbol", "date", "recent_return_20d", "recent_return_60d", "volatility_20d"]]


def bucketize(series: pd.Series, labels: list[str]) -> pd.Series:
    ranked = series.rank(method="first", pct=True)
    return pd.cut(ranked, bins=[0.0, 1 / 3, 2 / 3, 1.0], labels=labels, include_lowest=True)


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
    monthly["loss_month"] = pd.to_numeric(monthly["net_return"], errors="coerce") < 0

    selected = selected.merge(monthly[["month", "net_return", "loss_month"]], on="month", how="left", suffixes=("", "_month"))
    selected["x_total"] = pd.to_numeric(selected["x1"], errors="coerce") + pd.to_numeric(selected["x2"], errors="coerce")
    selected["x1_share"] = pd.to_numeric(selected["x1"], errors="coerce") / selected["x_total"]
    selected = selected[selected["x1_share"] >= 0.70].copy()
    selected["buy_date"] = pd.to_datetime(selected["buy_date"], errors="coerce").dt.date

    price_features = build_price_features(prices)
    selected = selected.merge(price_features, left_on=["symbol", "buy_date"], right_on=["symbol", "date"], how="left")

    regimes = pd.DataFrame(json.loads(REGIME_PATH.read_text()))
    selected = selected.merge(regimes[["month", "breadth_200d", "regime_label", "regime_risk"]], on="month", how="left")

    summary_rows = []
    for label, frame in [
        ("loss_x1_heavy", selected[selected["loss_month"] == True]),
        ("ok_x1_heavy", selected[selected["loss_month"] == False]),
        ("all_x1_heavy", selected),
    ]:
        summary_rows.append(
            {
                "segment": label,
                "rows": len(frame),
                "months": int(frame["month"].nunique()) if not frame.empty else 0,
                "mean_position_return": pd.to_numeric(frame["net_return"], errors="coerce").mean(),
                "median_position_return": pd.to_numeric(frame["net_return"], errors="coerce").median(),
                "mean_score": pd.to_numeric(frame["score"], errors="coerce").mean(),
                "mean_x1_share": pd.to_numeric(frame["x1_share"], errors="coerce").mean(),
                "mean_recent_return_20d": pd.to_numeric(frame["recent_return_20d"], errors="coerce").mean(),
                "mean_recent_return_60d": pd.to_numeric(frame["recent_return_60d"], errors="coerce").mean(),
                "mean_volatility_20d": pd.to_numeric(frame["volatility_20d"], errors="coerce").mean(),
                "mean_breadth_200d": pd.to_numeric(frame["breadth_200d"], errors="coerce").mean(),
            }
        )
    summary = pd.DataFrame(summary_rows)

    data = selected.copy()
    data["ret20_bucket"] = bucketize(pd.to_numeric(data["recent_return_20d"], errors="coerce"), ["low", "mid", "high"])
    data["ret60_bucket"] = bucketize(pd.to_numeric(data["recent_return_60d"], errors="coerce"), ["low", "mid", "high"])
    data["breadth_bucket"] = bucketize(pd.to_numeric(data["breadth_200d"], errors="coerce"), ["weak", "mid", "strong"])
    bucket_rows = []
    for column in ["ret20_bucket", "ret60_bucket", "breadth_bucket", "regime_risk"]:
        subset = data[data[column].notna()].copy()
        for bucket, frame in subset.groupby(column, dropna=False):
            bucket_rows.append(
                {
                    "dimension": column,
                    "bucket": str(bucket),
                    "rows": len(frame),
                    "loss_month_share": float((frame["loss_month"] == True).mean()),
                    "mean_position_return": pd.to_numeric(frame["net_return"], errors="coerce").mean(),
                }
            )
    buckets = pd.DataFrame(bucket_rows).sort_values(["dimension", "bucket"])

    months = (
        data[data["loss_month"] == True]
        .groupby("month", dropna=False)
        .agg(
            month_net_return=("net_return_month", "first"),
            mean_recent_return_20d=("recent_return_20d", "mean"),
            mean_recent_return_60d=("recent_return_60d", "mean"),
            mean_breadth_200d=("breadth_200d", "mean"),
            regime_label=("regime_label", "first"),
            symbols=("symbol", lambda s: ",".join(s.astype(str))),
        )
        .reset_index()
        .sort_values("month")
    )

    summary.to_csv(OUTPUT_DIR / "momentum_x1_heavy_presignal_summary.csv", index=False)
    buckets.to_csv(OUTPUT_DIR / "momentum_x1_heavy_presignal_buckets.csv", index=False)
    months.to_csv(OUTPUT_DIR / "momentum_x1_heavy_presignal_months.csv", index=False)

    loss_row = summary[summary["segment"] == "loss_x1_heavy"].iloc[0]
    ok_row = summary[summary["segment"] == "ok_x1_heavy"].iloc[0]
    lines = [
        "# Momentum X1-Heavy Presignal Audit",
        "",
        f"- X1-heavy zarar ayı satırı: `{int(loss_row['rows'])}`",
        f"- X1-heavy normal ay satırı: `{int(ok_row['rows'])}`",
        f"- 20g getiri: zarar aylarında `{loss_row['mean_recent_return_20d']:.2%}`, diğer aylarda `{ok_row['mean_recent_return_20d']:.2%}`",
        f"- 60g getiri: zarar aylarında `{loss_row['mean_recent_return_60d']:.2%}`, diğer aylarda `{ok_row['mean_recent_return_60d']:.2%}`",
        f"- 20g volatilite: zarar aylarında `{loss_row['mean_volatility_20d']:.4f}`, diğer aylarda `{ok_row['mean_volatility_20d']:.4f}`",
        f"- 200g breadth: zarar aylarında `{loss_row['mean_breadth_200d']:.2%}`, diğer aylarda `{ok_row['mean_breadth_200d']:.2%}`",
        "",
        "## İlk Okuma",
        "",
    ]
    if loss_row["mean_breadth_200d"] < ok_row["mean_breadth_200d"]:
        lines.append("- X1-heavy kayıplar daha zayıf breadth rejimlerinde geliyor.")
    if loss_row["mean_recent_return_20d"] < ok_row["mean_recent_return_20d"]:
        lines.append("- X1-heavy kayıplarda kısa dönem momentum da daha zayıf.")
    if loss_row["mean_recent_return_60d"] < ok_row["mean_recent_return_60d"]:
        lines.append("- Orta dönem price strength de kayıp örneklerinde daha düşük.")
    if loss_row["mean_volatility_20d"] > ok_row["mean_volatility_20d"]:
        lines.append("- Kayıp örnekleri daha yüksek kısa dönem vol taşıyor.")
    (OUTPUT_DIR / "momentum_x1_heavy_presignal_readout.md").write_text("\n".join(lines), encoding="utf-8")
    print((OUTPUT_DIR / "momentum_x1_heavy_presignal_readout.md").as_posix())
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

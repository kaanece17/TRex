from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
TARGET_CONFIG = str(ROOT / "config.formula_research.yaml")


def _latest_run_id(con: duckdb.DuckDBPyConnection) -> str:
    row = con.execute(
        """
        select run_id
        from backtest_runs
        where notes = ?
        order by created_at desc
        limit 1
        """,
        [TARGET_CONFIG],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"no backtest run found for {TARGET_CONFIG}")
    return str(row[0])


def _load_selected(con: duckdb.DuckDBPyConnection, run_id: str) -> pd.DataFrame:
    selected = con.execute(
        """
        select
          run_id,
          month,
          symbol,
          score,
          x1,
          x2,
          buy_date,
          sell_date,
          net_return
        from backtest_selected_positions
        where run_id = ?
        """,
        [run_id],
    ).df()
    selected["buy_date"] = pd.to_datetime(selected["buy_date"], errors="coerce")
    selected["sell_date"] = pd.to_datetime(selected["sell_date"], errors="coerce")
    selected["net_return"] = pd.to_numeric(selected["net_return"], errors="coerce")
    selected = selected[selected["net_return"].notna()].copy()
    selected["score_rank_in_month"] = (
        selected.groupby("month")["score"].rank(method="first", ascending=False).astype(int)
    )
    selected["high_score"] = selected["score_rank_in_month"] <= 3
    return selected


def _build_price_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    prices = con.execute(
        """
        select symbol, date, adjusted_close, close, volume
        from market_prices
        order by symbol, date
        """
    ).df()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["adjusted_close"] = pd.to_numeric(prices["adjusted_close"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")
    prices = prices[prices["volume"].fillna(0) > 0].copy()
    prices["ret_20d"] = prices.groupby("symbol")["adjusted_close"].pct_change(20)
    prices["ret_60d"] = prices.groupby("symbol")["adjusted_close"].pct_change(60)
    prices["ma_200d"] = prices.groupby("symbol")["adjusted_close"].transform(lambda s: s.rolling(200).mean())
    prices["above_200dma"] = prices["adjusted_close"] > prices["ma_200d"]
    prices["dist_200dma"] = prices["adjusted_close"] / prices["ma_200d"] - 1
    return prices[["symbol", "date", "ret_20d", "ret_60d", "above_200dma", "dist_200dma"]].copy()


def _attach_signals(selected: pd.DataFrame, price_features: pd.DataFrame) -> pd.DataFrame:
    selected = selected[selected["buy_date"].notna()].copy()
    selected = selected.sort_values(["symbol", "buy_date"]).reset_index(drop=True)
    price_features = price_features[price_features["date"].notna()].copy()
    price_features = price_features.sort_values(["symbol", "date"]).reset_index(drop=True)
    pieces: list[pd.DataFrame] = []
    for symbol, left in selected.groupby("symbol", sort=False):
        right = price_features[price_features["symbol"] == symbol].copy()
        if right.empty:
            merged = left.copy()
            merged["date"] = pd.NaT
            merged["ret_20d"] = pd.NA
            merged["ret_60d"] = pd.NA
            merged["above_200dma"] = pd.NA
            merged["dist_200dma"] = pd.NA
        else:
            merged = pd.merge_asof(
                left.sort_values("buy_date"),
                right.sort_values("date"),
                left_on="buy_date",
                right_on="date",
                direction="backward",
                allow_exact_matches=False,
            )
        if "symbol_x" in merged.columns:
            merged["symbol"] = merged["symbol_x"]
            merged = merged.drop(columns=[col for col in ["symbol_x", "symbol_y"] if col in merged.columns])
        pieces.append(merged)
    enriched = pd.concat(pieces, ignore_index=True)
    enriched["weak_20d"] = enriched["ret_20d"] < 0
    enriched["weak_60d"] = enriched["ret_60d"] < 0
    enriched["below_200dma"] = ~enriched["above_200dma"].fillna(False)
    enriched["weak_combo_20_200"] = enriched["weak_20d"] & enriched["below_200dma"]
    enriched["weak_combo_60_200"] = enriched["weak_60d"] & enriched["below_200dma"]
    return enriched


def _summarize_segment(df: pd.DataFrame, label: str) -> dict[str, object]:
    if df.empty:
        return {
            "segment": label,
            "rows": 0,
            "mean_net_return": None,
            "median_net_return": None,
            "loss_ratio": None,
            "mean_score": None,
            "mean_ret_20d": None,
            "mean_ret_60d": None,
            "pct_below_200dma": None,
        }
    return {
        "segment": label,
        "rows": int(len(df)),
        "mean_net_return": float(df["net_return"].mean()),
        "median_net_return": float(df["net_return"].median()),
        "loss_ratio": float((df["net_return"] < 0).mean()),
        "mean_score": float(df["score"].mean()),
        "mean_ret_20d": float(df["ret_20d"].mean()),
        "mean_ret_60d": float(df["ret_60d"].mean()),
        "pct_below_200dma": float(df["below_200dma"].mean()),
    }


def _build_summary(enriched: pd.DataFrame) -> pd.DataFrame:
    high = enriched[enriched["high_score"]].copy()
    segments = [
        _summarize_segment(enriched, "all_realized"),
        _summarize_segment(high, "high_score_rank_le_3"),
        _summarize_segment(high[high["weak_20d"]], "high_score_and_20d_negative"),
        _summarize_segment(high[~high["weak_20d"]], "high_score_and_20d_nonnegative"),
        _summarize_segment(high[high["weak_60d"]], "high_score_and_60d_negative"),
        _summarize_segment(high[~high["weak_60d"]], "high_score_and_60d_nonnegative"),
        _summarize_segment(high[high["below_200dma"]], "high_score_and_below_200dma"),
        _summarize_segment(high[~high["below_200dma"]], "high_score_and_above_200dma"),
        _summarize_segment(high[high["weak_combo_20_200"]], "high_score_and_20d_negative_and_below_200dma"),
        _summarize_segment(high[high["weak_combo_60_200"]], "high_score_and_60d_negative_and_below_200dma"),
    ]
    return pd.DataFrame(segments)


def _build_examples(enriched: pd.DataFrame) -> pd.DataFrame:
    high = enriched[enriched["high_score"]].copy()
    flagged = high[
        high["weak_20d"] | high["weak_60d"] | high["below_200dma"]
    ].copy()
    flagged = flagged.sort_values(["net_return", "month", "score"], ascending=[True, True, False])
    cols = [
        "month",
        "symbol",
        "score",
        "score_rank_in_month",
        "x1",
        "x2",
        "ret_20d",
        "ret_60d",
        "above_200dma",
        "dist_200dma",
        "net_return",
    ]
    return flagged[cols].head(80)


def _build_bucket_table(enriched: pd.DataFrame) -> pd.DataFrame:
    high = enriched[enriched["high_score"]].copy()
    rows: list[dict[str, object]] = []
    for signal in ["weak_20d", "weak_60d", "below_200dma", "weak_combo_20_200", "weak_combo_60_200"]:
        signal_df = high[high[signal]].copy()
        other_df = high[~high[signal]].copy()
        rows.append(
            {
                "signal": signal,
                "flagged_rows": int(len(signal_df)),
                "other_rows": int(len(other_df)),
                "flagged_mean_return": float(signal_df["net_return"].mean()) if not signal_df.empty else None,
                "other_mean_return": float(other_df["net_return"].mean()) if not other_df.empty else None,
                "flagged_median_return": float(signal_df["net_return"].median()) if not signal_df.empty else None,
                "other_median_return": float(other_df["net_return"].median()) if not other_df.empty else None,
                "flagged_loss_ratio": float((signal_df["net_return"] < 0).mean()) if not signal_df.empty else None,
                "other_loss_ratio": float((other_df["net_return"] < 0).mean()) if not other_df.empty else None,
            }
        )
    return pd.DataFrame(rows)


def _write_readout(run_id: str, summary: pd.DataFrame, buckets: pd.DataFrame) -> None:
    lines = [
        f"run_id: {run_id}",
        "",
        "High-score tanimi: ay icinde score rank <= 3",
        "Teknik sinyaller: 20g momentum, 60g momentum, 200g ustu/alti",
        "",
        "Ozet:",
    ]
    for row in summary.to_dict(orient="records"):
        if row["rows"] == 0:
            continue
        lines.append(
            f"- {row['segment']}: n={row['rows']}, avg={row['mean_net_return']:.4f}, "
            f"median={row['median_net_return']:.4f}, loss={row['loss_ratio']:.2%}"
        )
    lines.extend(["", "Signal farklari:"])
    for row in buckets.to_dict(orient="records"):
        lines.append(
            f"- {row['signal']}: flagged_avg={row['flagged_mean_return']:.4f} "
            f"vs other_avg={row['other_mean_return']:.4f}, "
            f"flagged_loss={row['flagged_loss_ratio']:.2%} vs other_loss={row['other_loss_ratio']:.2%}"
        )
    (OUTPUT_DIR / "accepted_top6_high_score_technical_readout.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    run_id = _latest_run_id(con)
    selected = _load_selected(con, run_id)
    price_features = _build_price_features(con)
    enriched = _attach_signals(selected, price_features)
    summary = _build_summary(enriched)
    buckets = _build_bucket_table(enriched)
    examples = _build_examples(enriched)
    summary.to_csv(OUTPUT_DIR / "accepted_top6_high_score_technical_summary.csv", index=False)
    buckets.to_csv(OUTPUT_DIR / "accepted_top6_high_score_technical_buckets.csv", index=False)
    examples.to_csv(OUTPUT_DIR / "accepted_top6_high_score_technical_examples.csv", index=False)
    (OUTPUT_DIR / "accepted_top6_high_score_technical_bundle.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "rows": len(enriched),
                "summary": summary.to_dict(orient="records"),
                "buckets": buckets.to_dict(orient="records"),
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_readout(run_id, summary, buckets)
    print(run_id)


if __name__ == "__main__":
    main()

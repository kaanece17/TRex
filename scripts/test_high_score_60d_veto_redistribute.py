from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
TARGET_CONFIG = str(ROOT / "config.formula_research.yaml")
INITIAL_CAPITAL = 100_000.0


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


def _build_price_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    prices = con.execute(
        """
        select symbol, date, adjusted_close, volume
        from market_prices
        order by symbol, date
        """
    ).df()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["adjusted_close"] = pd.to_numeric(prices["adjusted_close"], errors="coerce")
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")
    prices = prices[prices["volume"].fillna(0) > 0].copy()
    prices = prices.sort_values(["symbol", "date"])
    prices["ret_60d"] = prices.groupby("symbol")["adjusted_close"].pct_change(60)
    return prices[["symbol", "date", "ret_60d"]].copy()


def _attach_60d(selected: pd.DataFrame, price_features: pd.DataFrame) -> pd.DataFrame:
    selected = selected.copy()
    selected["buy_date"] = pd.to_datetime(selected["buy_date"], errors="coerce").astype("datetime64[ns]")
    pieces: list[pd.DataFrame] = []
    for symbol, left in selected.groupby("symbol", sort=False):
        right = price_features[price_features["symbol"] == symbol].copy()
        if right.empty:
            merged = left.copy()
            merged["ret_60d"] = pd.NA
        else:
            right["date"] = pd.to_datetime(right["date"], errors="coerce").astype("datetime64[ns]")
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
    enriched["score_rank_in_month"] = (
        enriched.groupby("month")["score"].rank(method="first", ascending=False).astype(int)
    )
    enriched["high_score"] = enriched["score_rank_in_month"] <= 3
    enriched["weak_60d"] = enriched["ret_60d"] < 0
    enriched["vetoed"] = enriched["high_score"] & enriched["weak_60d"].fillna(False)
    return enriched


def _load_run(con: duckdb.DuckDBPyConnection, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = con.execute(
        """
        select
          run_id, month, symbol, weight, score, x1, x2,
          buy_date, sell_date, net_return
        from backtest_selected_positions
        where run_id = ?
        """,
        [run_id],
    ).df()
    monthly = con.execute(
        """
        select month, net_return
        from backtest_monthly_results
        where run_id = ?
        order by month
        """,
        [run_id],
    ).df()
    selected["net_return"] = pd.to_numeric(selected["net_return"], errors="coerce")
    return selected, monthly


def _simulate_redistributed(selected: pd.DataFrame, baseline_monthly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    portfolio_value = INITIAL_CAPITAL
    for month, month_df in selected.groupby("month", sort=True):
        surviving = month_df[~month_df["vetoed"]].copy()
        base_month_return = float(
            baseline_monthly.loc[baseline_monthly["month"] == month, "net_return"].iloc[0]
        )
        if surviving.empty:
            adjusted_return = 0.0
        else:
            surviving["adj_weight"] = surviving["weight"] / surviving["weight"].sum()
            adjusted_return = float((surviving["adj_weight"] * surviving["net_return"]).sum())
        start_value = portfolio_value
        portfolio_value = portfolio_value * (1 + adjusted_return)
        rows.append(
            {
                "month": month,
                "baseline_month_return": base_month_return,
                "adjusted_month_return": adjusted_return,
                "return_delta": adjusted_return - base_month_return,
                "selected_count": int(len(month_df)),
                "surviving_count": int(len(surviving)),
                "vetoed_count": int(month_df["vetoed"].sum()),
                "portfolio_value_start": start_value,
                "portfolio_value_end": portfolio_value,
                "vetoed_symbols": ", ".join(month_df.loc[month_df["vetoed"], "symbol"].astype(str).tolist()),
                "surviving_symbols": ", ".join(surviving["symbol"].astype(str).tolist()),
            }
        )
    return pd.DataFrame(rows)


def _period_summary(adjusted_monthly: pd.DataFrame) -> pd.DataFrame:
    periods = {
        "full_period": adjusted_monthly["month"].astype(str).tolist(),
        "2024_2026": adjusted_monthly[
            adjusted_monthly["month"].astype(str).str.startswith(("2024-", "2025-", "2026-"))
        ]["month"].astype(str).tolist(),
    }
    rows = []
    for label, months in periods.items():
        subset = adjusted_monthly[adjusted_monthly["month"].isin(months)].copy()
        if subset.empty:
            continue
        rows.append(
            {
                "period": label,
                "baseline_multiple": float((1 + subset["baseline_month_return"]).prod()),
                "adjusted_multiple": float((1 + subset["adjusted_month_return"]).prod()),
                "avg_adjusted_month_return": float(subset["adjusted_month_return"].mean()),
                "avg_surviving_count": float(subset["surviving_count"].mean()),
                "avg_vetoed_count": float(subset["vetoed_count"].mean()),
                "changed_month_ratio": float((subset["vetoed_count"] > 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def _write_readout(run_id: str, summary: pd.DataFrame, monthly: pd.DataFrame) -> None:
    best = monthly.sort_values("return_delta", ascending=False).head(10)
    worst = monthly.sort_values("return_delta").head(10)
    lines = [
        f"run_id: {run_id}",
        "",
        "Kural: high-score (score rank <= 3) ve 60g momentum negatif olan isimleri cikar,",
        "yerine alt listeden aday koyma; bosalan agirligi kalan hisselere yeniden dagit.",
        "",
        "Donem ozeti:",
    ]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"- {row['period']}: baseline={row['baseline_multiple']:.4f}x, adjusted={row['adjusted_multiple']:.4f}x, "
            f"avg_surviving={row['avg_surviving_count']:.2f}, changed_months={row['changed_month_ratio']:.2%}"
        )
    lines.extend(["", "En iyi ay farklari:"])
    for row in best.to_dict(orient="records"):
        lines.append(f"- {row['month']}: delta={row['return_delta']:.4f}, vetoed={row['vetoed_symbols']}")
    lines.extend(["", "En kotu ay farklari:"])
    for row in worst.to_dict(orient="records"):
        lines.append(f"- {row['month']}: delta={row['return_delta']:.4f}, vetoed={row['vetoed_symbols']}")
    (OUTPUT_DIR / "accepted_top6_high_score_60d_veto_redistribute_readout.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    run_id = _latest_run_id(con)
    selected, baseline_monthly = _load_run(con, run_id)
    price_features = _build_price_features(con)
    selected = _attach_60d(selected, price_features)
    adjusted_monthly = _simulate_redistributed(selected, baseline_monthly)
    summary = _period_summary(adjusted_monthly)

    selected.to_csv(OUTPUT_DIR / "accepted_top6_high_score_60d_veto_redistribute_selected.csv", index=False)
    adjusted_monthly.to_csv(OUTPUT_DIR / "accepted_top6_high_score_60d_veto_redistribute_monthly.csv", index=False)
    summary.to_csv(OUTPUT_DIR / "accepted_top6_high_score_60d_veto_redistribute_summary.csv", index=False)
    _write_readout(run_id, summary, adjusted_monthly)
    print(run_id)


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.cli import _load_membership_for_run


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.formula_research.yaml"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


def _build_price_features(prices: pd.DataFrame) -> pd.DataFrame:
    price_data = prices.copy()
    price_data["date"] = pd.to_datetime(price_data["date"], errors="coerce")
    price_data["adjusted_close"] = pd.to_numeric(price_data["adjusted_close"], errors="coerce")
    price_data["volume"] = pd.to_numeric(price_data["volume"], errors="coerce")
    price_data = price_data[price_data["volume"].fillna(0) > 0].copy()
    price_data = price_data.sort_values(["symbol", "date"])
    price_data["ret_20d"] = price_data.groupby("symbol")["adjusted_close"].pct_change(20)
    price_data["ret_60d"] = price_data.groupby("symbol")["adjusted_close"].pct_change(60)
    price_data["ma_200d"] = (
        price_data.groupby("symbol")["adjusted_close"].transform(lambda s: s.rolling(200).mean())
    )
    price_data["above_200dma"] = price_data["adjusted_close"] > price_data["ma_200d"]
    return price_data[["symbol", "date", "ret_20d", "ret_60d", "above_200dma"]].copy()


def _attach_price_signals(candidates: pd.DataFrame, price_features: pd.DataFrame) -> pd.DataFrame:
    candidates = candidates.copy()
    candidates["buy_date"] = pd.to_datetime(candidates["buy_date"], errors="coerce")
    pieces: list[pd.DataFrame] = []
    for symbol, left in candidates.groupby("symbol", sort=False):
        right = price_features[price_features["symbol"] == symbol].copy()
        if right.empty:
            merged = left.copy()
            merged["ret_20d"] = pd.NA
            merged["ret_60d"] = pd.NA
            merged["above_200dma"] = pd.NA
        else:
            left = left.copy()
            right = right.copy()
            left["buy_date"] = left["buy_date"].astype("datetime64[ns]")
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
    enriched["weak_20d"] = enriched["ret_20d"] < 0
    enriched["weak_60d"] = enriched["ret_60d"] < 0
    enriched["below_200dma"] = ~enriched["above_200dma"].fillna(False)
    return enriched


def _eligible_ranked(result: dict[str, pd.DataFrame | str], price_features: pd.DataFrame) -> pd.DataFrame:
    diagnostics = result["candidate_diagnostics"].copy()
    rejected = result["rejected_candidates"].copy()
    diagnostics["buy_date"] = pd.to_datetime(diagnostics["buy_date"], errors="coerce")
    rejected["buy_date"] = pd.to_datetime(rejected.get("buy_date"), errors="coerce")
    reject_keys = set()
    if not rejected.empty and {"month", "symbol"}.issubset(rejected.columns):
        reject_keys = set(
            zip(rejected["month"].astype(str), rejected["symbol"].astype(str))
        )
    ranked = diagnostics[
        ~diagnostics.apply(lambda row: (str(row["month"]), str(row["symbol"])) in reject_keys, axis=1)
    ].copy()
    ranked = ranked.sort_values(["month", "provisional_rank"])
    ranked = _attach_price_signals(ranked, price_features)
    return ranked


def _selected_table(result: dict[str, pd.DataFrame | str], price_features: pd.DataFrame) -> pd.DataFrame:
    planned = result["planned_positions"].copy()
    planned["buy_date"] = pd.to_datetime(planned["buy_date"], errors="coerce")
    planned["score_rank_in_month"] = (
        planned.groupby("month")["score"].rank(method="first", ascending=False).astype(int)
    )
    planned["high_score"] = planned["score_rank_in_month"] <= 3
    return _attach_price_signals(planned, price_features)


def _analyze_signal(
    selected: pd.DataFrame,
    ranked: pd.DataFrame,
    signal_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly_rows: list[dict[str, object]] = []
    swap_rows: list[dict[str, object]] = []
    for month, selected_month in selected.groupby("month", sort=True):
        ranked_month = ranked[ranked["month"] == month].copy()
        base_symbols = selected_month["symbol"].astype(str).tolist()
        flagged = selected_month[
            selected_month["high_score"] & selected_month[signal_col].fillna(False)
        ].copy()
        flagged_symbols = flagged["symbol"].astype(str).tolist()
        alt_symbols = [symbol for symbol in base_symbols if symbol not in flagged_symbols]
        replacement_pool = ranked_month[~ranked_month["symbol"].astype(str).isin(alt_symbols)].copy()
        replacement_pool = replacement_pool[~replacement_pool["symbol"].astype(str).isin(flagged_symbols)].copy()
        needed = max(len(base_symbols) - len(alt_symbols), 0)
        replacements = replacement_pool.head(needed)["symbol"].astype(str).tolist()
        alt_symbols.extend(replacements)
        monthly_rows.append(
            {
                "signal": signal_col,
                "month": month,
                "base_count": len(base_symbols),
                "flagged_selected_count": len(flagged_symbols),
                "swap_count": len(replacements),
                "changed": len(replacements) > 0,
                "flagged_symbols": ", ".join(flagged_symbols),
                "replacement_symbols": ", ".join(replacements),
                "base_symbols": ", ".join(base_symbols),
                "alt_symbols": ", ".join(alt_symbols),
            }
        )
        for flagged_symbol, replacement_symbol in zip(flagged_symbols, replacements):
            flagged_row = flagged[flagged["symbol"].astype(str) == flagged_symbol].iloc[0]
            replacement_row = ranked_month[ranked_month["symbol"].astype(str) == replacement_symbol].iloc[0]
            swap_rows.append(
                {
                    "signal": signal_col,
                    "month": month,
                    "flagged_symbol": flagged_symbol,
                    "flagged_score": float(flagged_row["score"]),
                    "flagged_ret_20d": float(flagged_row["ret_20d"]) if pd.notna(flagged_row["ret_20d"]) else None,
                    "flagged_ret_60d": float(flagged_row["ret_60d"]) if pd.notna(flagged_row["ret_60d"]) else None,
                    "replacement_symbol": replacement_symbol,
                    "replacement_rank": int(replacement_row["provisional_rank"]),
                    "replacement_score": float(replacement_row["score"]),
                    "replacement_ret_20d": float(replacement_row["ret_20d"]) if pd.notna(replacement_row["ret_20d"]) else None,
                    "replacement_ret_60d": float(replacement_row["ret_60d"]) if pd.notna(replacement_row["ret_60d"]) else None,
                }
            )
    return pd.DataFrame(monthly_rows), pd.DataFrame(swap_rows)


def _write_readout(summary: pd.DataFrame) -> None:
    lines = ["High-score teknik confirmation swap analizi", ""]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"- {row['signal']}: changed_months={row['changed_months']}, "
            f"total_flagged_selected={row['total_flagged_selected']}, total_replacements={row['total_replacements']}"
        )
    (OUTPUT_DIR / "accepted_top6_high_score_technical_swaps_readout.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings = load_config(CONFIG_PATH)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    membership = _load_membership_for_run(settings)
    storage.close()

    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    price_features = _build_price_features(prices)
    ranked = _eligible_ranked(result, price_features)
    selected = _selected_table(result, price_features)

    summaries: list[dict[str, object]] = []
    monthly_frames = []
    swap_frames = []
    for signal in ["weak_20d", "weak_60d", "below_200dma"]:
        monthly, swaps = _analyze_signal(selected, ranked, signal)
        monthly_frames.append(monthly)
        swap_frames.append(swaps)
        summaries.append(
            {
                "signal": signal,
                "months": int(len(monthly)),
                "changed_months": int(monthly["changed"].sum()),
                "total_flagged_selected": int(monthly["flagged_selected_count"].sum()),
                "total_replacements": int(monthly["swap_count"].sum()),
            }
        )

    summary_df = pd.DataFrame(summaries)
    monthly_df = pd.concat(monthly_frames, ignore_index=True)
    swaps_df = pd.concat(swap_frames, ignore_index=True) if swap_frames else pd.DataFrame()

    summary_df.to_csv(OUTPUT_DIR / "accepted_top6_high_score_technical_swaps_summary.csv", index=False)
    monthly_df.to_csv(OUTPUT_DIR / "accepted_top6_high_score_technical_swaps_monthly.csv", index=False)
    swaps_df.to_csv(OUTPUT_DIR / "accepted_top6_high_score_technical_swaps_examples.csv", index=False)
    _write_readout(summary_df)
    print(result["run_id"])


if __name__ == "__main__":
    main()

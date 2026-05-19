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
    data["recent_return_20d"] = data.groupby("symbol")[close_col].transform(lambda s: s.shift(1) / s.shift(21) - 1)
    data["recent_return_60d"] = data.groupby("symbol")[close_col].transform(lambda s: s.shift(1) / s.shift(61) - 1)
    return data[["symbol", "date", "recent_return_20d", "recent_return_60d"]]


def load_base_data() -> tuple[pd.DataFrame, pd.DataFrame]:
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
    selected["buy_date"] = pd.to_datetime(selected["buy_date"], errors="coerce").dt.date
    selected["x_total"] = pd.to_numeric(selected["x1"], errors="coerce") + pd.to_numeric(selected["x2"], errors="coerce")
    selected["x1_share"] = pd.to_numeric(selected["x1"], errors="coerce") / selected["x_total"]
    selected = selected.merge(build_price_features(prices), left_on=["symbol", "buy_date"], right_on=["symbol", "date"], how="left")
    return monthly, selected


def simulate_variant(
    monthly: pd.DataFrame,
    selected: pd.DataFrame,
    x1_share_threshold: float,
    ret20_threshold: float | None,
    ret60_threshold: float | None,
) -> dict[str, object]:
    adjusted_monthly = monthly.copy()
    adjusted_monthly["month"] = adjusted_monthly["month"].astype(str)
    selected = selected.copy()
    selected["month"] = selected["month"].astype(str)

    removed_total = 0
    triggered_months = 0
    avg_names = 0.0

    new_returns: list[tuple[str, float]] = []
    for month, month_positions in selected.groupby("month", dropna=False):
        frame = month_positions.copy()
        veto = frame["x1_share"].ge(x1_share_threshold)
        if ret20_threshold is not None:
            veto &= pd.to_numeric(frame["recent_return_20d"], errors="coerce").lt(ret20_threshold)
        if ret60_threshold is not None:
            veto &= pd.to_numeric(frame["recent_return_60d"], errors="coerce").lt(ret60_threshold)

        survivors = frame[~veto].copy()
        removed = int(veto.sum())
        removed_total += removed
        if removed > 0:
            triggered_months += 1

        if survivors.empty:
            month_return = 0.0
            avg_names += 0
        else:
            survivors["weight"] = pd.to_numeric(survivors["weight"], errors="coerce")
            survivors["net_return"] = pd.to_numeric(survivors["net_return"], errors="coerce")
            survivors["weight"] = survivors["weight"] / survivors["weight"].sum()
            month_return = float((survivors["weight"] * survivors["net_return"]).sum())
            avg_names += len(survivors)
        new_returns.append((month, month_return))

    new_returns_df = pd.DataFrame(new_returns, columns=["month", "net_return"])
    adjusted_monthly = adjusted_monthly.merge(new_returns_df, on="month", how="left", suffixes=("", "_sim"))
    adjusted_monthly["net_return_sim"] = adjusted_monthly["net_return_sim"].fillna(pd.to_numeric(adjusted_monthly["net_return"], errors="coerce"))
    adjusted_monthly = adjusted_monthly.sort_values("month").reset_index(drop=True)

    initial_capital = float(pd.to_numeric(adjusted_monthly["portfolio_value_start"], errors="coerce").iloc[0])
    capital = initial_capital
    path = []
    for _, row in adjusted_monthly.iterrows():
        capital *= 1 + float(row["net_return_sim"])
        path.append(capital)
    adjusted_monthly["portfolio_value_end_sim"] = path

    returns = pd.to_numeric(adjusted_monthly["net_return_sim"], errors="coerce")
    equity = pd.Series(path)
    peak = equity.cummax()
    drawdown = (equity / peak) - 1
    after_2024 = adjusted_monthly[adjusted_monthly["month"].astype(str) >= "2024-01"].copy()
    multiple_2024 = None
    if not after_2024.empty:
        start_2024 = float(pd.to_numeric(after_2024["portfolio_value_start"], errors="coerce").iloc[0])
        end_2024 = float(after_2024["portfolio_value_end_sim"].iloc[-1])
        multiple_2024 = end_2024 / start_2024 if start_2024 else None

    return {
        "variant": variant_name(x1_share_threshold, ret20_threshold, ret60_threshold),
        "x1_share_threshold": x1_share_threshold,
        "ret20_threshold": ret20_threshold,
        "ret60_threshold": ret60_threshold,
        "final_multiple": capital / initial_capital if initial_capital else None,
        "win_rate": float((returns > 0).mean()),
        "max_drawdown": float(drawdown.min()),
        "negative_months": int((returns < 0).sum()),
        "multiple_2024_2026": multiple_2024,
        "triggered_months": triggered_months,
        "removed_positions": removed_total,
        "avg_survivor_count": avg_names / max(len(new_returns), 1),
    }


def variant_name(x1_share_threshold: float, ret20_threshold: float | None, ret60_threshold: float | None) -> str:
    ret20 = "na" if ret20_threshold is None else str(int(ret20_threshold * 100))
    ret60 = "na" if ret60_threshold is None else str(int(ret60_threshold * 100))
    return f"x1_{int(x1_share_threshold*100)}_r20_{ret20}_r60_{ret60}"


def write_readout(summary: pd.DataFrame) -> None:
    best = summary.sort_values(["final_multiple", "max_drawdown"], ascending=[False, False]).iloc[0]
    base = summary[summary["variant"] == "base"].iloc[0]
    lines = [
        "# Momentum X1-Heavy Guard Candidate",
        "",
        f"- Base multiple: `{base['final_multiple']:.2f}x`",
        f"- En iyi varyant: `{best['variant']}`",
        f"- En iyi varyant multiple: `{best['final_multiple']:.2f}x`",
        f"- Base 2024-2026: `{base['multiple_2024_2026']:.2f}x`",
        f"- En iyi varyant 2024-2026: `{best['multiple_2024_2026']:.2f}x`",
        "",
        "## Not",
        "",
        "- Bu çalışma ana koda dokunmadan, seçili pozisyonlar üzerinde veto+redistribute simülasyonudur.",
    ]
    (OUTPUT_DIR / "momentum_x1_guard_candidate_readout.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    monthly, selected = load_base_data()

    variants = [
        (None, None, None),  # base
        (0.70, 0.05, None),
        (0.70, 0.10, None),
        (0.70, None, 0.15),
        (0.70, None, 0.20),
        (0.70, 0.05, 0.15),
        (0.70, 0.10, 0.20),
        (0.80, 0.05, None),
        (0.80, 0.10, None),
        (0.80, None, 0.15),
        (0.80, None, 0.20),
        (0.80, 0.05, 0.15),
        (0.80, 0.10, 0.20),
    ]
    rows = []
    for x1_thr, ret20_thr, ret60_thr in variants:
        if x1_thr is None:
            rows.append(
                {
                    "variant": "base",
                    "x1_share_threshold": None,
                    "ret20_threshold": None,
                    "ret60_threshold": None,
                    "final_multiple": float(pd.to_numeric(monthly["portfolio_value_end"], errors="coerce").iloc[-1])
                    / float(pd.to_numeric(monthly["portfolio_value_start"], errors="coerce").iloc[0]),
                    "win_rate": float((pd.to_numeric(monthly["net_return"], errors="coerce") > 0).mean()),
                    "max_drawdown": float((pd.to_numeric(monthly["portfolio_value_end"], errors="coerce") / pd.to_numeric(monthly["portfolio_value_end"], errors="coerce").cummax() - 1).min()),
                    "negative_months": int((pd.to_numeric(monthly["net_return"], errors="coerce") < 0).sum()),
                    "multiple_2024_2026": float(
                        pd.to_numeric(monthly[monthly["month"].astype(str) >= "2024-01"]["portfolio_value_end"], errors="coerce").iloc[-1]
                    )
                    / float(pd.to_numeric(monthly[monthly["month"].astype(str) >= "2024-01"]["portfolio_value_start"], errors="coerce").iloc[0]),
                    "triggered_months": 0,
                    "removed_positions": 0,
                    "avg_survivor_count": float(selected.groupby("month").size().mean()),
                }
            )
            continue
        rows.append(simulate_variant(monthly, selected, x1_thr, ret20_thr, ret60_thr))

    summary = pd.DataFrame(rows).sort_values("final_multiple", ascending=False)
    summary.to_csv(OUTPUT_DIR / "momentum_x1_guard_candidate_summary.csv", index=False)
    write_readout(summary)
    print((OUTPUT_DIR / "momentum_x1_guard_candidate_readout.md").as_posix())
    print(summary.head(20).to_string(index=False))


if __name__ == "__main__":
    main()

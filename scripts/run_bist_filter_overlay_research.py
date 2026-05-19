from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.formula_research_momentum.yaml"
DB_PATH = ROOT / "data/bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs/formula_research_reference"
SUMMARY_CSV = OUTPUT_DIR / "bist_filter_overlay_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "bist_filter_overlay_monthly.csv"
README_MD = OUTPUT_DIR / "bist_filter_overlay_readout.md"


VARIANTS = [
    {
        "name": "baseline",
        "notes": "Current accepted baseline.",
        "filters": {},
        "strategy": {},
    },
    {
        "name": "turnover_25m",
        "notes": "Raise minimum 20d turnover to 25M.",
        "filters": {"min_avg_turnover_20d": 25_000_000},
        "strategy": {},
    },
    {
        "name": "firm_value_1b",
        "notes": "Require firm value of at least 1B.",
        "filters": {"min_firm_value": 1_000_000_000},
        "strategy": {},
    },
    {
        "name": "turn25m_fv1b",
        "notes": "Liquidity + size floor together.",
        "filters": {"min_avg_turnover_20d": 25_000_000, "min_firm_value": 1_000_000_000},
        "strategy": {},
    },
    {
        "name": "hold_buffer_7",
        "notes": "Keep existing names when still inside top 7.",
        "filters": {},
        "strategy": {"hold_buffer_rank": 7},
    },
    {
        "name": "turn25m_hold7",
        "notes": "Liquidity floor with a mild hold buffer.",
        "filters": {"min_avg_turnover_20d": 25_000_000},
        "strategy": {"hold_buffer_rank": 7},
    },
]


def _load_inputs() -> tuple[BacktestConfig, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = load_config(CONFIG_PATH)
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    membership = storage.read_table("universe_membership")
    storage.close()
    return config, prices, financials, membership


def _period_multiple(monthly: pd.DataFrame, start_month: str) -> float | None:
    subset = monthly[monthly["month"] >= start_month].copy()
    if subset.empty:
        return None
    start_value = float(subset["portfolio_value_start"].iloc[0])
    end_value = float(subset["portfolio_value_end"].iloc[-1])
    if start_value <= 0:
        return None
    return end_value / start_value


def _summarize(name: str, notes: str, monthly: pd.DataFrame) -> dict[str, object]:
    curve = monthly["portfolio_value_end"].astype(float)
    return {
        "variant": name,
        "notes": notes,
        "months": len(monthly),
        "final_capital": float(curve.iloc[-1]),
        "multiple": float(curve.iloc[-1] / 100000.0),
        "win_rate": float((monthly["net_return"] > 0).mean()),
        "max_drawdown": float(((curve / curve.cummax()) - 1).min()),
        "avg_monthly_return": float(monthly["net_return"].mean()),
        "period_2024_plus": _period_multiple(monthly, "2024-01"),
    }


def _run_variant(
    variant: dict[str, object],
    base_config: BacktestConfig,
    prices: pd.DataFrame,
    financials: pd.DataFrame,
    membership: pd.DataFrame,
) -> tuple[dict[str, object], pd.DataFrame]:
    config = base_config.model_copy(deep=True)
    for key, value in variant["filters"].items():
        setattr(config.filters, key, value)
    for key, value in variant["strategy"].items():
        setattr(config.strategy, key, value)
    result = run_monthly_rotation_backtest(
        config,
        prices,
        financials,
        membership,
        collect_diagnostics=False,
        collect_positions=False,
    )
    monthly = result["monthly_results"].copy()
    monthly["variant"] = variant["name"]
    summary = _summarize(variant["name"], variant["notes"], monthly)
    return summary, monthly


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_config, prices, financials, membership = _load_inputs()
    summary_rows: list[dict[str, object]] = []
    monthly_frames: list[pd.DataFrame] = []
    for variant in VARIANTS:
        summary, monthly = _run_variant(variant, base_config, prices, financials, membership)
        summary_rows.append(summary)
        monthly_frames.append(monthly)

    summary_df = pd.DataFrame(summary_rows).sort_values(["multiple", "max_drawdown"], ascending=[False, False]).reset_index(drop=True)
    monthly_df = pd.concat(monthly_frames, ignore_index=True)
    summary_df.to_csv(SUMMARY_CSV, index=False)
    monthly_df.to_csv(MONTHLY_CSV, index=False)

    top = summary_df.iloc[0]
    lines = [
        "# BIST Filter Overlay Research",
        "",
        f"- Variant count: `{len(summary_df)}`",
        f"- Winner: `{top['variant']}`",
        f"- Winner multiple: `{top['multiple']:.2f}x`",
        f"- Winner 2024+: `{top['period_2024_plus']:.2f}x`" if pd.notna(top["period_2024_plus"]) else "- Winner 2024+: `n/a`",
        f"- Winner max drawdown: `{top['max_drawdown']:.2%}`",
        "",
        "## Ranking",
        "",
    ]
    for row in summary_df.to_dict("records"):
        period_text = f"{row['period_2024_plus']:.2f}x" if pd.notna(row["period_2024_plus"]) else "n/a"
        lines.append(
            f"- `{row['variant']}`: `{row['multiple']:.2f}x`, `2024+ {period_text}`, "
            f"win `{row['win_rate']:.2%}`, max DD `{row['max_drawdown']:.2%}`"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()

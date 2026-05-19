from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.storage import DuckDbStorage


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.formula_research_momentum.yaml"
DB_PATH = ROOT / "data/bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs/formula_research_reference"
SUMMARY_CSV = OUTPUT_DIR / "bist_earnings_quality_proxy_refine_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "bist_earnings_quality_proxy_refine_monthly.csv"
README_MD = OUTPUT_DIR / "bist_earnings_quality_proxy_refine_readout.md"


VARIANTS = [
    ("baseline", None, None, "Current accepted baseline."),
    ("combo_25_35", 2.5, 3.5, "Tighter caps on yoy growth and acceleration."),
    ("combo_31_46", 3.1, 4.6, "Current evidence-based combined cap."),
    ("combo_40_60", 4.0, 6.0, "Looser caps on yoy growth and acceleration."),
    ("combo_31_only", 3.1, None, "Only yoy growth cap."),
    ("combo_46_only", None, 4.6, "Only acceleration cap."),
]


def _load_inputs():
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


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_config, prices, financials, membership = _load_inputs()

    summary_rows = []
    monthly_frames = []
    for name, max_yoy, max_accel, notes in VARIANTS:
        config = base_config.model_copy(deep=True)
        config.filters.max_ni_ttm_growth_yoy = max_yoy
        config.filters.max_earnings_acceleration = max_accel
        result = run_monthly_rotation_backtest(
            config,
            prices,
            financials,
            membership,
            collect_diagnostics=False,
            collect_positions=False,
        )
        monthly = result["monthly_results"].copy()
        monthly["variant"] = name
        monthly_frames.append(monthly)
        curve = monthly["portfolio_value_end"].astype(float)
        summary_rows.append(
            {
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
        )

    summary_df = pd.DataFrame(summary_rows).sort_values(["multiple", "max_drawdown"], ascending=[False, False]).reset_index(drop=True)
    monthly_df = pd.concat(monthly_frames, ignore_index=True)
    summary_df.to_csv(SUMMARY_CSV, index=False)
    monthly_df.to_csv(MONTHLY_CSV, index=False)

    top = summary_df.iloc[0]
    lines = [
        "# BIST Earnings Quality Proxy Refine",
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

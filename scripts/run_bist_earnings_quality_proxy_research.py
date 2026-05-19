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
SUMMARY_CSV = OUTPUT_DIR / "bist_earnings_quality_proxy_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "bist_earnings_quality_proxy_monthly.csv"
README_MD = OUTPUT_DIR / "bist_earnings_quality_proxy_readout.md"


VARIANTS = [
    {
        "name": "baseline",
        "notes": "Current accepted baseline.",
        "filters": {},
    },
    {
        "name": "ni_yoy_cap_3p1",
        "notes": "Filter out extreme ni_ttm_growth_yoy above 3.1x.",
        "filters": {"max_ni_ttm_growth_yoy": 3.1},
    },
    {
        "name": "accel_cap_4p6",
        "notes": "Filter out extreme earnings_acceleration above 4.6x.",
        "filters": {"max_earnings_acceleration": 4.6},
    },
    {
        "name": "ni_yoy_cap_3p1_accel_4p6",
        "notes": "Filter out both extreme ni_ttm_growth_yoy and acceleration.",
        "filters": {"max_ni_ttm_growth_yoy": 3.1, "max_earnings_acceleration": 4.6},
    },
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
    for variant in VARIANTS:
        config = base_config.model_copy(deep=True)
        for key, value in variant["filters"].items():
            setattr(config.filters, key, value)
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
        monthly_frames.append(monthly)
        curve = monthly["portfolio_value_end"].astype(float)
        summary_rows.append(
            {
                "variant": variant["name"],
                "notes": variant["notes"],
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
        "# BIST Earnings Quality Proxy Research",
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

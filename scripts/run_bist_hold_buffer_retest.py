from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.storage import DuckDbStorage


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.formula_research_momentum.yaml"
DB_PATH = ROOT / "data/bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs/formula_research_reference"
SUMMARY_CSV = OUTPUT_DIR / "bist_hold_buffer_retest_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "bist_hold_buffer_retest_monthly.csv"
README_MD = OUTPUT_DIR / "bist_hold_buffer_retest_readout.md"


def _load_inputs() -> tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = load_config(CONFIG_PATH)
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    storage.close()
    membership = _load_membership_for_run(config)
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


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_config, prices, financials, membership = _load_inputs()

    variants = [
        ("baseline", "Current repaired accepted baseline.", None),
        ("hold_buffer_5", "Keep existing names if they remain inside top 5.", 5),
        ("hold_buffer_6", "Keep existing names if they remain inside top 6.", 6),
        ("hold_buffer_7", "Keep existing names if they remain inside top 7.", 7),
        ("hold_buffer_8", "Keep existing names if they remain inside top 8.", 8),
    ]

    summary_rows: list[dict[str, object]] = []
    monthly_frames: list[pd.DataFrame] = []

    for name, notes, hold_rank in variants:
        config = base_config.model_copy(deep=True)
        config.project.name = name
        config.strategy.hold_buffer_rank = hold_rank
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
        summary_rows.append(_summarize(name, notes, monthly))

    summary_df = pd.DataFrame(summary_rows)
    base = summary_df.set_index("variant").loc["baseline"]
    summary_df["strict_gate_pass"] = (
        (summary_df["multiple"] > float(base["multiple"]))
        & (summary_df["win_rate"] >= float(base["win_rate"]))
        & (summary_df["max_drawdown"] >= float(base["max_drawdown"]))
    )
    summary_df = summary_df.sort_values(["strict_gate_pass", "multiple", "max_drawdown"], ascending=[False, False, False]).reset_index(drop=True)
    monthly_df = pd.concat(monthly_frames, ignore_index=True)
    summary_df.to_csv(SUMMARY_CSV, index=False)
    monthly_df.to_csv(MONTHLY_CSV, index=False)

    lines = [
        "# BIST Hold Buffer Retest",
        "",
        "## Strict Gate",
        "",
        "- Higher total multiple",
        "- Win rate not lower",
        "- Max drawdown not worse",
        "",
        "## Ranking",
        "",
    ]
    for row in summary_df.to_dict("records"):
        period_text = f"{row['period_2024_plus']:.2f}x" if pd.notna(row["period_2024_plus"]) else "n/a"
        lines.append(
            f"- `{row['variant']}`: `{row['multiple']:.2f}x`, `2024+ {period_text}`, "
            f"win `{row['win_rate']:.2%}`, max DD `{row['max_drawdown']:.2%}`, strict_pass=`{str(bool(row['strict_gate_pass'])).lower()}`"
        )
    passes = summary_df[summary_df["strict_gate_pass"]]
    lines += ["", "## Decision", ""]
    if passes.empty:
        lines.append("- No hold-buffer variant passes the strict gate.")
        lines.append("- Keep the current accepted baseline without a hold buffer.")
    else:
        lines.append(f"- Promote `{passes.iloc[0]['variant']}` over the current accepted baseline.")
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()

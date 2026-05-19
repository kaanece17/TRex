from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage


BASE_CONFIG_PATH = Path("/Users/kaanece/projects/TRex/config.formula_research_momentum.yaml")
DB_PATH = Path("/Users/kaanece/projects/TRex/data/bist_backtest.duckdb")
OUTPUT_DIR = Path("/Users/kaanece/projects/TRex/outputs/formula_research_reference")
SUMMARY_CSV = OUTPUT_DIR / "bist_x1_growth_cooling_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "bist_x1_growth_cooling_monthly.csv"
README_MD = OUTPUT_DIR / "bist_x1_growth_cooling_readout.md"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    mode: str | None = None
    share_threshold: float | None = None
    return_60d_threshold: float | None = None
    penalty_amount: float = 0.0


CANDIDATES = [
    CandidateSpec(
        name="momentum_baseline",
        notes="Current accepted baseline.",
    ),
    CandidateSpec(
        name="x1cool_080_020_p05",
        notes="Light x1-heavy cooling.",
        mode="x1_heavy_low_60d_penalty",
        share_threshold=0.80,
        return_60d_threshold=0.20,
        penalty_amount=0.05,
    ),
    CandidateSpec(
        name="x1cool_080_020_p10",
        notes="Current strongest historical cooling idea.",
        mode="x1_heavy_low_60d_penalty",
        share_threshold=0.80,
        return_60d_threshold=0.20,
        penalty_amount=0.10,
    ),
    CandidateSpec(
        name="x1cool_085_020_p10",
        notes="Slightly stricter x1-share trigger.",
        mode="x1_heavy_low_60d_penalty",
        share_threshold=0.85,
        return_60d_threshold=0.20,
        penalty_amount=0.10,
    ),
    CandidateSpec(
        name="x1cool_080_015_p10",
        notes="Only cool names with weaker 60d trend.",
        mode="x1_heavy_low_60d_penalty",
        share_threshold=0.80,
        return_60d_threshold=0.15,
        penalty_amount=0.10,
    ),
    CandidateSpec(
        name="x1cool_080_025_p10",
        notes="Broader 60d cooling trigger.",
        mode="x1_heavy_low_60d_penalty",
        share_threshold=0.80,
        return_60d_threshold=0.25,
        penalty_amount=0.10,
    ),
]


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    financials["announcement_datetime"] = pd.to_datetime(financials["announcement_datetime"], errors="coerce")
    financials = (
        financials.sort_values(["symbol", "period_end", "announcement_datetime"])
        .drop_duplicates(["symbol", "period_end", "announcement_datetime"], keep="last")
        .reset_index(drop=True)
    )
    membership = _load_membership_for_run(load_config(BASE_CONFIG_PATH))
    storage.close()
    return prices, financials, membership


def _apply_candidate(spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(load_config(BASE_CONFIG_PATH))
    config.project.name = spec.name
    config.strategy.x1_soft_penalty_mode = spec.mode
    config.strategy.x1_soft_penalty_share_threshold = spec.share_threshold
    config.strategy.x1_soft_penalty_return_60d_threshold = spec.return_60d_threshold
    config.strategy.x1_soft_penalty_amount = spec.penalty_amount
    return config


def _period_multiple(monthly: pd.DataFrame, start_month: str) -> float | None:
    subset = monthly[monthly["month"] >= start_month].copy()
    if subset.empty:
        return None
    start_value = float(subset["portfolio_value_start"].iloc[0])
    end_value = float(subset["portfolio_value_end"].iloc[-1])
    if start_value <= 0:
        return None
    return end_value / start_value


def _summarize_monthly(monthly: pd.DataFrame, spec: CandidateSpec, runtime_seconds: float, initial_capital: float) -> dict[str, object]:
    curve = monthly["portfolio_value_end"].astype(float)
    return {
        "candidate": spec.name,
        "notes": spec.notes,
        "months": len(monthly),
        "final_capital": float(curve.iloc[-1]),
        "multiple": float(curve.iloc[-1] / initial_capital),
        "win_rate": float((monthly["net_return"] > 0).mean()),
        "max_drawdown": float(((curve / curve.cummax()) - 1).min()),
        "avg_monthly_return": float(monthly["net_return"].mean()),
        "period_2024_plus": _period_multiple(monthly, "2024-01"),
        "runtime_seconds": runtime_seconds,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prices, financials, membership = _load_inputs()

    summary_rows: list[dict[str, object]] = []
    monthly_frames: list[pd.DataFrame] = []

    for spec in CANDIDATES:
        config = _apply_candidate(spec)
        print(f"running {spec.name}...", flush=True)
        started = perf_counter()
        result = run_monthly_rotation_backtest(config, prices, financials, membership)
        runtime_seconds = perf_counter() - started
        monthly = result["monthly_results"].copy()
        monthly["candidate"] = spec.name
        monthly_frames.append(monthly)
        row = _summarize_monthly(monthly, spec, runtime_seconds, config.backtest.initial_capital)
        summary_rows.append(row)
        print(
            f"done {spec.name}: multiple={row['multiple']:.2f}x win={row['win_rate']:.2%} dd={row['max_drawdown']:.2%}",
            flush=True,
        )
        pd.DataFrame(summary_rows).to_csv(SUMMARY_CSV, index=False)
        pd.concat(monthly_frames, ignore_index=True).to_csv(MONTHLY_CSV, index=False)

    summary = pd.DataFrame(summary_rows).sort_values(
        ["multiple", "period_2024_plus", "max_drawdown"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    pd.concat(monthly_frames, ignore_index=True).to_csv(MONTHLY_CSV, index=False)
    summary.to_csv(SUMMARY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# BIST X1-Heavy Growth Cooling Research",
        "",
        f"- Candidate count: `{len(summary)}`",
        f"- Winner: `{top['candidate']}`",
        f"- Winner multiple: `{top['multiple']:.2f}x`",
        f"- Winner 2024+: `{top['period_2024_plus']:.2f}x`" if pd.notna(top["period_2024_plus"]) else "- Winner 2024+: `n/a`",
        f"- Winner max drawdown: `{top['max_drawdown']:.2%}`",
        "",
        "## Ranking",
        "",
    ]
    for row in summary.to_dict("records"):
        period_text = f"{row['period_2024_plus']:.2f}x" if pd.notna(row["period_2024_plus"]) else "n/a"
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, `2024+ {period_text}`, "
            f"win `{row['win_rate']:.2%}`, max DD `{row['max_drawdown']:.2%}`"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

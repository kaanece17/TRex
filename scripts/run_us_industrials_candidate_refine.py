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


CONFIG_PATH = Path("/Users/kaanece/projects/TRex/config.us_industrials_momentum.yaml")
DB_PATH = Path("/Users/kaanece/projects/TRex/data/us_backtest.duckdb")
OUTPUT_DIR = Path("/Users/kaanece/projects/TRex/outputs/formula_research_reference")
SUMMARY_CSV = OUTPUT_DIR / "us_industrials_candidate_refine_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "us_industrials_candidate_refine_monthly.csv"
README_MD = OUTPUT_DIR / "us_industrials_candidate_refine_readout.md"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    top_n: int = 5
    weighting: str = "equal_weight"
    score_weight_cap: float | None = None
    min_avg_turnover_20d: float = 20_000_000
    min_market_cap: float = 2_000_000_000
    require_positive_net_income_ttm: bool = True
    require_positive_previous_net_income_ttm: bool = True
    require_positive_operating_profit_ttm: bool = True


CANDIDATES = [
    CandidateSpec(
        name="quality_eq_2b_20m_top5",
        notes="Quality equal-weight baseline from round one.",
    ),
    CandidateSpec(
        name="quality_eq_5b_20m_top5",
        notes="Raise market-cap floor to $5b.",
        min_market_cap=5_000_000_000,
    ),
    CandidateSpec(
        name="quality_eq_10b_20m_top5",
        notes="Raise market-cap floor to $10b.",
        min_market_cap=10_000_000_000,
    ),
    CandidateSpec(
        name="quality_eq_2b_50m_top5",
        notes="Raise liquidity floor to $50m.",
        min_avg_turnover_20d=50_000_000,
    ),
    CandidateSpec(
        name="quality_eq_5b_50m_top5",
        notes="Higher cap and higher liquidity floor.",
        min_avg_turnover_20d=50_000_000,
        min_market_cap=5_000_000_000,
    ),
    CandidateSpec(
        name="quality_eq_2b_20m_top7",
        notes="Broader basket with 7 names.",
        top_n=7,
    ),
    CandidateSpec(
        name="quality_scorecap35_2b_20m_top5",
        notes="Score-weight capped winner from round one.",
        weighting="score_weight_capped",
        score_weight_cap=0.35,
    ),
    CandidateSpec(
        name="quality_scorecap30_2b_20m_top5",
        notes="Slightly tighter score cap at 30%.",
        weighting="score_weight_capped",
        score_weight_cap=0.30,
    ),
    CandidateSpec(
        name="quality_scorecap35_5b_20m_top5",
        notes="Score-weight capped with higher market-cap floor.",
        weighting="score_weight_capped",
        score_weight_cap=0.35,
        min_market_cap=5_000_000_000,
    ),
    CandidateSpec(
        name="quality_scorecap35_5b_50m_top5",
        notes="Score-weight capped with higher cap and liquidity floors.",
        weighting="score_weight_capped",
        score_weight_cap=0.35,
        min_market_cap=5_000_000_000,
        min_avg_turnover_20d=50_000_000,
    ),
]


def _apply_candidate(base: BacktestConfig, spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(base)
    config.strategy.top_n = spec.top_n
    config.strategy.weighting = spec.weighting
    config.strategy.score_weight_cap = spec.score_weight_cap
    config.filters.min_avg_turnover_20d = spec.min_avg_turnover_20d
    config.filters.min_market_cap = spec.min_market_cap
    config.filters.require_positive_net_income_ttm = spec.require_positive_net_income_ttm
    config.filters.require_positive_previous_net_income_ttm = spec.require_positive_previous_net_income_ttm
    config.filters.require_positive_operating_profit_ttm = spec.require_positive_operating_profit_ttm
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
    if monthly.empty:
        return {
            "candidate": spec.name,
            "notes": spec.notes,
            "months": 0,
            "final_capital": initial_capital,
            "multiple": 1.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "avg_monthly_return": 0.0,
            "period_2024_plus": None,
            "period_2025_plus": None,
            "runtime_seconds": runtime_seconds,
        }
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
        "period_2025_plus": _period_multiple(monthly, "2025-01"),
        "runtime_seconds": runtime_seconds,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_config(CONFIG_PATH)
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    membership = _load_membership_for_run(base)

    summary_rows: list[dict[str, object]] = []
    monthly_frames: list[pd.DataFrame] = []

    for spec in CANDIDATES:
        config = _apply_candidate(base, spec)
        started = perf_counter()
        result = run_monthly_rotation_backtest(config, prices, financials, membership)
        runtime_seconds = perf_counter() - started
        monthly = result["monthly_results"].copy()
        monthly["candidate"] = spec.name
        monthly_frames.append(monthly)
        summary_rows.append(_summarize_monthly(monthly, spec, runtime_seconds, config.backtest.initial_capital))

    storage.close()

    summary = pd.DataFrame(summary_rows).sort_values(
        ["multiple", "period_2025_plus", "max_drawdown"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    monthly_all = pd.concat(monthly_frames, ignore_index=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    monthly_all.to_csv(MONTHLY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# US Industrials Candidate Refinement",
        "",
        f"- Candidate count: `{len(summary)}`",
        f"- Winner: `{top['candidate']}`",
        f"- Winner multiple: `{top['multiple']:.2f}x`",
        f"- Winner 2025+: `{top['period_2025_plus']:.2f}x`" if pd.notna(top["period_2025_plus"]) else "- Winner 2025+: `n/a`",
        f"- Winner max drawdown: `{top['max_drawdown']:.2%}`",
        "",
        "## Ranking",
        "",
    ]
    for row in summary.to_dict("records"):
        period_2025 = row["period_2025_plus"]
        period_2025_text = f"{period_2025:.2f}x" if pd.notna(period_2025) else "n/a"
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, `2025+ {period_2025_text}`, "
            f"win `{row['win_rate']:.2%}`, max DD `{row['max_drawdown']:.2%}`"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

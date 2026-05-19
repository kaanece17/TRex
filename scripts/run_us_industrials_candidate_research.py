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
SUMMARY_CSV = OUTPUT_DIR / "us_industrials_candidate_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "us_industrials_candidate_monthly.csv"
README_MD = OUTPUT_DIR / "us_industrials_candidate_readout.md"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    top_n: int | None = None
    weighting: str | None = None
    score_weight_cap: float | None = None
    min_avg_turnover_20d: float | None = None
    min_market_cap: float | None = None
    require_positive_net_income_ttm: bool | None = None
    require_positive_previous_net_income_ttm: bool | None = None
    require_positive_operating_profit_ttm: bool | None = None


CANDIDATES = [
    CandidateSpec(name="base", notes="Current US momentum baseline."),
    CandidateSpec(
        name="liquid_20m",
        notes="Require at least $20m avg daily turnover.",
        min_avg_turnover_20d=20_000_000,
    ),
    CandidateSpec(
        name="liquid_50m",
        notes="Require at least $50m avg daily turnover.",
        min_avg_turnover_20d=50_000_000,
    ),
    CandidateSpec(
        name="quality_momentum",
        notes="Positive TTM net income, previous TTM, and operating profit.",
        require_positive_net_income_ttm=True,
        require_positive_previous_net_income_ttm=True,
        require_positive_operating_profit_ttm=True,
        min_avg_turnover_20d=20_000_000,
    ),
    CandidateSpec(
        name="large_mid_2b",
        notes="Prune sub-$2b market cap names and require liquid names.",
        min_market_cap=2_000_000_000,
        min_avg_turnover_20d=20_000_000,
    ),
    CandidateSpec(
        name="large_mid_quality",
        notes="Large/mid only plus profitability checks.",
        min_market_cap=2_000_000_000,
        min_avg_turnover_20d=20_000_000,
        require_positive_net_income_ttm=True,
        require_positive_previous_net_income_ttm=True,
        require_positive_operating_profit_ttm=True,
    ),
    CandidateSpec(
        name="large_mid_quality_top7",
        notes="Large/mid quality with broader 7-name basket.",
        min_market_cap=2_000_000_000,
        min_avg_turnover_20d=20_000_000,
        require_positive_net_income_ttm=True,
        require_positive_previous_net_income_ttm=True,
        require_positive_operating_profit_ttm=True,
        top_n=7,
    ),
    CandidateSpec(
        name="large_mid_quality_scorecap",
        notes="Large/mid quality with score-weight capped sizing.",
        min_market_cap=2_000_000_000,
        min_avg_turnover_20d=20_000_000,
        require_positive_net_income_ttm=True,
        require_positive_previous_net_income_ttm=True,
        require_positive_operating_profit_ttm=True,
        weighting="score_weight_capped",
        score_weight_cap=0.35,
    ),
]


def _apply_candidate(base: BacktestConfig, spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(base)
    if spec.top_n is not None:
        config.strategy.top_n = spec.top_n
    if spec.weighting is not None:
        config.strategy.weighting = spec.weighting
    if spec.score_weight_cap is not None:
        config.strategy.score_weight_cap = spec.score_weight_cap
    if spec.min_avg_turnover_20d is not None:
        config.filters.min_avg_turnover_20d = spec.min_avg_turnover_20d
    if spec.min_market_cap is not None:
        config.filters.min_market_cap = spec.min_market_cap
    if spec.require_positive_net_income_ttm is not None:
        config.filters.require_positive_net_income_ttm = spec.require_positive_net_income_ttm
    if spec.require_positive_previous_net_income_ttm is not None:
        config.filters.require_positive_previous_net_income_ttm = spec.require_positive_previous_net_income_ttm
    if spec.require_positive_operating_profit_ttm is not None:
        config.filters.require_positive_operating_profit_ttm = spec.require_positive_operating_profit_ttm
    return config


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

    summary = pd.DataFrame(summary_rows).sort_values(["multiple", "win_rate"], ascending=False).reset_index(drop=True)
    monthly_all = pd.concat(monthly_frames, ignore_index=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    monthly_all.to_csv(MONTHLY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# US Industrials Candidate Research",
        "",
        f"- Candidate count: `{len(summary)}`",
        f"- Winner by multiple: `{top['candidate']}`",
        f"- Winner multiple: `{top['multiple']:.2f}x`",
        f"- Winner win rate: `{top['win_rate']:.2%}`",
        f"- Winner max drawdown: `{top['max_drawdown']:.2%}`",
        "",
        "## Ranking",
        "",
    ]
    for row in summary.to_dict("records"):
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, win `{row['win_rate']:.2%}`, "
            f"max DD `{row['max_drawdown']:.2%}`, avg month `{row['avg_monthly_return']:.2%}`"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

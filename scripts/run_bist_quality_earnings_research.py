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
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


MOMENTUM_CONFIG_PATH = Path("/Users/kaanece/projects/TRex/config.formula_research_momentum.yaml")
QE_CONFIG_PATH = Path("/Users/kaanece/projects/TRex/config.formula_research_momentum_quality_earnings.yaml")
DB_PATH = Path("/Users/kaanece/projects/TRex/data/bist_backtest.duckdb")
OUTPUT_DIR = Path("/Users/kaanece/projects/TRex/outputs/formula_research_reference")
SUMMARY_CSV = OUTPUT_DIR / "bist_quality_earnings_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "bist_quality_earnings_monthly.csv"
README_MD = OUTPUT_DIR / "bist_quality_earnings_readout.md"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    config_path: Path
    earnings_weight: float | None = None
    require_positive_profitability: bool | None = None
    weighting: str | None = None
    score_weight_cap: float | None = None


CANDIDATES = [
    CandidateSpec(
        name="momentum_baseline",
        notes="Current accepted BIST momentum baseline.",
        config_path=MOMENTUM_CONFIG_PATH,
    ),
    CandidateSpec(
        name="qe_w05",
        notes="Quality plus earnings, lighter earnings sleeve.",
        config_path=QE_CONFIG_PATH,
        earnings_weight=0.5,
    ),
    CandidateSpec(
        name="qe_w10",
        notes="Quality plus earnings baseline.",
        config_path=QE_CONFIG_PATH,
        earnings_weight=1.0,
    ),
    CandidateSpec(
        name="qe_w15",
        notes="Quality plus earnings, heavier earnings sleeve.",
        config_path=QE_CONFIG_PATH,
        earnings_weight=1.5,
    ),
    CandidateSpec(
        name="qe_w10_profitability",
        notes="Quality plus earnings with positive profitability discipline.",
        config_path=QE_CONFIG_PATH,
        earnings_weight=1.0,
        require_positive_profitability=True,
    ),
    CandidateSpec(
        name="qe_w10_scorecap35",
        notes="Quality plus earnings with capped score weights.",
        config_path=QE_CONFIG_PATH,
        earnings_weight=1.0,
        weighting="score_weight_capped",
        score_weight_cap=0.35,
    ),
    CandidateSpec(
        name="qe_w10_profitability_scorecap35",
        notes="Quality plus earnings with profitability discipline and score cap.",
        config_path=QE_CONFIG_PATH,
        earnings_weight=1.0,
        require_positive_profitability=True,
        weighting="score_weight_capped",
        score_weight_cap=0.35,
    ),
]


def _load_financials() -> pd.DataFrame:
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
    financials = add_earnings_momentum_features(financials)
    membership = _load_membership_for_run(load_config(MOMENTUM_CONFIG_PATH))
    storage.close()
    return prices, financials, membership


def _apply_candidate(spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(load_config(spec.config_path))
    config.project.name = spec.name
    if spec.earnings_weight is not None:
        config.scoring.earnings_weight = spec.earnings_weight
    if spec.require_positive_profitability:
        config.filters.require_positive_net_income_ttm = True
        config.filters.require_positive_previous_net_income_ttm = True
        config.filters.require_positive_operating_profit_ttm = True
    if spec.weighting is not None:
        config.strategy.weighting = spec.weighting
        config.strategy.score_weight_cap = spec.score_weight_cap
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
    prices, financials, membership = _load_financials()

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
    monthly_all = pd.concat(monthly_frames, ignore_index=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    monthly_all.to_csv(MONTHLY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# BIST Quality + Earnings Research",
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

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


CONFIG_PATH = Path("/Users/kaanece/projects/TRex/config.us_industrials_quality_earnings.yaml")
DB_PATH = Path("/Users/kaanece/projects/TRex/data/us_backtest.duckdb")
OUTPUT_DIR = Path("/Users/kaanece/projects/TRex/outputs/formula_research_reference")
SUMMARY_CSV = OUTPUT_DIR / "us_quality_earnings_refine_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "us_quality_earnings_refine_monthly.csv"
README_MD = OUTPUT_DIR / "us_quality_earnings_refine_readout.md"

BASELINE_MULTIPLE = 3.136757550892786
BASELINE_MAX_DD = -0.4492610327267006


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    top_n: int = 5
    score_weight_cap: float = 0.35
    min_avg_turnover_20d: float = 50_000_000
    min_market_cap: float = 5_000_000_000
    earnings_weight: float = 1.0


CANDIDATES = [
    CandidateSpec(
        name="qe_base_w10",
        notes="Current winner baseline.",
    ),
    CandidateSpec(
        name="qe_w075",
        notes="Slightly lighter earnings sleeve.",
        earnings_weight=0.75,
    ),
    CandidateSpec(
        name="qe_w125",
        notes="Slightly heavier earnings sleeve.",
        earnings_weight=1.25,
    ),
    CandidateSpec(
        name="qe_top4_w10",
        notes="Tighter 4-name basket.",
        top_n=4,
    ),
    CandidateSpec(
        name="qe_top6_w10",
        notes="Broader 6-name basket.",
        top_n=6,
    ),
    CandidateSpec(
        name="qe_cap30_w10",
        notes="Tighter 30% score cap.",
        score_weight_cap=0.30,
    ),
    CandidateSpec(
        name="qe_cap40_w10",
        notes="Looser 40% score cap.",
        score_weight_cap=0.40,
    ),
    CandidateSpec(
        name="qe_10b_50m_w10",
        notes="Raise market-cap floor to $10b.",
        min_market_cap=10_000_000_000,
    ),
    CandidateSpec(
        name="qe_5b_100m_w10",
        notes="Raise liquidity floor to $100m.",
        min_avg_turnover_20d=100_000_000,
    ),
]


def _apply_candidate(base: BacktestConfig, spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(base)
    config.project.name = spec.name
    config.strategy.top_n = spec.top_n
    config.strategy.score_weight_cap = spec.score_weight_cap
    config.scoring.earnings_weight = spec.earnings_weight
    config.filters.min_avg_turnover_20d = spec.min_avg_turnover_20d
    config.filters.min_market_cap = spec.min_market_cap
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
    multiple = float(curve.iloc[-1] / initial_capital)
    max_drawdown = float(((curve / curve.cummax()) - 1).min())
    return {
        "candidate": spec.name,
        "notes": spec.notes,
        "months": len(monthly),
        "final_capital": float(curve.iloc[-1]),
        "multiple": multiple,
        "win_rate": float((monthly["net_return"] > 0).mean()),
        "max_drawdown": max_drawdown,
        "avg_monthly_return": float(monthly["net_return"].mean()),
        "period_2025_plus": _period_multiple(monthly, "2025-01"),
        "runtime_seconds": runtime_seconds,
        "beats_gate": multiple > BASELINE_MULTIPLE and max_drawdown > BASELINE_MAX_DD,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_config(CONFIG_PATH)
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
    membership = _load_membership_for_run(base)
    storage.close()

    summary_rows: list[dict[str, object]] = []
    monthly_frames: list[pd.DataFrame] = []

    for spec in CANDIDATES:
        config = _apply_candidate(base, spec)
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
        ["beats_gate", "multiple", "period_2025_plus", "max_drawdown"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    monthly_all = pd.concat(monthly_frames, ignore_index=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    monthly_all.to_csv(MONTHLY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# US Quality + Earnings Refinement",
        "",
        f"- Candidate count: `{len(summary)}`",
        f"- Winner: `{top['candidate']}`",
        f"- Winner multiple: `{top['multiple']:.2f}x`",
        f"- Winner 2025+: `{top['period_2025_plus']:.2f}x`" if pd.notna(top["period_2025_plus"]) else "- Winner 2025+: `n/a`",
        f"- Winner max drawdown: `{top['max_drawdown']:.2%}`",
        f"- Gate cleared: `{'yes' if bool(top['beats_gate']) else 'no'}`",
        "",
        "## Ranking",
        "",
    ]
    for row in summary.to_dict("records"):
        period_2025 = row["period_2025_plus"]
        period_2025_text = f"{period_2025:.2f}x" if pd.notna(period_2025) else "n/a"
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, `2025+ {period_2025_text}`, "
            f"win `{row['win_rate']:.2%}`, max DD `{row['max_drawdown']:.2%}`, gate `{'yes' if row['beats_gate'] else 'no'}`"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

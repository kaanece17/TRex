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
SUMMARY_CSV = OUTPUT_DIR / "us_op_pead_research_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "us_op_pead_research_monthly.csv"
README_MD = OUTPUT_DIR / "us_op_pead_research_readout.md"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    formula: str = "quality_plus_earnings"
    earnings_weight: float = 1.0
    rebalance_frequency: str = "monthly"


CANDIDATES = [
    CandidateSpec(
        name="qe_monthly_base",
        notes="Current US winner: quality plus full earnings sleeve, monthly cadence.",
    ),
    CandidateSpec(
        name="qe_bimonthly",
        notes="Current winner on a slower 2-month cadence to better match PEAD-style 2m drift.",
        rebalance_frequency="bimonthly",
    ),
    CandidateSpec(
        name="qe_quarterly",
        notes="Current winner on quarterly cadence to match longer post-filing drift.",
        rebalance_frequency="quarterly",
    ),
    CandidateSpec(
        name="op_monthly_w10",
        notes="Operating-profit-growth sleeve only, monthly cadence.",
        formula="quality_plus_op_growth",
    ),
    CandidateSpec(
        name="op_monthly_w15",
        notes="Operating-profit-growth sleeve only, heavier weight, monthly cadence.",
        formula="quality_plus_op_growth",
        earnings_weight=1.5,
    ),
    CandidateSpec(
        name="op_bimonthly_w10",
        notes="Operating-profit-growth sleeve only, 2-month cadence.",
        formula="quality_plus_op_growth",
        rebalance_frequency="bimonthly",
    ),
    CandidateSpec(
        name="op_bimonthly_w15",
        notes="Operating-profit-growth sleeve only, heavier weight, 2-month cadence.",
        formula="quality_plus_op_growth",
        earnings_weight=1.5,
        rebalance_frequency="bimonthly",
    ),
    CandidateSpec(
        name="op_quarterly_w10",
        notes="Operating-profit-growth sleeve only, quarterly cadence.",
        formula="quality_plus_op_growth",
        rebalance_frequency="quarterly",
    ),
]


def _apply_candidate(base: BacktestConfig, spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(base)
    config.project.name = spec.name
    config.scoring.formula = spec.formula
    config.scoring.earnings_weight = spec.earnings_weight
    config.strategy.rebalance_frequency = spec.rebalance_frequency
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
        "formula": spec.formula,
        "earnings_weight": spec.earnings_weight,
        "rebalance_frequency": spec.rebalance_frequency,
        "months": len(monthly),
        "final_capital": float(curve.iloc[-1]),
        "multiple": multiple,
        "win_rate": float((monthly["net_return"] > 0).mean()),
        "max_drawdown": max_drawdown,
        "avg_monthly_return": float(monthly["net_return"].mean()),
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

    summary = pd.DataFrame(summary_rows)
    baseline = summary.loc[summary["candidate"] == "qe_monthly_base"].iloc[0]
    summary["strict_pass"] = (
        (summary["multiple"] > float(baseline["multiple"]))
        & (summary["max_drawdown"] > float(baseline["max_drawdown"]))
        & (summary["win_rate"] >= float(baseline["win_rate"]))
    )
    summary = summary.sort_values(
        ["strict_pass", "multiple", "period_2025_plus", "max_drawdown"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    monthly_all = pd.concat(monthly_frames, ignore_index=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    monthly_all.to_csv(MONTHLY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# US OP-Growth / PEAD Candidate Research",
        "",
        "Evidence anchor:",
        "- `op_ttm_growth_yoy` showed the strongest positive 2m/3m relation in the current US selected universe.",
        "- `ni_ttm_growth_yoy` and generic quality combo were weaker or mildly negative.",
        "",
        f"- Baseline candidate: `qe_monthly_base`",
        f"- Baseline multiple: `{baseline['multiple']:.2f}x`",
        f"- Baseline win rate: `{baseline['win_rate']:.2%}`",
        f"- Baseline max drawdown: `{baseline['max_drawdown']:.2%}`",
        "",
        f"- Winner: `{top['candidate']}`",
        f"- Winner multiple: `{top['multiple']:.2f}x`",
        f"- Winner max drawdown: `{top['max_drawdown']:.2%}`",
        f"- Strict gate cleared: `{'yes' if bool(top['strict_pass']) else 'no'}`",
        "",
        "## Ranking",
        "",
    ]
    for row in summary.to_dict("records"):
        period_2025 = row["period_2025_plus"]
        period_2025_text = f"{period_2025:.2f}x" if pd.notna(period_2025) else "n/a"
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, win `{row['win_rate']:.2%}`, "
            f"max DD `{row['max_drawdown']:.2%}`, `2025+ {period_2025_text}`, strict `{'yes' if row['strict_pass'] else 'no'}`"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run, _merge_analyst_consensus_history
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features, add_ttm_values


CONFIG_PATH = Path("/Users/kaanece/projects/TRex/config.us_large_cap_tech_quality_earnings.yaml")
DB_PATH = Path("/Users/kaanece/projects/TRex/data/us_large_cap_tech_backtest.duckdb")
OUTPUT_DIR = Path("/Users/kaanece/projects/TRex/outputs/formula_research_reference")
SUMMARY_CSV = OUTPUT_DIR / "us_large_cap_tech_pit_signal_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "us_large_cap_tech_pit_signal_monthly.csv"
README_MD = OUTPUT_DIR / "us_large_cap_tech_pit_signal_readout.md"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    scoring_updates: dict[str, float | int | None]


CANDIDATES = [
    CandidateSpec(
        name="tech_quality_earnings_baseline",
        notes="Baseline large-cap tech quality plus earnings profile.",
        scoring_updates={},
    ),
    CandidateSpec(
        name="tech_filing_timeliness",
        notes="Reward earlier filers and penalize long filing lags.",
        scoring_updates={
            "filing_timeliness_weight": 0.20,
            "delay_penalty": 0.08,
            "filing_lag_threshold_days": 50,
        },
    ),
    CandidateSpec(
        name="tech_announcement_freshness",
        notes="Favor fresher reports at rebalance time.",
        scoring_updates={
            "announcement_freshness_weight": 0.15,
        },
    ),
    CandidateSpec(
        name="tech_announcement_drift",
        notes="Add a short post-announcement drift sleeve as a PEAD-style proxy.",
        scoring_updates={
            "announcement_drift_weight": 0.20,
            "announcement_drift_lookback_days": 20,
        },
    ),
    CandidateSpec(
        name="tech_revenue_quality",
        notes="Add revenue growth and revenue acceleration to the quality sleeve.",
        scoring_updates={
            "revenue_growth_weight": 0.15,
            "revenue_acceleration_weight": 0.10,
        },
    ),
    CandidateSpec(
        name="tech_eps_surprise",
        notes="Reward positive historical EPS surprise by quarter.",
        scoring_updates={
            "eps_surprise_weight": 0.20,
        },
    ),
    CandidateSpec(
        name="tech_analyst_revisions",
        notes="Use archived near-term analyst revision balance when available.",
        scoring_updates={
            "analyst_revision_weight": 0.15,
            "recommendation_weight": 0.10,
        },
    ),
    CandidateSpec(
        name="tech_asset_growth_guard",
        notes="Penalize aggressive asset growers.",
        scoring_updates={
            "asset_growth_penalty": 0.10,
            "asset_growth_threshold": 0.25,
        },
    ),
    CandidateSpec(
        name="tech_accrual_guard",
        notes="Penalize weak cash conversion via high accruals.",
        scoring_updates={
            "accruals_penalty": 0.10,
            "accruals_ratio_threshold": 0.08,
        },
    ),
    CandidateSpec(
        name="tech_combo_all",
        notes="Combine filing, freshness, drift, revenue, asset-growth, and accrual overlays.",
        scoring_updates={
            "filing_timeliness_weight": 0.15,
            "announcement_freshness_weight": 0.10,
            "announcement_drift_weight": 0.15,
            "announcement_drift_lookback_days": 20,
            "revenue_growth_weight": 0.10,
            "revenue_acceleration_weight": 0.05,
            "eps_surprise_weight": 0.10,
            "analyst_revision_weight": 0.10,
            "recommendation_weight": 0.05,
            "asset_growth_penalty": 0.08,
            "asset_growth_threshold": 0.25,
            "accruals_penalty": 0.08,
            "accruals_ratio_threshold": 0.08,
            "delay_penalty": 0.05,
            "filing_lag_threshold_days": 50,
        },
    ),
]


def _apply_candidate(base: BacktestConfig, spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(base)
    config.project.name = spec.name
    for key, value in spec.scoring_updates.items():
        setattr(config.scoring, key, value)
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


def _coverage(financials: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for column in [
        "filing_lag_days",
        "revenue_ttm_growth_yoy",
        "revenue_acceleration",
        "asset_growth_yoy",
        "accruals_ratio",
        "eps_surprise_percent",
    ]:
        if column not in financials.columns:
            coverage = 0.0
        else:
            coverage = float(pd.to_numeric(financials[column], errors="coerce").notna().mean())
        rows.append({"feature": column, "coverage": coverage})
    return pd.DataFrame(rows)


def _summarize_monthly(
    monthly: pd.DataFrame,
    spec: CandidateSpec,
    runtime_seconds: float,
    initial_capital: float,
) -> dict[str, object]:
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
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_config(CONFIG_PATH)
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    analyst_snapshots = storage.read_table("analyst_snapshot_history")
    analyst_consensus = storage.read_table("analyst_consensus_history")
    if financials.empty:
        raise RuntimeError("financial_snapshots is empty")
    financials["announcement_datetime"] = pd.to_datetime(financials["announcement_datetime"], errors="coerce")
    financials = (
        financials.sort_values(["symbol", "period_end", "announcement_datetime"])
        .drop_duplicates(["symbol", "period_end"], keep="last")
        .reset_index(drop=True)
    )
    financials = (
        financials.sort_values(["symbol", "fiscal_year", "fiscal_quarter", "announcement_datetime"])
        .drop_duplicates(["symbol", "fiscal_year", "fiscal_quarter"], keep="last")
        .reset_index(drop=True)
    )
    financials = add_ttm_values(financials)
    financials = add_earnings_momentum_features(financials)
    financials = _merge_analyst_consensus_history(financials, analyst_consensus)
    membership = _load_membership_for_run(base)
    storage.close()

    coverage = _coverage(financials)
    summary_rows: list[dict[str, object]] = []
    monthly_frames: list[pd.DataFrame] = []

    for spec in CANDIDATES:
        config = _apply_candidate(base, spec)
        print(f"running {spec.name}...", flush=True)
        started = perf_counter()
        result = run_monthly_rotation_backtest(
            config,
            prices,
            financials,
            membership,
            analyst_snapshots=analyst_snapshots,
        )
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

    summary = pd.DataFrame(summary_rows).sort_values(
        ["multiple", "period_2025_plus", "max_drawdown"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    monthly_all = pd.concat(monthly_frames, ignore_index=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    monthly_all.to_csv(MONTHLY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# US Large-Cap Tech PIT Signal Research",
        "",
        "Compared PIT overlays on top of the current large-cap tech quality-plus-earnings baseline.",
        "",
        "## Feature coverage in current snapshot table",
        "",
    ]
    for row in coverage.to_dict("records"):
        lines.append(f"- `{row['feature']}`: `{row['coverage']:.1%}`")
    lines.extend(
        [
            "",
            "Note:",
            "- If `revenue_ttm_growth_yoy`, `asset_growth_yoy`, or `accruals_ratio` coverage is low, rerun the SEC load and rebuild snapshots to fully activate those variants.",
            "",
            f"- Winner: `{top['candidate']}`",
            f"- Winner multiple: `{top['multiple']:.2f}x`",
            f"- Winner max drawdown: `{top['max_drawdown']:.2%}`",
            f"- Winner 2025+: `{top['period_2025_plus']:.2f}x`" if pd.notna(top["period_2025_plus"]) else "- Winner 2025+: `n/a`",
            "",
            "## Ranking",
            "",
        ]
    )
    for row in summary.to_dict("records"):
        period_2025 = row["period_2025_plus"]
        period_2025_text = f"{period_2025:.2f}x" if pd.notna(period_2025) else "n/a"
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, win `{row['win_rate']:.2%}`, "
            f"max DD `{row['max_drawdown']:.2%}`, `2025+ {period_2025_text}`"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

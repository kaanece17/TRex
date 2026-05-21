from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.us_industrials_quality_op_growth.yaml"
DB_PATH = ROOT / "data" / "us_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    lookback_months: int | None = None
    min_negative_hits: int | None = None
    scale_factor: float | None = None


CANDIDATES = [
    CandidateSpec(
        name="us_op_growth_base",
        notes="Current US OP-growth winner.",
    ),
    CandidateSpec(
        name="us_op_growth_dynrep_6m_2hits_085",
        notes="Scale dynamic repeaters using 6m lookback, 2 negative hits, 0.85 weight factor.",
        lookback_months=6,
        min_negative_hits=2,
        scale_factor=0.85,
    ),
    CandidateSpec(
        name="us_op_growth_dynrep_12m_2hits_075",
        notes="Scale dynamic repeaters using 12m lookback, 2 negative hits, 0.75 weight factor.",
        lookback_months=12,
        min_negative_hits=2,
        scale_factor=0.75,
    ),
]


def _apply_candidate(base: BacktestConfig, spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(base)
    config.project.name = spec.name
    if spec.lookback_months is None:
        config.strategy.dynamic_repeater_weight_scale_mode = None
        config.strategy.dynamic_repeater_lookback_months = 0
        config.strategy.dynamic_repeater_min_negative_hits = 0
        config.strategy.dynamic_repeater_weight_scale_factor = 1.0
    else:
        config.strategy.dynamic_repeater_weight_scale_mode = "recent_negative_repeaters_scale"
        config.strategy.dynamic_repeater_lookback_months = spec.lookback_months
        config.strategy.dynamic_repeater_min_negative_hits = int(spec.min_negative_hits or 0)
        config.strategy.dynamic_repeater_weight_scale_factor = float(spec.scale_factor or 1.0)
    return config


def _max_drawdown(monthly: pd.DataFrame) -> float:
    values = pd.to_numeric(monthly["portfolio_value_end"], errors="coerce")
    return float((values / values.cummax() - 1.0).min())


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

    rows: list[dict[str, object]] = []
    for spec in CANDIDATES:
        settings = _apply_candidate(base, spec)
        result = run_monthly_rotation_backtest(settings, prices, financials, membership)
        monthly = result["monthly_results"].copy()
        net = pd.to_numeric(monthly["net_return"], errors="coerce")
        rows.append(
            {
                "candidate": spec.name,
                "notes": spec.notes,
                "run_id": result["run_id"],
                "months": len(monthly),
                "multiple": float(monthly["portfolio_value_end"].iloc[-1] / settings.backtest.initial_capital),
                "final_capital": float(monthly["portfolio_value_end"].iloc[-1]),
                "win_rate": float((net > 0).mean()),
                "avg_monthly_return": float(net.mean()),
                "max_drawdown": _max_drawdown(monthly),
                "period_2025_plus": _period_multiple(monthly, "2025-01"),
            }
        )

    summary = pd.DataFrame(rows)
    baseline = summary.loc[summary["candidate"] == "us_op_growth_base"].iloc[0]
    summary["strict_pass"] = (
        (summary["multiple"] > float(baseline["multiple"]))
        & (summary["win_rate"] >= float(baseline["win_rate"]))
        & (summary["max_drawdown"] >= float(baseline["max_drawdown"]))
    )
    summary = summary.sort_values(["strict_pass", "multiple", "max_drawdown"], ascending=[False, False, False]).reset_index(drop=True)
    summary.to_csv(OUTPUT_DIR / "us_op_growth_dynamic_repeater_acceptance_summary.csv", index=False)

    lines = [
        "# US OP-Growth Dynamic Repeater Acceptance Review",
        "",
        f"- Baseline: `{baseline['candidate']}`",
        f"- Baseline multiple: `{baseline['multiple']:.2f}x`",
        f"- Baseline win rate: `{baseline['win_rate']:.2%}`",
        f"- Baseline max drawdown: `{baseline['max_drawdown']:.2%}`",
        "",
    ]
    for row in summary.to_dict("records"):
        period_2025 = row["period_2025_plus"]
        period_2025_text = f"{period_2025:.2f}x" if pd.notna(period_2025) else "n/a"
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, win `{row['win_rate']:.2%}`, "
            f"dd `{row['max_drawdown']:.2%}`, `2025+ {period_2025_text}`, strict `{'yes' if row['strict_pass'] else 'no'}`"
        )
    (OUTPUT_DIR / "us_op_growth_dynamic_repeater_acceptance_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

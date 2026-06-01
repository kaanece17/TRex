from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run, _merge_analyst_consensus_history
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_ttm_values, add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
BASE_CONFIG = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"


@dataclass(frozen=True)
class ProfileSpec:
    label: str
    family: str
    notes: str
    scoring_updates: dict[str, float | int | None]


PROFILES = [
    ProfileSpec(
        label="tech_quality_earnings_baseline",
        family="baseline",
        notes="Current baseline large-cap tech quality plus earnings profile.",
        scoring_updates={},
    ),
    ProfileSpec(
        label="tech_announcement_freshness",
        family="freshness",
        notes="Favor fresher reports at rebalance time.",
        scoring_updates={"announcement_freshness_weight": 0.15},
    ),
    ProfileSpec(
        label="tech_announcement_drift",
        family="event_drift",
        notes="Add a short post-announcement drift sleeve as a PEAD-style proxy.",
        scoring_updates={
            "announcement_drift_weight": 0.20,
            "announcement_drift_lookback_days": 20,
        },
    ),
    ProfileSpec(
        label="tech_asset_growth_guard",
        family="asset_growth",
        notes="Penalize aggressive asset growers.",
        scoring_updates={
            "asset_growth_penalty": 0.10,
            "asset_growth_threshold": 0.25,
        },
    ),
]

SPLITS = [
    ("2020_2021", "2020-01-01", "2021-12-31"),
    ("2022_2023", "2022-01-01", "2023-12-31"),
    ("2024_2026ytd", "2024-01-01", "2026-05-31"),
    ("full_period", "2020-01-01", "2026-05-31"),
]

COMMISSION_STRESS = [0.003, 0.005, 0.007, 0.010]


def _load_inputs(base: BacktestConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    analyst_snapshots = storage.read_table("analyst_snapshot_history")
    analyst_consensus = storage.read_table("analyst_consensus_history")
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
    return prices, financials, membership, analyst_snapshots


def _apply_profile(base: BacktestConfig, profile: ProfileSpec) -> BacktestConfig:
    config = deepcopy(base)
    config.project.name = profile.label
    for key, value in profile.scoring_updates.items():
        setattr(config.scoring, key, value)
    return config


def _apply_dates(config: BacktestConfig, start_date: str, end_date: str) -> BacktestConfig:
    payload = config.model_dump()
    payload["backtest"]["start_date"] = start_date
    payload["backtest"]["end_date"] = end_date
    return BacktestConfig.model_validate(payload)


def _apply_commission(config: BacktestConfig, commission_rate: float) -> BacktestConfig:
    payload = config.model_dump()
    payload["costs"]["commission_rate"] = commission_rate
    return BacktestConfig.model_validate(payload)


def _max_drawdown(monthly: pd.DataFrame) -> float:
    values = pd.to_numeric(monthly["portfolio_value_end"], errors="coerce")
    peak = values.cummax()
    drawdown = values / peak - 1.0
    return float(drawdown.min())


def _summary_row(label: str, family: str, settings: BacktestConfig, result: dict) -> dict[str, object]:
    monthly = result["monthly_results"].copy()
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    return {
        "label": label,
        "family": family,
        "run_id": result["run_id"],
        "final_capital": float(monthly["portfolio_value_end"].iloc[-1]),
        "multiple": float(monthly["portfolio_value_end"].iloc[-1] / settings.backtest.initial_capital),
        "avg_month_return": float(net.mean()),
        "median_month_return": float(net.median()),
        "up_ratio": float((net > 0).mean()),
        "max_drawdown": _max_drawdown(monthly),
    }


def _period_row(label: str, family: str, period: str, result: dict) -> dict[str, object]:
    monthly = result["monthly_results"].copy()
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    return {
        "label": label,
        "family": family,
        "period": period,
        "months": len(monthly),
        "multiple": float(monthly["portfolio_value_end"].iloc[-1] / monthly["portfolio_value_start"].iloc[0]),
        "avg_month_return": float(net.mean()),
        "up_ratio": float((net > 0).mean()),
        "max_drawdown": _max_drawdown(monthly),
    }


def _cost_row(label: str, family: str, commission_rate: float, result: dict, initial_capital: float) -> dict[str, object]:
    monthly = result["monthly_results"].copy()
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    return {
        "label": label,
        "family": family,
        "commission_rate": commission_rate,
        "run_id": result["run_id"],
        "multiple": float(monthly["portfolio_value_end"].iloc[-1] / initial_capital),
        "up_ratio": float((net > 0).mean()),
        "max_drawdown": _max_drawdown(monthly),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_config(BASE_CONFIG)
    prices, financials, membership, analyst_snapshots = _load_inputs(base)

    summary_rows: list[dict[str, object]] = []
    period_rows: list[dict[str, object]] = []
    cost_rows: list[dict[str, object]] = []

    for profile in PROFILES:
        settings = _apply_profile(base, profile)
        full_result = run_monthly_rotation_backtest(
            settings,
            prices,
            financials,
            membership,
            analyst_snapshots=analyst_snapshots,
        )
        summary_rows.append(_summary_row(profile.label, profile.family, settings, full_result))

        for period, start_date, end_date in SPLITS:
            split_settings = _apply_dates(settings, start_date, end_date)
            split_result = run_monthly_rotation_backtest(
                split_settings,
                prices,
                financials,
                membership,
                analyst_snapshots=analyst_snapshots,
            )
            period_rows.append(_period_row(profile.label, profile.family, period, split_result))

        for commission_rate in COMMISSION_STRESS:
            stressed = _apply_commission(settings, commission_rate)
            stressed_result = run_monthly_rotation_backtest(
                stressed,
                prices,
                financials,
                membership,
                analyst_snapshots=analyst_snapshots,
            )
            cost_rows.append(
                _cost_row(
                    profile.label,
                    profile.family,
                    commission_rate,
                    stressed_result,
                    stressed.backtest.initial_capital,
                )
            )

    summary = pd.DataFrame(summary_rows).sort_values(["multiple", "max_drawdown"], ascending=[False, False]).reset_index(drop=True)
    periods = pd.DataFrame(period_rows)
    costs = pd.DataFrame(cost_rows)

    summary.to_csv(OUTPUT_DIR / "us_large_cap_tech_pit_signal_acceptance_summary.csv", index=False)
    periods.to_csv(OUTPUT_DIR / "us_large_cap_tech_pit_signal_acceptance_periods.csv", index=False)
    costs.to_csv(OUTPUT_DIR / "us_large_cap_tech_pit_signal_acceptance_costs.csv", index=False)

    baseline = summary.loc[summary["label"] == "tech_quality_earnings_baseline"].iloc[0]
    winner = summary.iloc[0]

    lines = [
        "# US Large-Cap Tech PIT Signal Acceptance Review",
        "",
        "Profiles:",
        "- tech_quality_earnings_baseline: current baseline",
        "- tech_announcement_freshness: freshness overlay",
        "- tech_announcement_drift: event-drift overlay",
        "- tech_asset_growth_guard: asset-growth penalty overlay",
        "",
        f"- Baseline multiple: `{baseline['multiple']:.2f}x`",
        f"- Baseline up ratio: `{baseline['up_ratio']:.2%}`",
        f"- Baseline max drawdown: `{baseline['max_drawdown']:.2%}`",
        "",
        f"- Candidate winner: `{winner['label']}`",
        f"- Winner multiple: `{winner['multiple']:.2f}x`",
        f"- Winner up ratio: `{winner['up_ratio']:.2%}`",
        f"- Winner max drawdown: `{winner['max_drawdown']:.2%}`",
        "",
        "Full-period summary:",
    ]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"- {row['label']} ({row['family']}): {row['multiple']:.2f}x, "
            f"up={row['up_ratio']:.2%}, dd={row['max_drawdown']:.2%}, "
            f"avg_month={row['avg_month_return']:.2%}"
        )
    lines.append("")
    lines.append("Cost stress:")
    for row in costs.sort_values(["label", "commission_rate"]).to_dict(orient="records"):
        lines.append(
            f"- {row['label']} @ {row['commission_rate']:.3f}: "
            f"{row['multiple']:.2f}x, up={row['up_ratio']:.2%}, dd={row['max_drawdown']:.2%}"
        )
    lines.append("")
    lines.append("Era-by-era:")
    for row in periods.sort_values(["period", "multiple"], ascending=[True, False]).to_dict(orient="records"):
        lines.append(
            f"- {row['period']} | {row['label']}: "
            f"{row['multiple']:.2f}x, up={row['up_ratio']:.2%}, dd={row['max_drawdown']:.2%}"
        )
    (OUTPUT_DIR / "us_large_cap_tech_pit_signal_acceptance_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

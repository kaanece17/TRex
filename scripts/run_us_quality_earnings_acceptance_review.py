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
DB_PATH = ROOT / "data" / "us_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


@dataclass(frozen=True)
class ProfileSpec:
    label: str
    family: str
    config_path: Path


PROFILES = [
    ProfileSpec(
        label="us_momentum",
        family="baseline",
        config_path=ROOT / "config.us_industrials_momentum.yaml",
    ),
    ProfileSpec(
        label="us_quality_scorecap",
        family="quality",
        config_path=ROOT / "config.us_industrials_quality_scorecap.yaml",
    ),
    ProfileSpec(
        label="us_quality_earnings",
        family="quality_earnings",
        config_path=ROOT / "config.us_industrials_quality_earnings.yaml",
    ),
]

SPLITS = [
    ("2020_2021", "2020-01-01", "2021-12-31"),
    ("2022_2023", "2022-01-01", "2023-12-31"),
    ("2024_2026ytd", "2024-01-01", "2026-05-31"),
    ("full_period", "2020-01-01", "2026-05-31"),
]

COMMISSION_STRESS = [0.003, 0.005, 0.007, 0.010]


def _load_inputs(base_config: BacktestConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
    membership = _load_membership_for_run(base_config)
    storage.close()
    return prices, financials, membership


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
    base_settings = load_config(PROFILES[0].config_path)
    prices, financials, membership = _load_inputs(base_settings)

    summary_rows: list[dict[str, object]] = []
    period_rows: list[dict[str, object]] = []
    cost_rows: list[dict[str, object]] = []

    for profile in PROFILES:
        settings = load_config(profile.config_path)
        full_result = run_monthly_rotation_backtest(settings, prices, financials, membership)
        summary_rows.append(_summary_row(profile.label, profile.family, settings, full_result))

        for period, start_date, end_date in SPLITS:
            split_settings = _apply_dates(settings, start_date, end_date)
            split_result = run_monthly_rotation_backtest(split_settings, prices, financials, membership)
            period_rows.append(_period_row(profile.label, profile.family, period, split_result))

        for commission_rate in COMMISSION_STRESS:
            stressed = _apply_commission(settings, commission_rate)
            stressed_result = run_monthly_rotation_backtest(stressed, prices, financials, membership)
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

    summary.to_csv(OUTPUT_DIR / "us_quality_earnings_acceptance_summary.csv", index=False)
    periods.to_csv(OUTPUT_DIR / "us_quality_earnings_acceptance_periods.csv", index=False)
    costs.to_csv(OUTPUT_DIR / "us_quality_earnings_acceptance_costs.csv", index=False)

    lines = [
        "# US Quality + Earnings Acceptance Review",
        "",
        "Profiles:",
        "- us_momentum: original baseline",
        "- us_quality_scorecap: old quality winner",
        "- us_quality_earnings: current promoted winner",
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
    (OUTPUT_DIR / "us_quality_earnings_acceptance_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

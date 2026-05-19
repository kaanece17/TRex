from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
BASELINE_CONFIG = ROOT / "config.formula_research.yaml"


def _load_inputs():
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    storage.close()
    return prices, financials


def _max_drawdown(monthly: pd.DataFrame) -> float:
    values = pd.to_numeric(monthly["portfolio_value_end"], errors="coerce")
    peak = values.cummax()
    dd = values / peak - 1
    return float(dd.min())


def _summary_row(label: str, settings: BacktestConfig, result: dict) -> dict[str, object]:
    monthly = result["monthly_results"].copy()
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    return {
        "label": label,
        "run_id": result["run_id"],
        "final_capital": float(monthly["portfolio_value_end"].iloc[-1]),
        "multiple": float(monthly["portfolio_value_end"].iloc[-1] / settings.backtest.initial_capital),
        "avg_month_return": float(net.mean()),
        "median_month_return": float(net.median()),
        "up_ratio": float((net > 0).mean()),
        "max_drawdown": _max_drawdown(monthly),
        "avg_selected_count": float(
            monthly["selected_symbols"]
            .fillna("")
            .map(lambda s: 0 if not s else len([x for x in s.split(",") if x.strip()]))
            .mean()
        ),
    }


def _period_rows(label: str, settings: BacktestConfig, result: dict) -> list[dict[str, object]]:
    monthly = result["monthly_results"].copy()
    monthly["bucket"] = "other"
    monthly.loc[monthly["month"].astype(str).str.startswith(("2020-", "2021-")), "bucket"] = "2020_2021"
    monthly.loc[monthly["month"].astype(str).str.startswith(("2022-", "2023-")), "bucket"] = "2022_2023"
    monthly.loc[monthly["month"].astype(str).str.startswith(("2024-", "2025-", "2026-")), "bucket"] = "2024_2026"
    rows = []
    for bucket, subset in monthly.groupby("bucket", sort=False):
        if bucket == "other":
            continue
        net = pd.to_numeric(subset["net_return"], errors="coerce")
        start = settings.backtest.initial_capital
        multiple = float((1 + net).prod())
        values = start * (1 + net).cumprod()
        peak = values.cummax()
        dd = values / peak - 1
        rows.append(
            {
                "label": label,
                "period": bucket,
                "multiple": multiple,
                "avg_month_return": float(net.mean()),
                "up_ratio": float((net > 0).mean()),
                "max_drawdown": float(dd.min()),
            }
        )
    return rows


def _run_variant(
    prices: pd.DataFrame,
    financials: pd.DataFrame,
    membership: pd.DataFrame,
    *,
    label: str,
    rank_threshold: int,
    lookback_days: int,
) -> tuple[BacktestConfig, dict]:
    baseline = load_config(BASELINE_CONFIG)
    values = baseline.model_dump()
    values["strategy"]["technical_confirmation_mode"] = "high_score_negative_momentum_veto"
    values["strategy"]["technical_confirmation_rank_threshold"] = rank_threshold
    values["strategy"]["technical_confirmation_lookback_days"] = lookback_days
    values["strategy"]["technical_confirmation_return_threshold"] = 0.0
    values["strategy"]["technical_confirmation_redistribute"] = True
    config = BacktestConfig.model_validate(values)
    result = run_monthly_rotation_backtest(config, prices, financials, membership)
    result["label"] = label
    return config, result


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prices, financials = _load_inputs()
    baseline_settings = load_config(BASELINE_CONFIG)
    membership = _load_membership_for_run(baseline_settings)

    baseline_result = run_monthly_rotation_backtest(baseline_settings, prices, financials, membership)
    variants = [
        ("accepted_top6", baseline_settings, baseline_result),
        ("tc_rank2_20d",) + _run_variant(prices, financials, membership, label="tc_rank2_20d", rank_threshold=2, lookback_days=20),
        ("tc_rank2_60d",) + _run_variant(prices, financials, membership, label="tc_rank2_60d", rank_threshold=2, lookback_days=60),
        ("tc_rank3_20d",) + _run_variant(prices, financials, membership, label="tc_rank3_20d", rank_threshold=3, lookback_days=20),
        ("tc_rank3_60d",) + _run_variant(prices, financials, membership, label="tc_rank3_60d", rank_threshold=3, lookback_days=60),
    ]

    summary_rows: list[dict[str, object]] = []
    period_rows: list[dict[str, object]] = []
    for label, settings, result in variants:
        summary_rows.append(_summary_row(label, settings, result))
        period_rows.extend(_period_rows(label, settings, result))

    summary = pd.DataFrame(summary_rows)
    periods = pd.DataFrame(period_rows)
    summary.to_csv(OUTPUT_DIR / "technical_confirmation_robustness_summary.csv", index=False)
    periods.to_csv(OUTPUT_DIR / "technical_confirmation_robustness_periods.csv", index=False)

    lines = ["Teknik confirmation robustness grid", ""]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"- {row['label']}: {row['multiple']:.4f}x, up={row['up_ratio']:.2%}, "
            f"dd={row['max_drawdown']:.2%}, avg_count={row['avg_selected_count']:.2f}"
        )
    (OUTPUT_DIR / "technical_confirmation_robustness_readout.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

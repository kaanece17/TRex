from __future__ import annotations

from copy import deepcopy
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
CANDIDATE_CONFIG = ROOT / "config.formula_research_technical_confirmation.yaml"


def _load_inputs():
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    storage.close()
    return prices, financials


def _run_config(config_path: Path, prices: pd.DataFrame, financials: pd.DataFrame) -> tuple[BacktestConfig, dict]:
    settings = load_config(config_path)
    membership = _load_membership_for_run(settings)
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    return settings, result


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
        "avg_selected_count": float(monthly["selected_symbols"].fillna("").map(lambda s: 0 if not s else len([x for x in s.split(',') if x.strip()])).mean()),
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


def _cost_stress_rows(prices: pd.DataFrame, financials: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    candidate_settings = load_config(CANDIDATE_CONFIG)
    membership = _load_membership_for_run(candidate_settings)
    for commission in [0.002, 0.003, 0.004, 0.005]:
        values = candidate_settings.model_dump()
        values["costs"]["commission_rate"] = commission
        stressed = BacktestConfig.model_validate(values)
        result = run_monthly_rotation_backtest(stressed, prices, financials, membership)
        summary = _summary_row(f"candidate_{commission:.3f}", stressed, result)
        summary["commission_rate"] = commission
        rows.append(summary)
    return rows


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prices, financials = _load_inputs()
    baseline_settings, baseline_result = _run_config(BASELINE_CONFIG, prices, financials)
    candidate_settings, candidate_result = _run_config(CANDIDATE_CONFIG, prices, financials)

    compare = pd.DataFrame(
        [
            _summary_row("accepted_top6", baseline_settings, baseline_result),
            _summary_row("technical_confirmation_candidate", candidate_settings, candidate_result),
        ]
    )
    periods = pd.DataFrame(
        _period_rows("accepted_top6", baseline_settings, baseline_result)
        + _period_rows("technical_confirmation_candidate", candidate_settings, candidate_result)
    )
    cost_stress = pd.DataFrame(_cost_stress_rows(prices, financials))

    compare.to_csv(OUTPUT_DIR / "technical_confirmation_candidate_compare.csv", index=False)
    periods.to_csv(OUTPUT_DIR / "technical_confirmation_candidate_periods.csv", index=False)
    cost_stress.to_csv(OUTPUT_DIR / "technical_confirmation_candidate_cost_stress.csv", index=False)

    lines = [
        f"baseline_run_id: {baseline_result['run_id']}",
        f"candidate_run_id: {candidate_result['run_id']}",
        "",
        "Kandidat: high-score + 60g negatif veto, replacement yok, kalanlara agirlik dagit",
        "",
        "Karsilastirma:",
    ]
    for row in compare.to_dict(orient="records"):
        lines.append(
            f"- {row['label']}: {row['multiple']:.4f}x, avg={row['avg_month_return']:.4f}, "
            f"up={row['up_ratio']:.2%}, dd={row['max_drawdown']:.2%}, avg_count={row['avg_selected_count']:.2f}"
        )
    (OUTPUT_DIR / "technical_confirmation_candidate_readout.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(candidate_result["run_id"])


if __name__ == "__main__":
    main()

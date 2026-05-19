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
ACCEPTED_CONFIG = ROOT / "config.formula_research.yaml"
MOMENTUM_CONFIG = ROOT / "config.formula_research_momentum.yaml"
TECHNICAL_CONFIG = ROOT / "config.formula_research_technical_confirmation.yaml"


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    storage.close()
    return prices, financials


def _max_drawdown(monthly: pd.DataFrame) -> float:
    values = pd.to_numeric(monthly["portfolio_value_end"], errors="coerce")
    peak = values.cummax()
    drawdown = values / peak - 1
    return float(drawdown.min())


def _avg_selected_count(monthly: pd.DataFrame) -> float:
    return float(
        monthly["selected_symbols"]
        .fillna("")
        .map(lambda s: 0 if not s else len([x for x in s.split(",") if x.strip()]))
        .mean()
    )


def _avg_max_weight(selected_positions: pd.DataFrame) -> float:
    if selected_positions.empty or "weight" not in selected_positions.columns:
        return 0.0
    weights = pd.to_numeric(selected_positions["weight"], errors="coerce")
    frame = selected_positions.assign(weight=weights)
    return float(frame.groupby("month")["weight"].max().mean())


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
        "avg_selected_count": _avg_selected_count(monthly),
        "avg_max_weight": _avg_max_weight(result["selected_positions"]),
    }


def _period_rows(label: str, family: str, result: dict) -> list[dict[str, object]]:
    monthly = result["monthly_results"].copy()
    monthly["month"] = monthly["month"].astype(str)
    periods = [
        ("2020_2021", "2020-01", "2021-12"),
        ("2022_2023", "2022-01", "2023-12"),
        ("2024_2026", "2024-01", "2026-04"),
    ]
    rows: list[dict[str, object]] = []
    for period_label, start, end in periods:
        subset = monthly[(monthly["month"] >= start) & (monthly["month"] <= end)].copy()
        if subset.empty:
            continue
        net = pd.to_numeric(subset["net_return"], errors="coerce")
        values = pd.to_numeric(subset["portfolio_value_end"], errors="coerce")
        peak = values.cummax()
        drawdown = values / peak - 1
        rows.append(
            {
                "label": label,
                "family": family,
                "period": period_label,
                "multiple": float((1 + net).prod()),
                "avg_month_return": float(net.mean()),
                "up_ratio": float((net > 0).mean()),
                "max_drawdown": float(drawdown.min()),
            }
        )
    return rows


def _cost_rows(
    label: str,
    family: str,
    base_settings: BacktestConfig,
    prices: pd.DataFrame,
    financials: pd.DataFrame,
    membership: pd.DataFrame,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for commission in (0.002, 0.004, 0.006):
        values = base_settings.model_dump()
        values["costs"]["commission_rate"] = commission
        stressed = BacktestConfig.model_validate(values)
        result = run_monthly_rotation_backtest(stressed, prices, financials, membership)
        monthly = result["monthly_results"].copy()
        rows.append(
            {
                "label": label,
                "family": family,
                "commission_rate": commission,
                "run_id": result["run_id"],
                "multiple": float(monthly["portfolio_value_end"].iloc[-1] / stressed.backtest.initial_capital),
                "up_ratio": float((pd.to_numeric(monthly["net_return"], errors="coerce") > 0).mean()),
                "max_drawdown": _max_drawdown(monthly),
            }
        )
    return rows


def _run_variant(settings: BacktestConfig, prices: pd.DataFrame, financials: pd.DataFrame, membership: pd.DataFrame) -> dict:
    return run_monthly_rotation_backtest(settings, prices, financials, membership)


def _momentum_variant(top_n: int, min_recent_return_20d: float) -> tuple[str, BacktestConfig]:
    base = load_config(MOMENTUM_CONFIG)
    values = base.model_dump()
    values["strategy"]["top_n"] = top_n
    values["filters"]["min_recent_return_20d"] = min_recent_return_20d
    label = f"momentum_top{top_n}_{min_recent_return_20d:+.2f}".replace("+", "p").replace("-", "m")
    return label, BacktestConfig.model_validate(values)


def _technical_variant(rank_threshold: int, lookback_days: int) -> tuple[str, BacktestConfig]:
    base = load_config(TECHNICAL_CONFIG)
    values = base.model_dump()
    values["strategy"]["technical_confirmation_rank_threshold"] = rank_threshold
    values["strategy"]["technical_confirmation_lookback_days"] = lookback_days
    label = f"technical_rank{rank_threshold}_{lookback_days}d"
    return label, BacktestConfig.model_validate(values)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prices, financials = _load_inputs()

    accepted_settings = load_config(ACCEPTED_CONFIG)
    membership = _load_membership_for_run(accepted_settings)

    accepted_result = _run_variant(accepted_settings, prices, financials, membership)

    momentum_variants = [
        _momentum_variant(4, 0.00),
        _momentum_variant(5, -0.01),
        _momentum_variant(5, 0.00),
        _momentum_variant(5, 0.01),
        _momentum_variant(6, 0.00),
    ]
    technical_variants = [
        _technical_variant(2, 20),
        _technical_variant(2, 60),
        _technical_variant(3, 20),
        _technical_variant(3, 60),
    ]

    summary_rows = [_summary_row("accepted_top6", "baseline", accepted_settings, accepted_result)]
    period_rows = _period_rows("accepted_top6", "baseline", accepted_result)
    cost_rows = _cost_rows("accepted_top6", "baseline", accepted_settings, prices, financials, membership)

    for label, settings in momentum_variants:
        result = _run_variant(settings, prices, financials, membership)
        summary_rows.append(_summary_row(label, "momentum", settings, result))
        period_rows.extend(_period_rows(label, "momentum", result))

    for label, settings in technical_variants:
        result = _run_variant(settings, prices, financials, membership)
        summary_rows.append(_summary_row(label, "technical", settings, result))
        period_rows.extend(_period_rows(label, "technical", result))

    # Cost stress only for the live finalists, not every neighbor.
    live_cost_profiles = [
        ("momentum_top5_p0.00", "momentum", _momentum_variant(5, 0.00)[1]),
        ("technical_rank2_20d", "technical", _technical_variant(2, 20)[1]),
    ]
    for label, family, settings in live_cost_profiles:
        cost_rows.extend(_cost_rows(label, family, settings, prices, financials, membership))

    summary = pd.DataFrame(summary_rows)
    periods = pd.DataFrame(period_rows)
    costs = pd.DataFrame(cost_rows)

    summary.to_csv(OUTPUT_DIR / "candidate_robustness_summary.csv", index=False)
    periods.to_csv(OUTPUT_DIR / "candidate_robustness_periods.csv", index=False)
    costs.to_csv(OUTPUT_DIR / "candidate_robustness_cost_stress.csv", index=False)

    lines = [
        "# Candidate Robustness Review",
        "",
        "Families:",
        "- momentum: top_n ve 20g momentum esigi komsulari",
        "- technical: rank threshold ve lookback komsulari",
        "",
        "Summary:",
    ]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"- {row['label']} ({row['family']}): {row['multiple']:.2f}x, "
            f"up={row['up_ratio']:.2%}, dd={row['max_drawdown']:.2%}, "
            f"avg_count={row['avg_selected_count']:.2f}, avg_max_w={row['avg_max_weight']:.2%}"
        )
    (OUTPUT_DIR / "candidate_robustness_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

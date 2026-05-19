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


def _max_drawdown(values: pd.Series) -> float:
    peak = values.cummax()
    dd = values / peak - 1
    return float(dd.min())


def _build_variant(
    *,
    rank_threshold: int,
    lookback_days: int,
) -> BacktestConfig:
    baseline = load_config(BASELINE_CONFIG)
    values = baseline.model_dump()
    values["strategy"]["technical_confirmation_mode"] = "high_score_negative_momentum_veto"
    values["strategy"]["technical_confirmation_rank_threshold"] = rank_threshold
    values["strategy"]["technical_confirmation_lookback_days"] = lookback_days
    values["strategy"]["technical_confirmation_return_threshold"] = 0.0
    values["strategy"]["technical_confirmation_redistribute"] = True
    return BacktestConfig.model_validate(values)


def _open_gap_ratio(selected: pd.DataFrame) -> float:
    if selected.empty or "open_gap_count" not in selected.columns:
        return 0.0
    counts = pd.to_numeric(selected["open_gap_count"], errors="coerce").fillna(0)
    return float((counts > 0).mean())


def _worst_quarters(monthly: pd.DataFrame, label: str) -> pd.DataFrame:
    net = monthly.copy()
    net["quarter"] = pd.PeriodIndex(pd.to_datetime(net["month"] + "-01"), freq="Q").astype(str)
    quarter_returns = (
        net.groupby("quarter", as_index=False)["net_return"]
        .apply(lambda s: float((1 + pd.to_numeric(s, errors="coerce")).prod() - 1))
        .rename(columns={"net_return": "quarter_return"})
        .sort_values("quarter_return")
        .head(5)
    )
    quarter_returns.insert(0, "label", label)
    return quarter_returns


def _concentration_summary(selected: pd.DataFrame, monthly: pd.DataFrame, label: str) -> dict[str, object]:
    if selected.empty:
        return {
            "label": label,
            "avg_top_weight": 0.0,
            "max_top_weight": 0.0,
            "avg_symbol_count": 0.0,
        }
    top_weights = (
        selected.groupby("month", as_index=False)["weight"]
        .max()
        .rename(columns={"weight": "top_weight"})
    )
    counts = (
        selected.groupby("month", as_index=False)["symbol"]
        .nunique()
        .rename(columns={"symbol": "symbol_count"})
    )
    merged = top_weights.merge(counts, on="month", how="left")
    return {
        "label": label,
        "avg_top_weight": float(merged["top_weight"].mean()),
        "max_top_weight": float(merged["top_weight"].max()),
        "avg_symbol_count": float(merged["symbol_count"].mean()),
    }


def _summary_row(label: str, settings: BacktestConfig, result: dict) -> dict[str, object]:
    monthly = result["monthly_results"].copy()
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    values = pd.to_numeric(monthly["portfolio_value_end"], errors="coerce")
    selected = result["selected_positions"].copy()
    row = {
        "label": label,
        "run_id": result["run_id"],
        "multiple": float(values.iloc[-1] / settings.backtest.initial_capital),
        "up_ratio": float((net > 0).mean()),
        "max_drawdown": _max_drawdown(values),
        "open_gap_ratio": _open_gap_ratio(selected),
    }
    row.update(_concentration_summary(selected, monthly, label))
    return row


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prices, financials = _load_inputs()
    membership = _load_membership_for_run(load_config(BASELINE_CONFIG))

    finalists = [
        ("tc_rank2_20d", _build_variant(rank_threshold=2, lookback_days=20)),
        ("tc_rank3_60d", _build_variant(rank_threshold=3, lookback_days=60)),
    ]

    runs: list[tuple[str, BacktestConfig, dict]] = []
    for label, config in finalists:
        result = run_monthly_rotation_backtest(config, prices, financials, membership)
        runs.append((label, config, result))

    summary = pd.DataFrame([_summary_row(label, config, result) for label, config, result in runs])
    worst_quarters = pd.concat(
        [_worst_quarters(result["monthly_results"].copy(), label) for label, _, result in runs],
        ignore_index=True,
    )

    summary.to_csv(OUTPUT_DIR / "technical_confirmation_finalists_summary.csv", index=False)
    worst_quarters.to_csv(OUTPUT_DIR / "technical_confirmation_finalists_worst_quarters.csv", index=False)

    lines = ["Teknik confirmation finalistleri", ""]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"- {row['label']}: {row['multiple']:.4f}x, dd={row['max_drawdown']:.2%}, "
            f"open_gap={row['open_gap_ratio']:.2%}, avg_top_weight={row['avg_top_weight']:.2%}, "
            f"avg_symbol_count={row['avg_symbol_count']:.2f}"
        )
    (OUTPUT_DIR / "technical_confirmation_finalists_readout.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.metrics import calculate_equity_curve, calculate_summary
from bist_factor_backtest.config import BacktestConfig


def export_excel_report(
    path: str | Path,
    config: BacktestConfig,
    monthly_results: pd.DataFrame,
    selected_positions: pd.DataFrame,
    rejected_candidates: pd.DataFrame,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame([calculate_summary(monthly_results, config.backtest.initial_capital)])
    summary["universe_mode"] = config.universe.mode
    summary["universe_source"] = config.universe.source
    summary["universe_confidence"] = _universe_confidence(selected_positions)
    summary["survivorship_bias_warning"] = config.universe.mode == "current_static"
    equity_curve = calculate_equity_curve(monthly_results) if not monthly_results.empty else pd.DataFrame()
    drawdown = equity_curve[["month", "drawdown"]] if not equity_curve.empty else pd.DataFrame()
    used = _used_financial_statements(selected_positions)
    config_data = pd.DataFrame([config.model_dump(mode="json")])
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        monthly_results.to_excel(writer, sheet_name="Monthly Returns", index=False)
        selected_positions.to_excel(writer, sheet_name="Selected Positions", index=False)
        used.to_excel(writer, sheet_name="Used Financial Statements", index=False)
        equity_curve.to_excel(writer, sheet_name="Equity Curve", index=False)
        drawdown.to_excel(writer, sheet_name="Drawdown", index=False)
        rejected_candidates.to_excel(writer, sheet_name="Rejected Candidates", index=False)
        config_data.to_excel(writer, sheet_name="Config", index=False)


def _used_financial_statements(selected_positions: pd.DataFrame) -> pd.DataFrame:
    if selected_positions.empty:
        return pd.DataFrame()
    columns = [
        "month",
        "symbol",
        "used_period_end",
        "used_announcement_datetime",
        "rebalance_datetime",
        "source_statement_id",
        "source_url",
    ]
    data = selected_positions.copy()
    if "rebalance_datetime" not in data.columns:
        data["rebalance_datetime"] = pd.NaT
    used = data[[column for column in columns if column in data.columns]].copy()
    used["is_point_in_time_valid"] = pd.to_datetime(used["used_announcement_datetime"]) <= pd.to_datetime(
        used["rebalance_datetime"]
    )
    return used


def _universe_confidence(selected_positions: pd.DataFrame) -> str:
    if selected_positions.empty or "universe_confidence" not in selected_positions.columns:
        return "unknown"
    values = set(selected_positions["universe_confidence"].dropna().astype(str))
    if "low" in values:
        return "low"
    if "medium" in values:
        return "medium"
    return "high" if values else "unknown"

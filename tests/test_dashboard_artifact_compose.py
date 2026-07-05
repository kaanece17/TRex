from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bist_factor_backtest.cli import _load_artifact_backtest_result, _load_backtest_result_for_run
from bist_factor_backtest.data.storage import DuckDbStorage


def test_loadArtifactBacktestResult_prefersEarliestUnresolvedMonth_overCurrentSummaryMonth(tmp_path):
    profile_root = tmp_path / "momentum_watchlist"
    profile_root.mkdir(parents=True)
    (profile_root / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "generated_at": "2026-07-05T14:28:49.690018+00:00",
                "current_month": "2026-07",
                "open_month_excluded_from_metrics": True,
            }
        ),
        encoding="utf-8",
    )
    (profile_root / "monthly_returns.json").write_text(
        json.dumps(
            [
                {"run_id": "run-1", "month": "2026-06", "net_return": 0.01},
                {"run_id": "run-1", "month": "2026-07", "net_return": None},
            ]
        ),
        encoding="utf-8",
    )
    (profile_root / "selected_positions.json").write_text(
        json.dumps(
            [
                {
                    "run_id": "run-1",
                    "month": "2026-06",
                    "symbol": "ASTOR",
                    "buy_price": 10.0,
                    "sell_price": None,
                    "gross_return": None,
                    "net_return": None,
                    "reason": None,
                },
                {
                    "run_id": "run-1",
                    "month": "2026-07",
                    "symbol": "CCOLA",
                    "buy_price": None,
                    "sell_price": None,
                    "gross_return": None,
                    "net_return": None,
                    "reason": None,
                },
            ]
        ),
        encoding="utf-8",
    )

    result = _load_artifact_backtest_result(tmp_path, "momentum_watchlist")

    assert result is not None
    assert result["open_month"] == "2026-06"


def test_loadBacktestResultForRun_detectsEarliestUnresolvedMonth_fromSelectedPositions(tmp_path):
    db_path = tmp_path / "test.duckdb"
    storage = DuckDbStorage(db_path)
    storage.initialize()
    storage.append_table(
        "backtest_runs",
        pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "created_at": "2026-07-05T14:28:49+00:00",
                    "config_hash": "hash",
                    "start_date": "2020-01-01",
                    "end_date": "2026-07-01",
                    "initial_capital": 100000.0,
                    "notes": None,
                }
            ]
        ),
    )
    storage.append_table(
        "backtest_monthly_results",
        pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "month": "2026-06",
                    "rebalance_datetime": None,
                    "buy_date": "2026-06-01",
                    "sell_date": "2026-07-01",
                    "gross_return": 0.01,
                    "net_return": 0.01,
                    "portfolio_value_start": 100000.0,
                    "portfolio_value_end": 101000.0,
                    "selected_symbols": "ASTOR",
                },
                {
                    "run_id": "run-1",
                    "month": "2026-07",
                    "rebalance_datetime": None,
                    "buy_date": "2026-07-01",
                    "sell_date": None,
                    "gross_return": None,
                    "net_return": None,
                    "portfolio_value_start": 101000.0,
                    "portfolio_value_end": None,
                    "selected_symbols": "CCOLA",
                },
            ]
        ),
    )
    storage.append_table(
        "backtest_selected_positions",
        pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "month": "2026-06",
                    "symbol": "ASTOR",
                    "buy_price": 10.0,
                    "sell_price": None,
                    "gross_return": None,
                    "net_return": None,
                    "used_period_end": "2025-12-01",
                    "used_announcement_datetime": "2026-02-17T00:00:00",
                },
                {
                    "run_id": "run-1",
                    "month": "2026-07",
                    "symbol": "CCOLA",
                    "buy_price": None,
                    "sell_price": None,
                    "gross_return": None,
                    "net_return": None,
                    "used_period_end": "2026-03-01",
                    "used_announcement_datetime": "2026-05-11T00:00:00",
                },
            ]
        ),
    )

    result = _load_backtest_result_for_run(storage, "run-1")
    storage.close()

    assert result is not None
    assert result["open_month"] == "2026-06"

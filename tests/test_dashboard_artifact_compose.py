from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bist_factor_backtest.cli import (
    _compose_dashboard_result,
    _load_artifact_backtest_result,
    _load_backtest_result_for_run,
)
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


def test_loadArtifactBacktestResult_marksSameMonthExitAsUnresolved_forOpenToOpen(tmp_path):
    profile_root = tmp_path / "momentum_watchlist"
    profile_root.mkdir(parents=True)
    (profile_root / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "generated_at": "2026-07-05T14:28:49.690018+00:00",
                "current_month": "2026-05",
                "open_month_excluded_from_metrics": False,
            }
        ),
        encoding="utf-8",
    )
    (profile_root / "monthly_returns.json").write_text(
        json.dumps(
            [
                {"run_id": "run-1", "month": "2026-04", "net_return": 0.01},
                {"run_id": "run-1", "month": "2026-05", "net_return": 0.02},
            ]
        ),
        encoding="utf-8",
    )
    (profile_root / "selected_positions.json").write_text(
        json.dumps(
            [
                {
                    "run_id": "run-1",
                    "month": "2026-04",
                    "symbol": "AAA",
                    "buy_price": 10.0,
                    "sell_price": 11.0,
                    "gross_return": 0.1,
                    "net_return": 0.09,
                    "reason": None,
                    "buy_date": "2026-04-01",
                    "sell_date": "2026-05-02",
                },
                {
                    "run_id": "run-1",
                    "month": "2026-05",
                    "symbol": "BBB",
                    "buy_price": 10.0,
                    "sell_price": 10.5,
                    "gross_return": 0.05,
                    "net_return": 0.04,
                    "reason": None,
                    "buy_date": "2026-05-04",
                    "sell_date": "2026-05-13",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = _load_artifact_backtest_result(
        tmp_path,
        "momentum_watchlist",
        execution_mode="rebalance_open_to_open",
    )

    assert result is not None
    assert result["open_month"] == "2026-05"


def test_loadBacktestResultForRun_marksSameMonthExitAsUnresolved_forOpenToOpen(tmp_path):
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
                    "month": "2026-05",
                    "rebalance_datetime": None,
                    "buy_date": "2026-05-04",
                    "sell_date": "2026-05-13",
                    "gross_return": 0.01,
                    "net_return": 0.01,
                    "portfolio_value_start": 100000.0,
                    "portfolio_value_end": 101000.0,
                    "selected_symbols": "KOCMT,MEGMT",
                }
            ]
        ),
    )
    storage.append_table(
        "backtest_selected_positions",
        pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "month": "2026-05",
                    "symbol": "KOCMT",
                    "buy_price": 10.0,
                    "sell_price": 10.5,
                    "gross_return": 0.05,
                    "net_return": 0.04,
                    "buy_date": "2026-05-04",
                    "sell_date": "2026-05-13",
                    "used_period_end": "2025-12-01",
                    "used_announcement_datetime": "2026-03-02T00:00:00",
                }
            ]
        ),
    )

    result = _load_backtest_result_for_run(
        storage,
        "run-1",
        execution_mode="rebalance_open_to_open",
    )
    storage.close()

    assert result is not None
    assert result["open_month"] == "2026-05"


def test_composeDashboardResult_rebasesPreviewPortfolioValues_whenOpenMonthIsReplaced():
    historical_result = {
        "run_id": "run-1",
        "created_at": None,
        "monthly_results": pd.DataFrame(
            [
                {"month": "2026-04", "net_return": 0.10, "portfolio_value_start": 100_000.0, "portfolio_value_end": 110_000.0},
                {"month": "2026-05", "net_return": 0.20, "portfolio_value_start": 110_000.0, "portfolio_value_end": 132_000.0},
                {"month": "2026-06", "net_return": -0.50, "portfolio_value_start": 132_000.0, "portfolio_value_end": 66_000.0},
            ]
        ),
        "selected_positions": pd.DataFrame(
            [{"month": "2026-05", "symbol": "AAA"}, {"month": "2026-06", "symbol": "BBB"}]
        ),
        "planned_positions": pd.DataFrame(),
        "rejected_candidates": pd.DataFrame(),
        "candidate_diagnostics": pd.DataFrame(),
        "open_month": "2026-06",
    }
    preview_result = {
        "run_id": "run-2",
        "created_at": None,
        "monthly_results": pd.DataFrame(
            [
                {"month": "2026-06", "net_return": -0.10, "portfolio_value_start": 100_000.0, "portfolio_value_end": 90_000.0},
                {"month": "2026-07", "net_return": 0.05, "portfolio_value_start": 90_000.0, "portfolio_value_end": 94_500.0},
            ]
        ),
        "selected_positions": pd.DataFrame(
            [{"month": "2026-06", "symbol": "CCC"}, {"month": "2026-07", "symbol": "DDD"}]
        ),
        "planned_positions": pd.DataFrame(),
        "rejected_candidates": pd.DataFrame(),
        "candidate_diagnostics": pd.DataFrame(),
        "open_month": None,
    }

    result = _compose_dashboard_result(historical_result, preview_result)

    monthly = result["monthly_results"][["month", "portfolio_value_start", "portfolio_value_end"]].reset_index(drop=True)
    assert monthly.to_dict("records") == [
        {"month": "2026-04", "portfolio_value_start": 100_000.0, "portfolio_value_end": 110_000.0},
        {"month": "2026-05", "portfolio_value_start": 110_000.0, "portfolio_value_end": 132_000.0},
        {"month": "2026-06", "portfolio_value_start": 132_000.0, "portfolio_value_end": 118_800.0},
        {"month": "2026-07", "portfolio_value_start": 118_800.0, "portfolio_value_end": 124_740.0},
    ]

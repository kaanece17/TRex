import pandas as pd
import pytest

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.config import BacktestConfig


class TestRunMonthlyRotationBacktest:
    def test_runMonthlyRotationBacktest_emptyCandidates_returnsEmptyMonth(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "Europe/Istanbul"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {
                    "name": "BIST_SANAYI",
                    "source": "csv",
                    "symbols_file": "symbols.csv",
                    "membership_file": "membership.csv",
                    "mode": "reconstructed_historical",
                },
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 1,
                    "rebalance_frequency": "monthly",
                    "rebalance_day": "first_trading_day",
                    "rebalance_time": "market_open",
                    "market_open_time": "10:00",
                    "buy_rule": "first_trading_day_open",
                    "sell_rule": "last_trading_day_open",
                    "execution_mode": "ideal_open",
                    "weighting": "equal_weight",
                    "if_less_than_top_n": "use_available",
                },
                "scoring": {"formula": "x1_plus_x2", "use_ttm": True, "firm_value_mode": "market_cap"},
                "costs": {"commission_rate": 0.001},
                "filters": {
                    "require_positive_equity": True,
                    "require_positive_net_income_ttm": True,
                    "require_positive_previous_net_income_ttm": True,
                    "require_positive_operating_profit_ttm": True,
                    "require_positive_firm_value": True,
                    "require_shares_outstanding": True,
                    "min_avg_turnover_20d": 1,
                },
                "backtest": {"start_date": "2020-01-01", "end_date": "2020-01-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2019-12-31", "open": 99, "high": 99, "low": 99, "close": 99, "adjusted_close": 99, "volume": 1000},
                {"symbol": "AAA", "date": "2020-01-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100, "volume": 1000},
                {"symbol": "AAA", "date": "2020-01-31", "open": 110, "high": 110, "low": 110, "close": 110, "adjusted_close": 110, "volume": 1000},
            ]
        )
        financials = pd.DataFrame(columns=["symbol", "announcement_datetime", "announcement_date"])
        membership = pd.DataFrame(columns=["symbol", "universe_name", "start_date", "end_date"])

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert result["monthly_results"]["month"].tolist() == ["2020-01"]
        assert result["monthly_results"]["selected_symbols"].tolist() == [""]

    def test_runMonthlyRotationBacktest_syntheticData_returnsPitValidMonthlyResult(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "Europe/Istanbul"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {
                    "name": "BIST_SANAYI",
                    "source": "csv",
                    "symbols_file": "symbols.csv",
                    "membership_file": "membership.csv",
                    "mode": "historical",
                },
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 1,
                    "rebalance_frequency": "monthly",
                    "rebalance_day": "first_trading_day",
                    "rebalance_time": "market_open",
                    "market_open_time": "10:00",
                    "buy_rule": "first_trading_day_open",
                    "sell_rule": "last_trading_day_open",
                    "execution_mode": "ideal_open",
                    "weighting": "equal_weight",
                    "if_less_than_top_n": "use_available",
                },
                "scoring": {"formula": "x1_plus_x2", "use_ttm": True, "firm_value_mode": "market_cap"},
                "costs": {"commission_rate": 0.001},
                "filters": {
                    "require_positive_equity": True,
                    "require_positive_net_income_ttm": True,
                    "require_positive_previous_net_income_ttm": True,
                    "require_positive_operating_profit_ttm": True,
                    "require_positive_firm_value": True,
                    "require_shares_outstanding": True,
                    "min_avg_turnover_20d": 1,
                },
                "backtest": {"start_date": "2024-05-01", "end_date": "2024-05-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-04-29", "open": 8, "high": 8, "low": 8, "close": 8, "adjusted_close": 8, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-31", "open": 110, "high": 110, "low": 110, "close": 110, "adjusted_close": 110, "volume": 1000},
            ]
        )
        financials = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q1",
                    "fiscal_quarter": 1,
                    "announcement_datetime": "2024-04-30 18:00",
                    "announcement_date": "2024-04-30",
                    "net_income": 200,
                    "equity": 1000,
                    "operating_profit": 150,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 200,
                    "operating_profit_ttm": 150,
                    "previous_net_income_ttm": 100,
                    "net_income_growth": 1,
                    "source_statement_id": "s1",
                    "source_url": "kap",
                    "raw_hash": "hash",
                }
            ]
        )
        membership = pd.DataFrame(
            [{"symbol": "AAA", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2020-01-01").date(), "end_date": pd.NaT}]
        )
        expected = "AAA"

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert result["monthly_results"]["selected_symbols"].iloc[0] == expected
        assert result["monthly_results"]["net_return"].iloc[0] == pytest.approx(0.098)
        assert result["selected_positions"]["firm_value"].iloc[0] == 1000
        assert result["selected_positions"]["universe_confidence"].iloc[0] == "low"

    def test_runMonthlyRotationBacktest_missingSelectedSymbolPrice_returnsCashMonthAndRejectedCandidate(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "Europe/Istanbul"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {
                    "name": "BIST_SANAYI",
                    "source": "csv",
                    "symbols_file": "symbols.csv",
                    "membership_file": "membership.csv",
                    "mode": "historical",
                },
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 1,
                    "rebalance_frequency": "monthly",
                    "rebalance_day": "first_trading_day",
                    "rebalance_time": "market_open",
                    "market_open_time": "10:00",
                    "buy_rule": "first_trading_day_open",
                    "sell_rule": "last_trading_day_open",
                    "execution_mode": "ideal_open",
                    "weighting": "equal_weight",
                    "if_less_than_top_n": "use_available",
                },
                "scoring": {"formula": "x1_plus_x2", "use_ttm": True, "firm_value_mode": "market_cap"},
                "costs": {"commission_rate": 0.001},
                "filters": {
                    "require_positive_equity": True,
                    "require_positive_net_income_ttm": True,
                    "require_positive_previous_net_income_ttm": True,
                    "require_positive_operating_profit_ttm": True,
                    "require_positive_firm_value": True,
                    "require_shares_outstanding": True,
                    "min_avg_turnover_20d": 1,
                },
                "backtest": {"start_date": "2024-05-01", "end_date": "2024-05-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-04-29", "open": 8, "high": 8, "low": 8, "close": 8, "adjusted_close": 8, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-31", "open": 110, "high": 110, "low": 110, "close": 110, "adjusted_close": 110, "volume": 1000},
            ]
        )
        financials = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q1",
                    "fiscal_quarter": 1,
                    "announcement_datetime": "2024-04-30 18:00",
                    "announcement_date": "2024-04-30",
                    "net_income": 200,
                    "equity": 1000,
                    "operating_profit": 150,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 200,
                    "operating_profit_ttm": 150,
                    "previous_net_income_ttm": 100,
                    "net_income_growth": 1,
                    "source_statement_id": "s1",
                    "source_url": "kap",
                    "raw_hash": "hash",
                }
            ]
        )
        membership = pd.DataFrame(
            [{"symbol": "AAA", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2020-01-01").date(), "end_date": pd.NaT}]
        )
        expected = ""

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert result["monthly_results"]["selected_symbols"].iloc[0] == expected
        assert result["monthly_results"]["net_return"].iloc[0] == 0
        assert result["rejected_candidates"]["reason"].iloc[0] == "missing_price"

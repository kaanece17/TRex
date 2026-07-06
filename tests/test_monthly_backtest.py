import pandas as pd
import pytest

from bist_factor_backtest.backtest.monthly_rotation import _apply_rebalance_frequency, run_monthly_rotation_backtest
from bist_factor_backtest.config import BacktestConfig


class TestRebalanceFrequency:
    def test_applyRebalanceFrequency_bimonthlyAndQuarterly_filtersMonthList(self):
        months = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]

        assert _apply_rebalance_frequency(months, "monthly") == months
        assert _apply_rebalance_frequency(months, "bimonthly") == ["2024-01", "2024-03", "2024-05"]
        assert _apply_rebalance_frequency(months, "quarterly") == ["2024-01", "2024-04"]


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

    def test_runMonthlyRotationBacktest_rebalanceOpenToOpen_usesNextMonthOpenAsExit(self):
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
                    "execution_mode": "rebalance_open_to_open",
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
                "backtest": {"start_date": "2024-05-01", "end_date": "2024-07-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-04-29", "open": 8, "high": 8, "low": 8, "close": 8, "adjusted_close": 8, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-31", "open": 110, "high": 110, "low": 110, "close": 110, "adjusted_close": 110, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-03", "open": 120, "high": 120, "low": 120, "close": 120, "adjusted_close": 120, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-28", "open": 125, "high": 125, "low": 125, "close": 125, "adjusted_close": 125, "volume": 1000},
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

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        may_row = result["monthly_results"][result["monthly_results"]["month"] == "2024-05"].iloc[0]
        may_position = result["selected_positions"][result["selected_positions"]["month"] == "2024-05"].iloc[0]

        assert may_position["sell_date"] == pd.Timestamp("2024-06-03").date()
        assert may_row["net_return"] == pytest.approx(0.198)

    def test_runMonthlyRotationBacktest_rebalanceOpenToOpen_excludesIncompleteTailMonth(self):
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
                    "execution_mode": "rebalance_open_to_open",
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
                "backtest": {"start_date": "2024-05-01", "end_date": "2024-07-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-04-29", "open": 8, "high": 8, "low": 8, "close": 8, "adjusted_close": 8, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-31", "open": 110, "high": 110, "low": 110, "close": 110, "adjusted_close": 110, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-03", "open": 120, "high": 120, "low": 120, "close": 120, "adjusted_close": 120, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-28", "open": 125, "high": 125, "low": 125, "close": 125, "adjusted_close": 125, "volume": 1000},
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

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert result["monthly_results"]["month"].tolist() == ["2024-05"]

    def test_runMonthlyRotationBacktest_rebalanceOpenToOpen_skipsSinglePartialMonth(self):
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
                    "execution_mode": "rebalance_open_to_open",
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
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-13", "open": 110, "high": 110, "low": 110, "close": 110, "adjusted_close": 110, "volume": 1000},
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

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert result["monthly_results"].empty
        assert result["selected_positions"].empty

    def test_runMonthlyRotationBacktest_holdBufferRank_retainsPreviousHoldingWithinBuffer(self):
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
                    "hold_buffer_rank": 2,
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
                "costs": {"commission_rate": 0.0},
                "filters": {
                    "require_positive_equity": True,
                    "require_positive_net_income_ttm": True,
                    "require_positive_previous_net_income_ttm": True,
                    "require_positive_operating_profit_ttm": True,
                    "require_positive_firm_value": True,
                    "require_shares_outstanding": True,
                    "min_avg_turnover_20d": 1,
                },
                "backtest": {"start_date": "2024-05-01", "end_date": "2024-07-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-04-29", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-31", "open": 11, "high": 11, "low": 11, "close": 11, "adjusted_close": 11, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-03", "open": 11, "high": 11, "low": 11, "close": 11, "adjusted_close": 11, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-28", "open": 12, "high": 12, "low": 12, "close": 12, "adjusted_close": 12, "volume": 1000},
                {"symbol": "BBB", "date": "2024-04-29", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "BBB", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-02", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-31", "open": 11, "high": 11, "low": 11, "close": 11, "adjusted_close": 11, "volume": 1000},
                {"symbol": "BBB", "date": "2024-06-03", "open": 11, "high": 11, "low": 11, "close": 11, "adjusted_close": 11, "volume": 1000},
                {"symbol": "BBB", "date": "2024-06-28", "open": 13, "high": 13, "low": 13, "close": 13, "adjusted_close": 13, "volume": 1000},
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
                    "net_income": 100,
                    "equity": 1000,
                    "operating_profit": 60,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 100,
                    "operating_profit_ttm": 60,
                    "previous_net_income_ttm": 50,
                    "net_income_growth": 1,
                    "source_statement_id": "s1",
                    "source_url": "kap",
                    "raw_hash": "hash1",
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q1",
                    "fiscal_quarter": 1,
                    "announcement_datetime": "2024-04-30 18:00",
                    "announcement_date": "2024-04-30",
                    "net_income": 80,
                    "equity": 1000,
                    "operating_profit": 50,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 80,
                    "operating_profit_ttm": 50,
                    "previous_net_income_ttm": 50,
                    "net_income_growth": 0.6,
                    "source_statement_id": "s2",
                    "source_url": "kap",
                    "raw_hash": "hash2",
                },
            ]
        )
        membership = pd.DataFrame(
            [
                {"symbol": "AAA", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2020-01-01").date(), "end_date": pd.NaT},
                {"symbol": "BBB", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2024-06-01").date(), "end_date": pd.NaT},
            ]
        )

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert result["monthly_results"]["selected_symbols"].tolist() == ["AAA", "AAA"]

    def test_runMonthlyRotationBacktest_highReturnCooldown_excludesWinnerNextMonth(self):
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
                    "execution_mode": "rebalance_open_to_open",
                    "weighting": "equal_weight",
                    "if_less_than_top_n": "use_available",
                    "symbol_cooldown_exclusion_mode": "prior_high_return_same_symbol_exclude",
                    "symbol_cooldown_exclusion_lookback_months": 1,
                    "symbol_cooldown_exclusion_return_threshold": 0.40,
                },
                "scoring": {"formula": "x1_plus_x2", "use_ttm": True, "firm_value_mode": "market_cap"},
                "costs": {"commission_rate": 0.0},
                "filters": {
                    "require_positive_equity": True,
                    "require_positive_net_income_ttm": True,
                    "require_positive_previous_net_income_ttm": True,
                    "require_positive_operating_profit_ttm": True,
                    "require_positive_firm_value": True,
                    "require_shares_outstanding": True,
                    "min_avg_turnover_20d": 0,
                },
                "backtest": {"start_date": "2024-05-01", "end_date": "2024-07-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-04-01", "open": 9, "high": 9, "low": 9, "close": 9, "adjusted_close": 9, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-31", "open": 14, "high": 14, "low": 14, "close": 14, "adjusted_close": 14, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-03", "open": 15, "high": 15, "low": 15, "close": 15, "adjusted_close": 15, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-28", "open": 16, "high": 16, "low": 16, "close": 16, "adjusted_close": 16, "volume": 1000},
                {"symbol": "AAA", "date": "2024-07-01", "open": 16.5, "high": 16.5, "low": 16.5, "close": 16.5, "adjusted_close": 16.5, "volume": 1000},
                {"symbol": "BBB", "date": "2024-04-01", "open": 9, "high": 9, "low": 9, "close": 9, "adjusted_close": 9, "volume": 1000},
                {"symbol": "BBB", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-02", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-31", "open": 10.5, "high": 10.5, "low": 10.5, "close": 10.5, "adjusted_close": 10.5, "volume": 1000},
                {"symbol": "BBB", "date": "2024-06-03", "open": 11, "high": 11, "low": 11, "close": 11, "adjusted_close": 11, "volume": 1000},
                {"symbol": "BBB", "date": "2024-06-28", "open": 11.5, "high": 11.5, "low": 11.5, "close": 11.5, "adjusted_close": 11.5, "volume": 1000},
                {"symbol": "BBB", "date": "2024-07-01", "open": 11.6, "high": 11.6, "low": 11.6, "close": 11.6, "adjusted_close": 11.6, "volume": 1000},
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
                    "net_income": 300,
                    "equity": 1000,
                    "operating_profit": 150,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 300,
                    "operating_profit_ttm": 150,
                    "previous_net_income_ttm": 100,
                    "net_income_growth": 2,
                    "source_statement_id": "s1",
                    "source_url": "kap",
                    "raw_hash": "hash1",
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q1",
                    "fiscal_quarter": 1,
                    "announcement_datetime": "2024-04-30 18:00",
                    "announcement_date": "2024-04-30",
                    "net_income": 150,
                    "equity": 1000,
                    "operating_profit": 100,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 150,
                    "operating_profit_ttm": 100,
                    "previous_net_income_ttm": 100,
                    "net_income_growth": 0.5,
                    "source_statement_id": "s2",
                    "source_url": "kap",
                    "raw_hash": "hash2",
                },
            ]
        )
        membership = pd.DataFrame(
            [
                {"symbol": "AAA", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2020-01-01").date(), "end_date": pd.NaT},
                {"symbol": "BBB", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2020-01-01").date(), "end_date": pd.NaT},
            ]
        )

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert result["monthly_results"]["selected_symbols"].tolist() == ["AAA", "BBB"]

    def test_runMonthlyRotationBacktest_retainedPosition_waivesRolloverCommission(self):
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
                    "execution_mode": "rebalance_open_to_open",
                    "weighting": "equal_weight",
                    "if_less_than_top_n": "use_available",
                },
                "scoring": {"formula": "x1_plus_x2", "use_ttm": True, "firm_value_mode": "market_cap"},
                "costs": {"commission_rate": 0.002},
                "filters": {
                    "require_positive_equity": True,
                    "require_positive_net_income_ttm": True,
                    "require_positive_previous_net_income_ttm": True,
                    "require_positive_operating_profit_ttm": True,
                    "require_positive_firm_value": True,
                    "require_shares_outstanding": True,
                    "min_avg_turnover_20d": 1,
                },
                "backtest": {"start_date": "2024-05-01", "end_date": "2024-07-31", "initial_capital": 100000},
            }
        )
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-04-29", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-31", "open": 110, "high": 110, "low": 110, "close": 110, "adjusted_close": 110, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-03", "open": 120, "high": 120, "low": 120, "close": 120, "adjusted_close": 120, "volume": 1000},
                {"symbol": "AAA", "date": "2024-06-28", "open": 125, "high": 125, "low": 125, "close": 125, "adjusted_close": 125, "volume": 1000},
                {"symbol": "AAA", "date": "2024-07-01", "open": 126, "high": 126, "low": 126, "close": 126, "adjusted_close": 126, "volume": 1000},
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

        result = run_monthly_rotation_backtest(config, prices, financials, membership)
        may_position = result["selected_positions"][result["selected_positions"]["month"] == "2024-05"].iloc[0]
        jun_position = result["selected_positions"][result["selected_positions"]["month"] == "2024-06"].iloc[0]

        assert may_position["buy_commission_rate"] == pytest.approx(0.002)
        assert may_position["sell_commission_rate"] == pytest.approx(0.0)
        assert jun_position["buy_commission_rate"] == pytest.approx(0.0)
        assert jun_position["sell_commission_rate"] == pytest.approx(0.002)

    def test_runMonthlyRotationBacktest_regimeFilter_reducesTopNWhenBreadthWeak(self):
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
                    "top_n": 2,
                    "regime_filter_mode": "breadth_sma",
                    "regime_filter_top_n": 1,
                    "regime_filter_lookback_days": 3,
                    "regime_filter_breadth_threshold": 0.5,
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
                {"symbol": "AAA", "date": "2024-04-26", "open": 11, "high": 11, "low": 11, "close": 11, "adjusted_close": 11, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-29", "open": 10, "high": 10, "low": 10, "close": 10, "adjusted_close": 10, "volume": 1000},
                {"symbol": "AAA", "date": "2024-04-30", "open": 8, "high": 8, "low": 8, "close": 8, "adjusted_close": 8, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-02", "open": 9, "high": 9, "low": 9, "close": 9, "adjusted_close": 9, "volume": 1000},
                {"symbol": "AAA", "date": "2024-05-31", "open": 9, "high": 9, "low": 9, "close": 9, "adjusted_close": 9, "volume": 1000},
                {"symbol": "BBB", "date": "2024-04-26", "open": 21, "high": 21, "low": 21, "close": 21, "adjusted_close": 21, "volume": 1000},
                {"symbol": "BBB", "date": "2024-04-29", "open": 20, "high": 20, "low": 20, "close": 20, "adjusted_close": 20, "volume": 1000},
                {"symbol": "BBB", "date": "2024-04-30", "open": 18, "high": 18, "low": 18, "close": 18, "adjusted_close": 18, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-02", "open": 19, "high": 19, "low": 19, "close": 19, "adjusted_close": 19, "volume": 1000},
                {"symbol": "BBB", "date": "2024-05-31", "open": 19, "high": 19, "low": 19, "close": 19, "adjusted_close": 19, "volume": 1000},
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
                    "net_income": 300,
                    "equity": 1000,
                    "operating_profit": 100,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 300,
                    "operating_profit_ttm": 100,
                    "previous_net_income_ttm": 100,
                    "source_statement_id": "s1",
                    "source_url": "kap",
                    "raw_hash": "hash1",
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q1",
                    "fiscal_quarter": 1,
                    "announcement_datetime": "2024-04-30 18:00",
                    "announcement_date": "2024-04-30",
                    "net_income": 200,
                    "equity": 1000,
                    "operating_profit": 90,
                    "cash": 0,
                    "total_debt": 0,
                    "shares_outstanding": 100,
                    "shares_announcement_datetime": "2024-04-30 18:00",
                    "shares_source_url": "kap",
                    "net_income_ttm": 200,
                    "operating_profit_ttm": 90,
                    "previous_net_income_ttm": 100,
                    "source_statement_id": "s2",
                    "source_url": "kap",
                    "raw_hash": "hash2",
                },
            ]
        )
        membership = pd.DataFrame(
            [
                {"symbol": "AAA", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2020-01-01").date(), "end_date": pd.NaT},
                {"symbol": "BBB", "universe_name": "BIST_SANAYI", "start_date": pd.Timestamp("2020-01-01").date(), "end_date": pd.NaT},
            ]
        )

        result = run_monthly_rotation_backtest(config, prices, financials, membership)

        assert len(result["selected_positions"]) == 1
        assert result["monthly_results"]["selected_symbols"].iloc[0] in {"AAA", "BBB"}

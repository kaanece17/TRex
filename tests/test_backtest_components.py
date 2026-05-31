from datetime import date

import pandas as pd
import pytest

from bist_factor_backtest.backtest.execution import calculate_position_return_open_to_open
from bist_factor_backtest.backtest.monthly_rotation import (
    _apply_dynamic_repeater_weight_scaling_rule,
    _apply_marketbox_risk_on_filter_rule,
    _apply_position_quality_guard_rule,
    _apply_qqq_regime_weight_scaling_rule,
    _apply_technical_confirmation_rule,
    _apply_x1_soft_penalty_rule,
)
from bist_factor_backtest.backtest.portfolio import build_positions
from bist_factor_backtest.config import BacktestConfig
from bist_factor_backtest.data.calendar import get_first_trading_day, get_last_trading_day
from bist_factor_backtest.factors.liquidity import attach_recent_return_60d


class TestBuildPositions:
    def test_buildPositions_equalWeight_returnsEqualWeights(self):
        selected = pd.DataFrame([{"symbol": "AAA"}, {"symbol": "BBB"}])
        expected = [0.5, 0.5]

        result = build_positions(selected, weighting="equal_weight")

        assert result["weight"].tolist() == expected

    def test_buildPositions_emptySelection_returnsEmptyPositions(self):
        selected = pd.DataFrame(columns=["symbol"])

        result = build_positions(selected, weighting="equal_weight")

        assert result.empty

    def test_buildPositions_scoreWeightCapped_capsLargestWeight(self):
        selected = pd.DataFrame(
            [
                {"symbol": "AAA", "score": 10.0},
                {"symbol": "BBB", "score": 3.0},
                {"symbol": "CCC", "score": 2.0},
            ]
        )

        result = build_positions(selected, weighting="score_weight_capped", score_weight_cap=0.5)

        assert result["weight"].sum() == pytest.approx(1.0)
        assert result.loc[result["symbol"] == "AAA", "weight"].iloc[0] == pytest.approx(0.5)
        assert result.loc[result["symbol"] == "BBB", "weight"].iloc[0] == pytest.approx(0.3)
        assert result.loc[result["symbol"] == "CCC", "weight"].iloc[0] == pytest.approx(0.2)


class TestCalculatePositionReturnOpenToOpen:
    def test_calculatePositionReturnOpenToOpen_validPrices_returnsNetReturnAfterCommission(self):
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2024-05-02", "open": 100},
                {"symbol": "AAA", "date": "2024-05-31", "open": 115},
            ]
        )
        expected = 0.148

        result = calculate_position_return_open_to_open(prices, "AAA", date(2024, 5, 2), date(2024, 5, 31), 0.001, 0.001)

        assert result["gross_return"] == pytest.approx(0.15)
        assert result["net_return"] == pytest.approx(expected)

    def test_calculatePositionReturnOpenToOpen_missingSellPrice_returnsNone(self):
        prices = pd.DataFrame([{"symbol": "AAA", "date": "2024-05-02", "open": 100}])
        expected = None

        result = calculate_position_return_open_to_open(prices, "AAA", date(2024, 5, 2), date(2024, 5, 31), 0.001, 0.001)

        assert result is expected


class TestTradingDayCalendar:
    def test_getTradingDays_monthWithWeekendStart_returnsFirstAndLastAvailablePriceDates(self):
        prices = pd.DataFrame(
            [
                {"date": "2024-06-03"},
                {"date": "2024-06-28"},
                {"date": "2024-07-01"},
            ]
        )
        expected_first = date(2024, 6, 3)
        expected_last = date(2024, 6, 28)

        result_first = get_first_trading_day(prices, "2024-06")
        result_last = get_last_trading_day(prices, "2024-06")

        assert result_first == expected_first
        assert result_last == expected_last

    def test_getTradingDays_ignoresSparseZeroVolumeHolidayRows(self):
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2026-05-01", "volume": 0},
                {"symbol": "BBB", "date": "2026-05-01", "volume": 0},
                {"symbol": "CCC", "date": "2026-05-01", "volume": 0},
                {"symbol": "AAA", "date": "2026-05-04", "volume": 100},
                {"symbol": "BBB", "date": "2026-05-04", "volume": 120},
                {"symbol": "CCC", "date": "2026-05-04", "volume": 140},
                {"symbol": "DDD", "date": "2026-05-04", "volume": 160},
                {"symbol": "AAA", "date": "2026-05-29", "volume": 80},
                {"symbol": "BBB", "date": "2026-05-29", "volume": 90},
                {"symbol": "CCC", "date": "2026-05-29", "volume": 110},
                {"symbol": "DDD", "date": "2026-05-29", "volume": 130},
            ]
        )

        result_first = get_first_trading_day(prices, "2026-05")

        assert result_first == date(2026, 5, 4)


class TestRecentReturn60d:
    def test_attachRecentReturn60d_usesPrevious60TradingDays(self):
        prices = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                    "adjusted_close": float(100 + day),
                    "close": float(100 + day),
                    "volume": 1000,
                }
                for day in range(70)
            ]
        )
        candidates = pd.DataFrame([{"symbol": "AAA"}])

        result = attach_recent_return_60d(candidates, prices, date(2024, 3, 15))

        assert result["recent_return_60d"].iloc[0] == pytest.approx((169 / 109) - 1)


class TestQqqRegimeWeightScalingRule:
    def test_applyQqqRegimeWeightScalingRule_scalesWeightsWhenQqqBelow200d(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "America/New_York"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:", "price_symbol_suffix": None},
                "universe": {"name": "US_LARGE_CAP_TECH", "source": "csv", "symbols_file": "symbols.csv"},
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 2,
                    "qqq_regime_weight_scale_mode": "below_200dma_scale",
                    "qqq_regime_scale_factor": 0.75,
                    "qqq_regime_sma_lookback_days": 3,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )
        positions = pd.DataFrame([{"symbol": "AAA", "weight": 0.5}, {"symbol": "BBB", "weight": 0.5}])
        prices = pd.DataFrame(
            [
                {"symbol": "QQQ", "date": "2024-01-01", "adjusted_close": 100.0, "close": 100.0},
                {"symbol": "QQQ", "date": "2024-01-02", "adjusted_close": 100.0, "close": 100.0},
                {"symbol": "QQQ", "date": "2024-01-03", "adjusted_close": 100.0, "close": 100.0},
                {"symbol": "QQQ", "date": "2024-01-04", "adjusted_close": 90.0, "close": 90.0},
            ]
        )

        result = _apply_qqq_regime_weight_scaling_rule(positions, config, date(2024, 1, 5), prices)

        assert result["weight"].tolist() == pytest.approx([0.375, 0.375])

    def test_applyQqqRegimeWeightScalingRule_requiresNegative60dForDoubleRiskOff(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "America/New_York"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:", "price_symbol_suffix": None},
                "universe": {"name": "US_LARGE_CAP_TECH", "source": "csv", "symbols_file": "symbols.csv"},
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 2,
                    "qqq_regime_weight_scale_mode": "below_200dma_and_negative_60d_scale",
                    "qqq_regime_scale_factor": 0.75,
                    "qqq_regime_sma_lookback_days": 3,
                    "qqq_regime_return_lookback_days": 2,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )
        positions = pd.DataFrame([{"symbol": "AAA", "weight": 0.5}, {"symbol": "BBB", "weight": 0.5}])
        prices = pd.DataFrame(
            [
                {"symbol": "QQQ", "date": "2024-01-01", "adjusted_close": 100.0, "close": 100.0},
                {"symbol": "QQQ", "date": "2024-01-02", "adjusted_close": 100.0, "close": 100.0},
                {"symbol": "QQQ", "date": "2024-01-03", "adjusted_close": 100.0, "close": 100.0},
                {"symbol": "QQQ", "date": "2024-01-04", "adjusted_close": 90.0, "close": 90.0},
                {"symbol": "QQQ", "date": "2024-01-05", "adjusted_close": 95.0, "close": 95.0},
            ]
        )

        result = _apply_qqq_regime_weight_scaling_rule(positions, config, date(2024, 1, 6), prices)

        assert result["weight"].tolist() == pytest.approx([0.5, 0.5])


class TestTechnicalConfirmationRule:
    def test_applyTechnicalConfirmationRule_vetoesNegative60dHighScoreAndRedistributes(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "Europe/Istanbul"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {
                    "name": "BIST_SANAYI",
                    "source": "csv",
                    "symbols_file": "symbols.csv",
                },
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 3,
                    "technical_confirmation_mode": "high_score_negative_momentum_veto",
                    "technical_confirmation_rank_threshold": 2,
                    "technical_confirmation_lookback_days": 60,
                    "technical_confirmation_return_threshold": 0.0,
                    "technical_confirmation_redistribute": True,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )
        positions = pd.DataFrame(
            [
                {"symbol": "AAA", "score": 3.0, "weight": 1 / 3, "recent_return_60d": -0.10},
                {"symbol": "BBB", "score": 2.0, "weight": 1 / 3, "recent_return_60d": 0.05},
                {"symbol": "CCC", "score": 1.0, "weight": 1 / 3, "recent_return_60d": 0.02},
            ]
        )

        result = _apply_technical_confirmation_rule(positions, config)

        assert result["symbol"].tolist() == ["BBB", "CCC"]
        assert result["weight"].sum() == pytest.approx(1.0)
        assert result["weight"].tolist() == pytest.approx([0.5, 0.5])


class TestX1SoftPenaltyRule:
    def test_applyX1SoftPenaltyRule_penalizesX1HeavyWeak60dCandidate(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "Europe/Istanbul"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {
                    "name": "BIST_SANAYI",
                    "source": "csv",
                    "symbols_file": "symbols.csv",
                },
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 5,
                    "x1_soft_penalty_mode": "x1_heavy_low_60d_penalty",
                    "x1_soft_penalty_share_threshold": 0.80,
                    "x1_soft_penalty_return_60d_threshold": 0.20,
                    "x1_soft_penalty_amount": 0.10,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )
        candidates = pd.DataFrame(
            [
                {"symbol": "AAA", "x1": 0.90, "x2": 0.10, "recent_return_60d": 0.15, "selection_score": 1.00},
                {"symbol": "BBB", "x1": 0.70, "x2": 0.30, "recent_return_60d": 0.15, "selection_score": 1.00},
                {"symbol": "CCC", "x1": 0.90, "x2": 0.10, "recent_return_60d": 0.25, "selection_score": 1.00},
            ]
        )

        result = _apply_x1_soft_penalty_rule(candidates, config)

        assert result.loc[result["symbol"] == "AAA", "selection_score"].iloc[0] == pytest.approx(0.90)
        assert result.loc[result["symbol"] == "BBB", "selection_score"].iloc[0] == pytest.approx(1.00)
        assert result.loc[result["symbol"] == "CCC", "selection_score"].iloc[0] == pytest.approx(1.00)

    def test_applyTechnicalConfirmationRule_supports20DayLookback(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "Europe/Istanbul"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {
                    "name": "BIST_SANAYI",
                    "source": "csv",
                    "symbols_file": "symbols.csv",
                },
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 3,
                    "technical_confirmation_mode": "high_score_negative_momentum_veto",
                    "technical_confirmation_rank_threshold": 2,
                    "technical_confirmation_lookback_days": 20,
                    "technical_confirmation_return_threshold": 0.0,
                    "technical_confirmation_redistribute": True,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )
        positions = pd.DataFrame(
            [
                {"symbol": "AAA", "score": 3.0, "weight": 1 / 3, "recent_return_20d": -0.10},
                {"symbol": "BBB", "score": 2.0, "weight": 1 / 3, "recent_return_20d": 0.05},
                {"symbol": "CCC", "score": 1.0, "weight": 1 / 3, "recent_return_20d": 0.02},
            ]
        )

        result = _apply_technical_confirmation_rule(positions, config)

        assert result["symbol"].tolist() == ["BBB", "CCC"]
        assert result["weight"].sum() == pytest.approx(1.0)
        assert result["weight"].tolist() == pytest.approx([0.5, 0.5])


class TestDynamicRepeaterWeightScalingRule:
    def test_applyDynamicRepeaterWeightScalingRule_scalesWhenTwoFlaggedSymbolsPresent(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "America/New_York"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {"name": "US_INDUSTRIALS", "source": "csv", "symbols_file": "symbols.csv"},
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "dynamic_repeater_weight_scale_mode": "recent_negative_repeaters_scale",
                    "dynamic_repeater_lookback_months": 12,
                    "dynamic_repeater_min_negative_hits": 2,
                    "dynamic_repeater_weight_scale_factor": 0.75,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )
        positions = pd.DataFrame(
            [
                {"symbol": "AAA", "weight": 0.4},
                {"symbol": "BBB", "weight": 0.3},
                {"symbol": "CCC", "weight": 0.3},
            ]
        )
        history = {
            "AAA": [(pd.Period("2024-01", freq="M"), -0.10), (pd.Period("2024-03", freq="M"), -0.05)],
            "BBB": [(pd.Period("2024-02", freq="M"), -0.04), (pd.Period("2024-04", freq="M"), -0.02)],
            "CCC": [(pd.Period("2024-04", freq="M"), 0.03)],
        }

        result = _apply_dynamic_repeater_weight_scaling_rule(positions, config, "2024-05", history)

        assert result["weight"].sum() == pytest.approx(1.0)
        assert result.loc[result["symbol"] == "AAA", "weight"].iloc[0] < 0.4
        assert result.loc[result["symbol"] == "BBB", "weight"].iloc[0] < 0.3
        assert result.loc[result["symbol"] == "CCC", "weight"].iloc[0] > 0.3

    def test_applyDynamicRepeaterWeightScalingRule_ignoresSingleFlaggedSymbol(self):
        config = BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "America/New_York"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:"},
                "universe": {"name": "US_INDUSTRIALS", "source": "csv", "symbols_file": "symbols.csv"},
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "dynamic_repeater_weight_scale_mode": "recent_negative_repeaters_scale",
                    "dynamic_repeater_lookback_months": 12,
                    "dynamic_repeater_min_negative_hits": 2,
                    "dynamic_repeater_weight_scale_factor": 0.75,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )
        positions = pd.DataFrame(
            [
                {"symbol": "AAA", "weight": 0.4},
                {"symbol": "BBB", "weight": 0.3},
                {"symbol": "CCC", "weight": 0.3},
            ]
        )
        history = {
            "AAA": [(pd.Period("2024-01", freq="M"), -0.10), (pd.Period("2024-03", freq="M"), -0.05)],
            "BBB": [(pd.Period("2024-02", freq="M"), 0.04), (pd.Period("2024-04", freq="M"), -0.02)],
        }

        result = _apply_dynamic_repeater_weight_scaling_rule(positions, config, "2024-05", history)

        assert result["weight"].tolist() == pytest.approx([0.4, 0.3, 0.3])


class TestPositionQualityGuardRule:
    def _config(self, *, redistribute: bool = False, return_60d_threshold: float = 0.0) -> BacktestConfig:
        return BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "America/New_York"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:", "price_symbol_suffix": None},
                "universe": {"name": "US_LARGE_CAP_TECH", "source": "csv", "symbols_file": "symbols.csv"},
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 3,
                    "position_quality_guard_mode": "symbol_group_negative_60d_cash_veto",
                    "position_quality_guard_symbols": ["AMD", "NVDA"],
                    "position_quality_guard_return_60d_threshold": return_60d_threshold,
                    "position_quality_guard_redistribute": redistribute,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )

    def test_applyPositionQualityGuardRule_vetoesNegative60dGuardSymbolAndLeavesCash(self):
        positions = pd.DataFrame(
            [
                {"symbol": "AMD", "weight": 0.4, "recent_return_60d": -0.01},
                {"symbol": "MSFT", "weight": 0.3, "recent_return_60d": -0.20},
                {"symbol": "NVDA", "weight": 0.3, "recent_return_60d": 0.05},
            ]
        )

        result = _apply_position_quality_guard_rule(positions, self._config())

        assert result["symbol"].tolist() == ["MSFT", "NVDA"]
        assert result["weight"].sum() == pytest.approx(0.6)

    def test_applyPositionQualityGuardRule_canRedistributeSurvivorWeights(self):
        positions = pd.DataFrame(
            [
                {"symbol": "AMD", "weight": 0.4, "recent_return_60d": -0.01},
                {"symbol": "MSFT", "weight": 0.3, "recent_return_60d": -0.20},
                {"symbol": "NVDA", "weight": 0.3, "recent_return_60d": 0.05},
            ]
        )

        result = _apply_position_quality_guard_rule(positions, self._config(redistribute=True))

        assert result["symbol"].tolist() == ["MSFT", "NVDA"]
        assert result["weight"].sum() == pytest.approx(1.0)
        assert result["weight"].tolist() == pytest.approx([0.5, 0.5])

    def test_applyPositionQualityGuardRule_respectsConfiguredNegativeThreshold(self):
        positions = pd.DataFrame(
            [
                {"symbol": "AMD", "weight": 0.4, "recent_return_60d": -0.05},
                {"symbol": "NVDA", "weight": 0.3, "recent_return_60d": -0.11},
                {"symbol": "MSFT", "weight": 0.3, "recent_return_60d": -0.30},
            ]
        )

        result = _apply_position_quality_guard_rule(
            positions,
            self._config(return_60d_threshold=-0.10),
        )

        assert result["symbol"].tolist() == ["AMD", "MSFT"]
        assert result["weight"].sum() == pytest.approx(0.7)


class TestMarketboxRiskOnFilterRule:
    def _config(self, min_score: float = 0.50) -> BacktestConfig:
        return BacktestConfig.model_validate(
            {
                "project": {"name": "test", "timezone": "America/New_York"},
                "data": {"storage": "duckdb", "duckdb_path": ":memory:", "price_symbol_suffix": None},
                "universe": {"name": "US_LARGE_CAP_TECH", "source": "csv", "symbols_file": "symbols.csv"},
                "point_in_time": {"cutoff_mode": "market_open", "if_only_date_available": "previous_day_only"},
                "strategy": {
                    "top_n": 2,
                    "marketbox_risk_on_filter_mode": "xlk_risk_on_score",
                    "marketbox_risk_on_symbol": "XLK",
                    "marketbox_risk_on_min_score": min_score,
                    "marketbox_risk_on_stage_confidence": 1.0,
                },
                "scoring": {},
                "costs": {},
                "filters": {},
                "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31", "initial_capital": 100000},
            }
        )

    def _prices(self, *, xlk_growth: float, same_day_spike: bool = False) -> pd.DataFrame:
        rows = []
        dates = pd.bdate_range("2023-01-02", periods=230)
        for i, dt in enumerate(dates):
            day = dt.date().isoformat()
            xlk_close = 100.0 * ((1.0 + xlk_growth) ** i)
            if same_day_spike and day == "2023-11-20":
                xlk_close = 250.0
            for symbol, close in [
                ("XLK", xlk_close),
                ("SPY", 100.0),
                ("BTC-USD", 100.0),
                ("GC=F", 100.0),
            ]:
                rows.append(
                    {
                        "symbol": symbol,
                        "date": day,
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "adjusted_close": close,
                        "volume": 1000.0,
                    }
                )
        return pd.DataFrame(rows)

    def test_applyMarketboxRiskOnFilterRule_keepsPositionsWhenPriorXlkScoreIsRiskOn(self):
        positions = pd.DataFrame([{"symbol": "AAPL", "weight": 1.0}])
        prices = self._prices(xlk_growth=0.002)

        result = _apply_marketbox_risk_on_filter_rule(
            positions,
            self._config(min_score=0.50),
            date(2023, 11, 20),
            prices,
        )

        assert not result.empty

    def test_applyMarketboxRiskOnFilterRule_usesOnlyPitDataBeforeBuyDate(self):
        positions = pd.DataFrame([{"symbol": "AAPL", "weight": 1.0}])
        prices = self._prices(xlk_growth=0.0, same_day_spike=True)

        result = _apply_marketbox_risk_on_filter_rule(
            positions,
            self._config(min_score=0.70),
            date(2023, 11, 20),
            prices,
        )

        assert result.empty

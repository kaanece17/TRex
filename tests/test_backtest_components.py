from datetime import date

import pandas as pd
import pytest

from bist_factor_backtest.backtest.execution import calculate_position_return_open_to_open
from bist_factor_backtest.backtest.portfolio import build_positions
from bist_factor_backtest.data.calendar import get_first_trading_day, get_last_trading_day


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

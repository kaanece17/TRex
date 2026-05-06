import pandas as pd
import pytest

from bist_factor_backtest.factors.filters import FilterSettings, apply_filters
from bist_factor_backtest.factors.firm_value import calculate_market_cap_firm_value
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value
from bist_factor_backtest.factors.liquidity import attach_avg_turnover_20d
from bist_factor_backtest.factors.scoring import calculate_scores


class TestCalculateMarketCapFirmValue:
    def test_calculateMarketCapFirmValue_validInputs_returnsEnterpriseValue(self):
        data = pd.DataFrame([{"firm_value_price": 10, "shares_outstanding": 1000, "total_debt": 300, "cash": 100}])
        expected = 10200

        result = calculate_market_cap_firm_value(data)

        assert result["firm_value"].iloc[0] == expected

    def test_attachMarketCapFirmValue_rebalanceDate_usesPreviousClose(self):
        candidates = pd.DataFrame([{"symbol": "AAA", "shares_outstanding": 10, "total_debt": 15, "cash": 5}])
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2020-01-01", "close": 11},
                {"symbol": "AAA", "date": "2020-01-02", "close": 99},
            ]
        )
        expected = 120

        result = attach_market_cap_firm_value(candidates, prices, pd.Timestamp("2020-01-02 10:00"))

        assert result["firm_value"].iloc[0] == expected
        assert result["firm_value_price_date"].iloc[0] == pd.Timestamp("2020-01-01").date()


class TestCalculateScores:
    def test_calculateScores_validInputs_returnsExpectedScore(self):
        data = pd.DataFrame(
            [
                {
                    "net_income_ttm": 200,
                    "previous_net_income_ttm": 100,
                    "equity": 1000,
                    "operating_profit_ttm": 150,
                    "firm_value": 1300,
                }
            ]
        )
        expected = 0.5153846153846153

        result = calculate_scores(data)

        assert result["net_income_growth"].iloc[0] == 1
        assert result["score"].iloc[0] == pytest.approx(expected)

    def test_calculateScores_growthAboveOne_assumesPercentAndNormalizes(self):
        data = pd.DataFrame(
            [
                {
                    "net_income_ttm": 1100,
                    "previous_net_income_ttm": 100,
                    "equity": 1000,
                    "operating_profit_ttm": 150,
                    "firm_value": 1300,
                }
            ]
        )
        expected_growth = 0.1
        expected_x1 = 1.1 * (1 + expected_growth)

        result = calculate_scores(data)

        assert result["net_income_growth"].iloc[0] == pytest.approx(expected_growth)
        assert result["x1"].iloc[0] == pytest.approx(expected_x1)

    def test_calculateScores_growthBelowFloor_clipsToConfiguredMinimum(self):
        data = pd.DataFrame(
            [
                {
                    "net_income_ttm": -100,
                    "previous_net_income_ttm": 100,
                    "equity": 1000,
                    "operating_profit_ttm": 150,
                    "firm_value": 1300,
                }
            ]
        )
        expected_growth = -0.95

        result = calculate_scores(data)

        assert result["net_income_growth"].iloc[0] == pytest.approx(expected_growth)


class TestApplyFilters:
    def test_applyFilters_invalidRows_returnsFilteredAndRejectedReasons(self):
        data = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 1,
                    "net_income_ttm": 1,
                    "previous_net_income_ttm": 1,
                    "operating_profit_ttm": 1,
                    "firm_value": 1,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": -1,
                    "net_income_ttm": 1,
                    "previous_net_income_ttm": 1,
                    "operating_profit_ttm": 1,
                    "firm_value": 1,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                },
                {
                    "symbol": "CCC",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 1,
                    "net_income_ttm": 1,
                    "previous_net_income_ttm": 1,
                    "operating_profit_ttm": 1,
                    "firm_value": 1,
                    "shares_outstanding": None,
                    "avg_turnover_20d": 2_000_000,
                },
                {
                    "symbol": "DDD",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 1,
                    "net_income_ttm": 1,
                    "previous_net_income_ttm": 1,
                    "operating_profit_ttm": 1,
                    "firm_value": None,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                },
            ]
        )
        expected = ["AAA"]

        result, rejected = apply_filters(data, FilterSettings())

        assert result["symbol"].tolist() == expected
        assert rejected["reason"].tolist() == ["missing_financial_data", "negative_equity", "negative_firm_value"]

    def test_applyFilters_missingFinancialSnapshotFields_excludesRow(self):
        data = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": None,
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 1,
                    "net_income_ttm": 1,
                    "previous_net_income_ttm": 1,
                    "operating_profit_ttm": 1,
                    "firm_value": 1,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                }
            ]
        )
        expected = []

        result, rejected = apply_filters(data, FilterSettings())

        assert result["symbol"].tolist() == expected
        assert rejected["reason"].tolist() == ["missing_financial_data"]

    def test_applyFilters_missingFinancialSnapshotColumns_excludesRow(self):
        data = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "equity": 1,
                    "net_income_ttm": 1,
                    "previous_net_income_ttm": 1,
                    "operating_profit_ttm": 1,
                    "firm_value": 1,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                }
            ]
        )
        expected = []

        result, rejected = apply_filters(data, FilterSettings())

        assert result["symbol"].tolist() == expected
        assert rejected["reason"].tolist() == ["missing_financial_data"]


class TestAttachAvgTurnover20d:
    def test_attachAvgTurnover20d_stringDates_convertsAndCalculatesMean(self):
        candidates = pd.DataFrame([{"symbol": "AAA"}])
        prices = pd.DataFrame(
            [
                {"symbol": "AAA", "date": "2020-01-01", "close": 10, "volume": 5},
                {"symbol": "AAA", "date": "2020-01-02", "close": 20, "volume": 5},
                {"symbol": "AAA", "date": "2020-01-03", "close": 30, "volume": 5},
            ]
        )
        expected = (50 + 100) / 2

        result = attach_avg_turnover_20d(candidates, prices, pd.Timestamp("2020-01-03").date())

        assert result["avg_turnover_20d"].iloc[0] == expected

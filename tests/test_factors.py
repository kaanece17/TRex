import pandas as pd
import pytest

from bist_factor_backtest.config import ScoringConfig
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

    def test_calculateScores_rawGrowthMode_doesNotNormalizeOrClip(self):
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

        result = calculate_scores(data, ScoringConfig(growth_mode="raw"))

        assert result["net_income_growth"].iloc[0] == pytest.approx(10.0)
        assert result["x1"].iloc[0] == pytest.approx(12.1)

    def test_calculateScores_noteBestFit_usesLatestCumulativeGrowthWithAnnualBase(self):
        data = pd.DataFrame(
            [
                {
                    "net_income": 200,
                    "latest_cum_net_income": 150,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 120,
                    "firm_value": 1500,
                }
            ]
        )

        result = calculate_scores(data, ScoringConfig(formula="note_best_fit", use_ttm=False))

        assert result["net_income_growth"].iloc[0] == pytest.approx(0.5)
        assert result["x1"].iloc[0] == pytest.approx(0.3)
        assert result["x2"].iloc[0] == pytest.approx(0.08)
        assert result["score"].iloc[0] == pytest.approx(0.38)

    def test_calculateScores_noteBestFit_capsX1AndX2AtConfiguredQuantiles(self):
        data = pd.DataFrame(
            [
                {
                    "net_income": 100,
                    "latest_cum_net_income": 120,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 50,
                    "firm_value": 1000,
                },
                {
                    "net_income": 1000,
                    "latest_cum_net_income": 1000,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 500,
                    "firm_value": 1000,
                },
            ]
        )
        expected_x1_cap = pd.Series([0.12, 10.0]).quantile(0.5)
        expected_x2_cap = pd.Series([0.05, 0.5]).quantile(0.5)

        result = calculate_scores(
            data,
            ScoringConfig(
                formula="note_best_fit",
                use_ttm=False,
                x1_cap_quantile=0.5,
                x2_cap_quantile=0.5,
            ),
        )

        assert result["x1"].tolist() == pytest.approx([0.12, expected_x1_cap])
        assert result["x2"].tolist() == pytest.approx([0.05, expected_x2_cap])
        assert result["score"].tolist() == pytest.approx([0.17, expected_x1_cap + expected_x2_cap])

    def test_calculateScores_noteBestFit_appliesX1X2WeightsToScore(self):
        data = pd.DataFrame(
            [
                {
                    "net_income": 200,
                    "latest_cum_net_income": 150,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 120,
                    "firm_value": 1500,
                }
            ]
        )

        result = calculate_scores(
            data,
            ScoringConfig(formula="note_best_fit", use_ttm=False, x1_weight=0.9, x2_weight=1.0),
        )

        assert result["x1"].iloc[0] == pytest.approx(0.3)
        assert result["x2"].iloc[0] == pytest.approx(0.08)
        assert result["score"].iloc[0] == pytest.approx(0.35)
        assert result["x1_share"].iloc[0] == pytest.approx(0.3 / 0.38)
        assert result["x2_share"].iloc[0] == pytest.approx(0.08 / 0.38)

    def test_calculateScores_selectionScore_addsSmallMomentumRankBonus(self):
        data = pd.DataFrame(
            [
                {
                    "net_income": 200,
                    "latest_cum_net_income": 150,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 120,
                    "firm_value": 1500,
                    "recent_return_20d": -0.10,
                },
                {
                    "net_income": 200,
                    "latest_cum_net_income": 150,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 120,
                    "firm_value": 1500,
                    "recent_return_20d": 0.20,
                },
            ]
        )

        result = calculate_scores(
            data,
            ScoringConfig(
                formula="note_best_fit",
                use_ttm=False,
                momentum_rank_weight=0.2,
            ),
        )

        assert result["score"].tolist() == pytest.approx([0.38, 0.38])
        assert result["selection_score"].iloc[1] > result["selection_score"].iloc[0]

    def test_calculateScores_selectionScore_appliesCheapValueTrapPenalty(self):
        data = pd.DataFrame(
            [
                {
                    "net_income": 200,
                    "latest_cum_net_income": 150,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 30,
                    "firm_value": 300,
                },
                {
                    "net_income": 200,
                    "latest_cum_net_income": 150,
                    "previous_same_quarter_cum_net_income": 100,
                    "equity": 1000,
                    "operating_profit": 120,
                    "firm_value": 1500,
                },
            ]
        )

        result = calculate_scores(
            data,
            ScoringConfig(
                formula="note_best_fit",
                use_ttm=False,
                cheap_value_trap_penalty=0.1,
                cheap_value_trap_fv_to_equity_threshold=0.5,
                x1_dominant_value_penalty_share_threshold=0.75,
            ),
        )

        assert result["score"].tolist() == pytest.approx([0.4, 0.38])
        assert result["x1_share"].iloc[0] > 0.75
        assert result["selection_score"].tolist() == pytest.approx([0.3, 0.38])


class TestApplyFilters:
    def test_applyFilters_x1DominantLowGrowth_rejectsOnlyMatchingRows(self):
        data = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                    "x1_share": 0.90,
                    "net_income_growth": 0.05,
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                    "x1_share": 0.90,
                    "net_income_growth": 0.20,
                },
                {
                    "symbol": "CCC",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                    "x1_share": 0.70,
                    "net_income_growth": 0.01,
                },
            ]
        )

        filtered, rejected = apply_filters(
            data,
            FilterSettings(
                require_positive_equity=False,
                require_positive_net_income_ttm=False,
                require_positive_previous_net_income_ttm=False,
                require_positive_operating_profit_ttm=False,
                require_positive_firm_value=False,
                require_shares_outstanding=False,
                min_avg_turnover_20d=0,
                min_growth_when_x1_dominant_share=0.10,
                x1_dominant_growth_share_threshold=0.85,
            ),
        )

        assert filtered["symbol"].tolist() == ["BBB", "CCC"]
        assert rejected["symbol"].tolist() == ["AAA"]
        assert rejected["reason"].tolist() == ["x1_dominant_low_growth"]

    def test_applyFilters_minRecentReturn20d_rejectsNegativeMomentumRows(self):
        data = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                    "recent_return_20d": -0.01,
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                    "recent_return_20d": 0.02,
                },
            ]
        )

        filtered, rejected = apply_filters(data, FilterSettings(min_recent_return_20d=0.0, min_avg_turnover_20d=0))

        assert filtered["symbol"].tolist() == ["BBB"]
        assert rejected["symbol"].tolist() == ["AAA"]
        assert rejected["reason"].tolist() == ["negative_recent_momentum"]

    def test_applyFilters_maxNetIncomeToEquity_rejectsExtremeRows(self):
        data = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income": 80,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income": 150,
                    "net_income_ttm": 150,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                },
            ]
        )

        filtered, rejected = apply_filters(
            data,
            FilterSettings(
                require_positive_equity=True,
                require_positive_net_income_ttm=False,
                require_positive_previous_net_income_ttm=False,
                require_positive_operating_profit_ttm=False,
                require_positive_firm_value=False,
                require_shares_outstanding=True,
                max_net_income_to_equity=1.0,
                min_avg_turnover_20d=1,
            ),
        )

        assert filtered["symbol"].tolist() == ["AAA"]
        assert rejected["symbol"].tolist() == ["BBB"]
        assert rejected["reason"].tolist() == ["excessive_net_income_to_equity"]

    def test_applyFilters_x1DominantNegativeMomentum_rejectsMatchingRows(self):
        data = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income": 80,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                    "x1_share": 0.91,
                    "recent_return_20d": -0.01,
                },
                {
                    "symbol": "BBB",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-01T10:00:00",
                    "equity": 100,
                    "net_income": 80,
                    "net_income_ttm": 80,
                    "previous_net_income_ttm": 10,
                    "operating_profit_ttm": 20,
                    "firm_value": 200,
                    "shares_outstanding": 1,
                    "avg_turnover_20d": 2_000_000,
                    "x1_share": 0.91,
                    "recent_return_20d": 0.02,
                },
            ]
        )

        filtered, rejected = apply_filters(
            data,
            FilterSettings(
                require_positive_equity=True,
                require_positive_net_income_ttm=False,
                require_positive_previous_net_income_ttm=False,
                require_positive_operating_profit_ttm=False,
                require_positive_firm_value=False,
                require_shares_outstanding=True,
                x1_dominant_share_threshold=0.90,
                recent_return_20d_threshold=0.0,
                min_avg_turnover_20d=1,
            ),
        )

        assert filtered["symbol"].tolist() == ["BBB"]
        assert rejected["symbol"].tolist() == ["AAA"]
        assert rejected["reason"].tolist() == ["x1_dominant_negative_momentum"]

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

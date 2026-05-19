import pandas as pd
import pytest

from bist_factor_backtest.factors.ttm import add_earnings_momentum_features, add_quarterly_values, add_ttm_values


class TestAddQuarterlyValues:
    def test_addQuarterlyValues_cumulativeIncomeStatements_returnsQuarterlyValues(self):
        financials = pd.DataFrame(
            [
                {"symbol": "ABC", "period_end": "2024-03-31", "fiscal_year": 2024, "fiscal_quarter": 1, "net_income": 100, "operating_profit": 120},
                {"symbol": "ABC", "period_end": "2024-06-30", "fiscal_year": 2024, "fiscal_quarter": 2, "net_income": 250, "operating_profit": 260},
                {"symbol": "ABC", "period_end": "2024-09-30", "fiscal_year": 2024, "fiscal_quarter": 3, "net_income": 400, "operating_profit": 430},
                {"symbol": "ABC", "period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_quarter": 4, "net_income": 700, "operating_profit": 760},
            ]
        )
        expected = [100, 150, 150, 300]

        result = add_quarterly_values(financials)

        assert result["quarterly_net_income"].tolist() == expected


class TestAddTtmValues:
    def test_addTtmValues_sameQuarterPreviousYear_returnsComparablePreviousTtm(self):
        rows = []
        for year, values in [(2023, [10, 30, 60, 100]), (2024, [20, 50, 90, 140])]:
            for quarter, net_income in enumerate(values, start=1):
                rows.append(
                    {
                        "symbol": "ABC",
                        "period_end": f"{year}-{quarter * 3:02d}-28",
                        "fiscal_year": year,
                        "fiscal_quarter": quarter,
                        "net_income": net_income,
                        "operating_profit": net_income,
                    }
                )
        financials = pd.DataFrame(rows)
        expected = 100

        result = add_ttm_values(financials)
        current = result[(result["fiscal_year"] == 2024) & (result["fiscal_quarter"] == 4)].iloc[0]

        assert current["previous_net_income_ttm"] == expected

    def test_addTtmValues_existingDerivedColumns_recomputesWithoutMergeConflict(self):
        financials = pd.DataFrame(
            [
                {
                    "symbol": "ABC",
                    "period_end": "2023-03-31",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 1,
                    "net_income": 10,
                    "operating_profit": 10,
                    "previous_net_income_ttm": 999,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-06-30",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 2,
                    "net_income": 30,
                    "operating_profit": 30,
                    "previous_net_income_ttm": 999,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-09-30",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 3,
                    "net_income": 60,
                    "operating_profit": 60,
                    "previous_net_income_ttm": 999,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-12-31",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 4,
                    "net_income": 100,
                    "operating_profit": 100,
                    "previous_net_income_ttm": 999,
                },
            ]
        )
        expected = 100

        result = add_ttm_values(financials)

        assert result["net_income_ttm"].iloc[-1] == expected

    def test_addTtmValues_q4FallsBackToAnnualCumulativeWhenEarlierQuarterMissing(self):
        financials = pd.DataFrame(
            [
                {
                    "symbol": "ABC",
                    "period_end": "2022-06-30",
                    "fiscal_year": 2022,
                    "fiscal_quarter": 2,
                    "net_income": 20,
                    "operating_profit": 30,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2022-09-30",
                    "fiscal_year": 2022,
                    "fiscal_quarter": 3,
                    "net_income": 40,
                    "operating_profit": 60,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2022-12-31",
                    "fiscal_year": 2022,
                    "fiscal_quarter": 4,
                    "net_income": 100,
                    "operating_profit": 150,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-03-31",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 1,
                    "net_income": 30,
                    "operating_profit": 40,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-06-30",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 2,
                    "net_income": 70,
                    "operating_profit": 90,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-09-30",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 3,
                    "net_income": 120,
                    "operating_profit": 130,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-12-31",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 4,
                    "net_income": 200,
                    "operating_profit": 260,
                },
            ]
        )

        result = add_ttm_values(financials)
        q4_2022 = result[(result["fiscal_year"] == 2022) & (result["fiscal_quarter"] == 4)].iloc[0]
        q4_2023 = result[(result["fiscal_year"] == 2023) & (result["fiscal_quarter"] == 4)].iloc[0]

        assert q4_2022["net_income_ttm"] == 100
        assert q4_2023["previous_net_income_ttm"] == 100

    def test_addTtmValues_q2FallsBackToAnnualPlusCurrentMinusPreviousYearSameQuarter(self):
        financials = pd.DataFrame(
            [
                {
                    "symbol": "ABC",
                    "period_end": "2021-06-30",
                    "fiscal_year": 2021,
                    "fiscal_quarter": 2,
                    "net_income": 40,
                    "operating_profit": 50,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2021-12-31",
                    "fiscal_year": 2021,
                    "fiscal_quarter": 4,
                    "net_income": 100,
                    "operating_profit": 120,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2022-06-30",
                    "fiscal_year": 2022,
                    "fiscal_quarter": 2,
                    "net_income": 70,
                    "operating_profit": 80,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2022-12-31",
                    "fiscal_year": 2022,
                    "fiscal_quarter": 4,
                    "net_income": 160,
                    "operating_profit": 190,
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-06-30",
                    "fiscal_year": 2023,
                    "fiscal_quarter": 2,
                    "net_income": 90,
                    "operating_profit": 110,
                },
            ]
        )

        result = add_ttm_values(financials)
        q2_2022 = result[(result["fiscal_year"] == 2022) & (result["fiscal_quarter"] == 2)].iloc[0]
        q2_2023 = result[(result["fiscal_year"] == 2023) & (result["fiscal_quarter"] == 2)].iloc[0]

        assert q2_2022["net_income_ttm"] == 130
        assert q2_2022["operating_profit_ttm"] == 150
        assert q2_2023["previous_net_income_ttm"] == 130


class TestAddEarningsMomentumFeatures:
    def test_addEarningsMomentumFeatures_priorYearComparables_returnExpectedSignals(self):
        rows = []
        for year, values in [(2023, [10, 30, 60, 100]), (2024, [20, 50, 90, 140])]:
            for quarter, net_income in enumerate(values, start=1):
                rows.append(
                    {
                        "symbol": "ABC",
                        "period_end": f"{year}-{quarter * 3:02d}-28",
                        "fiscal_year": year,
                        "fiscal_quarter": quarter,
                        "net_income": net_income,
                        "operating_profit": net_income * 2,
                    }
                )
        financials = pd.DataFrame(rows)

        result = add_earnings_momentum_features(add_ttm_values(financials))
        current = result[(result["fiscal_year"] == 2024) & (result["fiscal_quarter"] == 4)].iloc[0]

        assert current["ni_ttm_growth_yoy"] == pytest.approx(0.4)
        assert current["op_ttm_growth_yoy"] == pytest.approx(0.4)
        assert pd.isna(current["earnings_acceleration"])
        assert current["profitability_quality_combo"] > 1.0

    def test_addEarningsMomentumFeatures_missingPriorYearComparable_keepsNa(self):
        financials = pd.DataFrame(
            [
                {"symbol": "ABC", "period_end": "2024-03-31", "fiscal_year": 2024, "fiscal_quarter": 1, "net_income": 10, "operating_profit": 20},
                {"symbol": "ABC", "period_end": "2024-06-30", "fiscal_year": 2024, "fiscal_quarter": 2, "net_income": 25, "operating_profit": 40},
                {"symbol": "ABC", "period_end": "2024-09-30", "fiscal_year": 2024, "fiscal_quarter": 3, "net_income": 45, "operating_profit": 70},
                {"symbol": "ABC", "period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_quarter": 4, "net_income": 80, "operating_profit": 120},
            ]
        )

        result = add_earnings_momentum_features(add_ttm_values(financials))
        current = result[result["fiscal_quarter"] == 4].iloc[0]

        assert pd.isna(current["ni_ttm_growth_yoy"])
        assert pd.isna(current["op_ttm_growth_yoy"])

import pandas as pd

from bist_factor_backtest.factors.ttm import add_quarterly_values, add_ttm_values


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

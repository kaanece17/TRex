from datetime import date, datetime

import pandas as pd

from bist_factor_backtest.data.point_in_time import get_latest_known_annual_financials_with_stale_replacement


class TestPointInTimeAnnualReplacement:
    def test_replacesStaleAnnualBase_withLatestKnownQuarter(self):
        financials = pd.DataFrame(
            [
                {
                    "symbol": "CCOLA",
                    "period_end": "2023-12-01",
                    "fiscal_year": 2023,
                    "fiscal_period": "Q4",
                    "fiscal_quarter": 4,
                    "announcement_datetime": pd.NaT,
                    "announcement_date": date(2024, 3, 13),
                    "net_income": 100.0,
                    "equity": 1000.0,
                    "operating_profit": 50.0,
                    "cash": 10.0,
                    "total_debt": 20.0,
                    "shares_outstanding": 1.0,
                    "shares_announcement_datetime": pd.NaT,
                    "shares_source_url": "annual-shares",
                    "net_income_ttm": 100.0,
                    "operating_profit_ttm": 50.0,
                    "previous_net_income_ttm": 80.0,
                    "net_income_growth": 0.25,
                    "source_statement_id": "annual-2023q4",
                    "source_url": "annual-url",
                    "announcement_source_url": "annual-ann",
                    "raw_hash": "annual",
                },
                {
                    "symbol": "CCOLA",
                    "period_end": "2024-09-01",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q3",
                    "fiscal_quarter": 3,
                    "announcement_datetime": pd.NaT,
                    "announcement_date": date(2024, 11, 4),
                    "net_income": 140.0,
                    "equity": 1200.0,
                    "operating_profit": 70.0,
                    "cash": 15.0,
                    "total_debt": 25.0,
                    "shares_outstanding": 1.0,
                    "shares_announcement_datetime": pd.NaT,
                    "shares_source_url": "q3-shares",
                    "net_income_ttm": 180.0,
                    "operating_profit_ttm": 90.0,
                    "previous_net_income_ttm": 120.0,
                    "net_income_growth": 0.50,
                    "source_statement_id": "q3-2024",
                    "source_url": "q3-url",
                    "announcement_source_url": "q3-ann",
                    "raw_hash": "q3",
                },
            ]
        )

        result = get_latest_known_annual_financials_with_stale_replacement(
            financials,
            rebalance_datetime=datetime(2025, 1, 2, 10, 0, 0),
            first_trading_day=date(2025, 1, 2),
        )

        assert pd.Timestamp(result["period_end"].iloc[0]) == pd.Timestamp("2024-09-01")
        assert result["fiscal_quarter"].iloc[0] == 3
        assert bool(result["annual_base_replaced"].iloc[0]) is True
        assert pd.Timestamp(result["annual_base_original_period_end"].iloc[0]) == pd.Timestamp("2023-12-01")

    def test_keepsFreshAnnualBase_whenLagIsAcceptable(self):
        financials = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2024-12-01",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q4",
                    "fiscal_quarter": 4,
                    "announcement_datetime": pd.NaT,
                    "announcement_date": date(2025, 3, 4),
                    "net_income": 100.0,
                    "equity": 1000.0,
                    "operating_profit": 50.0,
                    "cash": 10.0,
                    "total_debt": 20.0,
                    "shares_outstanding": 1.0,
                    "shares_announcement_datetime": pd.NaT,
                    "shares_source_url": "annual-shares",
                    "net_income_ttm": 100.0,
                    "operating_profit_ttm": 50.0,
                    "previous_net_income_ttm": 80.0,
                    "net_income_growth": 0.25,
                    "source_statement_id": "annual-2024q4",
                    "source_url": "annual-url",
                    "announcement_source_url": "annual-ann",
                    "raw_hash": "annual",
                }
            ]
        )

        result = get_latest_known_annual_financials_with_stale_replacement(
            financials,
            rebalance_datetime=datetime(2025, 5, 2, 10, 0, 0),
            first_trading_day=date(2025, 5, 2),
        )

        assert pd.Timestamp(result["period_end"].iloc[0]) == pd.Timestamp("2024-12-01")
        assert bool(result["annual_base_replaced"].iloc[0]) is False

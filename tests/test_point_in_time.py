from datetime import date

import pandas as pd

from bist_factor_backtest.data.point_in_time import get_latest_known_financials


class TestGetLatestKnownFinancials:
    def test_getLatestKnownFinancials_futureAnnouncement_excludesFutureStatement(self):
        rebalance_datetime = pd.Timestamp("2024-05-01 10:00", tz="Europe/Istanbul")
        financials = pd.DataFrame(
            [
                {
                    "symbol": "ABC",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-08 18:00",
                    "announcement_date": "2024-05-08",
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-12-31",
                    "announcement_datetime": "2024-03-08 18:00",
                    "announcement_date": "2024-03-08",
                },
            ]
        )
        expected = pd.Timestamp("2023-12-31")

        result = get_latest_known_financials(financials, rebalance_datetime)

        assert pd.Timestamp(result["period_end"].iloc[0]) == expected

    def test_getLatestKnownFinancials_sameDayDateOnly_excludesSameDayStatement(self):
        rebalance_datetime = pd.Timestamp("2024-05-02 10:00", tz="Europe/Istanbul")
        first_trading_day = date(2024, 5, 2)
        financials = pd.DataFrame(
            [
                {
                    "symbol": "ABC",
                    "period_end": "2024-03-31",
                    "announcement_datetime": None,
                    "announcement_date": "2024-05-02",
                },
                {
                    "symbol": "ABC",
                    "period_end": "2023-12-31",
                    "announcement_datetime": None,
                    "announcement_date": "2024-04-30",
                },
            ]
        )
        expected = pd.Timestamp("2023-12-31")

        result = get_latest_known_financials(financials, rebalance_datetime, first_trading_day)

        assert pd.Timestamp(result["period_end"].iloc[0]) == expected

    def test_getLatestKnownFinancials_noKnownFinancials_returnsEmptyResult(self):
        rebalance_datetime = pd.Timestamp("2024-05-01 10:00", tz="Europe/Istanbul")
        financials = pd.DataFrame(
            [
                {
                    "symbol": "ABC",
                    "period_end": "2024-03-31",
                    "announcement_datetime": "2024-05-08 18:00",
                    "announcement_date": "2024-05-08",
                }
            ]
        )

        result = get_latest_known_financials(financials, rebalance_datetime)

        assert result.empty

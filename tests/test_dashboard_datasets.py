import pandas as pd

from bist_factor_backtest.dashboard.datasets import (
    build_current_month_alerts,
    build_missing_financials,
    build_stale_financial_base_alerts,
    build_symbol_confidence,
)


class TestDashboardDatasets:
    def test_buildSymbolConfidence_classifiesWinnerLoserAndNeutral(self):
        selected = pd.DataFrame(
            [
                {"symbol": "WIN", "net_return": 0.10},
                {"symbol": "WIN", "net_return": 0.05},
                {"symbol": "WIN", "net_return": 0.02},
                {"symbol": "LOS", "net_return": -0.10},
                {"symbol": "LOS", "net_return": -0.05},
                {"symbol": "LOS", "net_return": 0.01},
                {"symbol": "NEU", "net_return": 0.10},
                {"symbol": "NEU", "net_return": -0.10},
                {"symbol": "NEU", "net_return": -0.02},
                {"symbol": "NEU", "net_return": 0.01},
                {"symbol": "SMALL", "net_return": 0.10},
                {"symbol": "SMALL", "net_return": 0.20},
            ]
        )

        result = build_symbol_confidence(selected).set_index("symbol")

        assert result.loc["WIN", "confidence_level"] == "winner"
        assert result.loc["LOS", "confidence_level"] == "loser"
        assert result.loc["NEU", "confidence_level"] == "neutral"
        assert result.loc["SMALL", "confidence_level"] == "neutral"

    def test_buildMissingFinancials_includesAnnouncementDateAndMissingFields(self):
        rejected = pd.DataFrame(
            [
                {
                    "month": "2026-05",
                    "symbol": "AAA",
                    "score": 1.2,
                    "selection_score": 1.2,
                    "reason": "missing_financial_data",
                    "provisional_rank": 2,
                    "effective_top_n": 6,
                    "period_end": pd.NaT,
                    "equity": 100.0,
                    "net_income_ttm": 20.0,
                    "previous_net_income_ttm": None,
                    "operating_profit_ttm": 15.0,
                    "shares_outstanding": 1000.0,
                    "announcement_date": pd.NaT,
                }
            ]
        )

        result = build_missing_financials(rejected)

        assert result["symbol"].tolist() == ["AAA"]
        assert set(result["missing_fields"].iloc[0]) == {
            "period_end",
            "previous_net_income_ttm",
            "announcement_date",
        }
        assert bool(result["announcement_date_missing"].iloc[0]) is True

    def test_buildCurrentMonthAlerts_keepsOnlyInCutoffRows(self):
        missing = pd.DataFrame(
            [
                {
                    "month": "2026-05",
                    "symbol": "AAA",
                    "provisional_rank": 3,
                    "effective_top_n": 6,
                    "missing_fields": ["announcement_date"],
                    "rejection_reason": "missing_financial_data",
                },
                {
                    "month": "2026-05",
                    "symbol": "BBB",
                    "provisional_rank": 8,
                    "effective_top_n": 6,
                    "missing_fields": ["equity"],
                    "rejection_reason": "missing_financial_data",
                },
                {
                    "month": "2026-04",
                    "symbol": "CCC",
                    "provisional_rank": 1,
                    "effective_top_n": 6,
                    "missing_fields": ["announcement_date"],
                    "rejection_reason": "missing_financial_data",
                },
            ]
        )

        result = build_current_month_alerts(missing, "2026-05")

        assert result["symbol"].tolist() == ["AAA"]

    def test_buildStaleFinancialBaseAlerts_keepsOnlyCurrentMonthStaleRows(self):
        positions = pd.DataFrame(
            [
                {
                    "month": "2026-05",
                    "symbol": "MERKO",
                    "used_period_label": "2024/Q4",
                    "buy_date": "2026-05-04",
                    "financial_base_quarter_lag": 6,
                    "stale_financial_base": True,
                    "financial_base_warning": "Annual baz eski",
                },
                {
                    "month": "2026-05",
                    "symbol": "AAA",
                    "used_period_label": "2025/Q4",
                    "buy_date": "2026-05-04",
                    "financial_base_quarter_lag": 2,
                    "stale_financial_base": False,
                    "financial_base_warning": None,
                },
                {
                    "month": "2026-04",
                    "symbol": "BBB",
                    "used_period_label": "2024/Q4",
                    "buy_date": "2026-04-01",
                    "financial_base_quarter_lag": 6,
                    "stale_financial_base": True,
                    "financial_base_warning": "Annual baz eski",
                },
            ]
        )

        result = build_stale_financial_base_alerts(positions, "2026-05")

        assert result["symbol"].tolist() == ["MERKO"]

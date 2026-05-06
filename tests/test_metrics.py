from __future__ import annotations

import math

import pandas as pd
import pytest

from bist_factor_backtest.backtest.metrics import calculate_equity_curve, calculate_summary


class TestCalculateEquityCurve:
    def test_calculateEquityCurve_validMonthlyResults_returnsDrawdownSeries(self):
        monthly_results = pd.DataFrame(
            [
                {"month": "2024-01", "portfolio_value_end": 100.0},
                {"month": "2024-02", "portfolio_value_end": 120.0},
                {"month": "2024-03", "portfolio_value_end": 90.0},
            ]
        )

        result = calculate_equity_curve(monthly_results)

        assert result["value"].tolist() == [100.0, 120.0, 90.0]
        assert result["peak"].tolist() == [100.0, 120.0, 120.0]
        assert result["drawdown"].tolist() == [0.0, 0.0, -0.25]


class TestCalculateSummary:
    def test_calculateSummary_emptyMonthlyResults_returnsInitialOnly(self):
        monthly_results = pd.DataFrame(columns=["month", "net_return", "portfolio_value_end"])

        result = calculate_summary(monthly_results, 1000.0)

        assert result == {
            "initial_capital": 1000.0,
            "final_capital": 1000.0,
            "total_return": 0.0,
            "number_of_months": 0,
        }

    def test_calculateSummary_nonEmptyMonthlyResults_returnsExpectedMetrics(self):
        monthly_results = pd.DataFrame(
            [
                {"month": "2024-01", "net_return": 0.10, "portfolio_value_end": 1100.0},
                {"month": "2024-02", "net_return": -0.05, "portfolio_value_end": 1045.0},
                {"month": "2024-03", "net_return": 0.20, "portfolio_value_end": 1254.0},
            ]
        )

        result = calculate_summary(monthly_results, 1000.0)

        expected_vol = float(pd.Series([0.10, -0.05, 0.20]).std(ddof=0))
        expected_sharpe = float(pd.Series([0.10, -0.05, 0.20]).mean() / expected_vol) * math.sqrt(12)
        expected_cagr = (1254.0 / 1000.0) ** (12 / 3) - 1

        assert result["initial_capital"] == 1000.0
        assert result["final_capital"] == 1254.0
        assert result["total_return"] == pytest.approx(0.254)
        assert result["cagr"] == pytest.approx(expected_cagr)
        assert result["average_monthly_return"] == pytest.approx((0.10 - 0.05 + 0.20) / 3)
        assert result["monthly_volatility"] == pytest.approx(expected_vol)
        assert result["sharpe"] == pytest.approx(expected_sharpe)
        assert result["max_drawdown"] == pytest.approx(-0.05)
        assert result["win_rate"] == pytest.approx(2 / 3)
        assert result["number_of_months"] == 3
        assert result["best_month"] == "2024-03"
        assert result["worst_month"] == "2024-02"
        assert result["average_selected_stock_return"] is None
        assert result["turnover"] == 1.0

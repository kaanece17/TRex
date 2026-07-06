from pathlib import Path

import pandas as pd

from bist_factor_backtest.dashboard.datasets import (
    build_display_positions,
    build_summary,
    build_current_month_alerts,
    build_missing_financials,
    build_stale_financial_base_alerts,
    _merge_symbol_confidence,
    _annotate_financial_base_freshness,
    build_symbol_confidence,
)
from bist_factor_backtest.config import (
    BacktestConfig,
    BacktestRangeConfig,
    CostsConfig,
    DataConfig,
    FiltersConfig,
    PointInTimeConfig,
    ProjectConfig,
    ScoringConfig,
    StrategyConfig,
    UniverseConfig,
)


class TestDashboardDatasets:
    def test_buildSummary_keepsMetricsOnLastClosedMonthDuringPreview(self):
        config = BacktestConfig(
            project=ProjectConfig(name="test"),
            data=DataConfig(duckdb_path=Path("dummy.duckdb")),
            universe=UniverseConfig(symbols_file=Path("symbols.csv"), membership_file=Path("membership.csv"), name="BIST_SANAYI"),
            point_in_time=PointInTimeConfig(),
            strategy=StrategyConfig(),
            scoring=ScoringConfig(),
            costs=CostsConfig(),
            filters=FiltersConfig(),
            backtest=BacktestRangeConfig(start_date=pd.Timestamp("2026-01-01").date(), end_date=pd.Timestamp("2026-12-31").date(), initial_capital=100000.0),
        )
        monthly_results = pd.DataFrame(
            [
                {"month": "2026-04", "net_return": 0.10, "portfolio_value_start": 100000.0, "portfolio_value_end": 110000.0},
                {"month": "2026-05", "net_return": -0.05, "portfolio_value_start": 110000.0, "portfolio_value_end": 104500.0},
            ]
        )
        display_positions = pd.DataFrame([{"month": "2026-05", "symbol": "AAA"}])
        realized_positions = pd.DataFrame()
        monthly_regimes = pd.DataFrame()
        preview_positions = pd.DataFrame([{"month": "2026-06", "symbol": "BBB"}])

        summary = build_summary(
            config,
            monthly_results,
            display_positions,
            realized_positions,
            monthly_regimes,
            preview_available=True,
            preview_positions=preview_positions,
        )

        assert summary["latest_selected_month"] == "2026-04"
        assert summary["metrics_through_month"] == "2026-04"
        assert summary["open_month_excluded_from_metrics"] is True
        assert summary["number_of_months"] == 1

    def test_buildSummary_includesLatestClosedMonthWhenPreviewIsNextMonth(self):
        config = BacktestConfig(
            project=ProjectConfig(name="test"),
            data=DataConfig(duckdb_path=Path("dummy.duckdb")),
            universe=UniverseConfig(symbols_file=Path("symbols.csv"), membership_file=Path("membership.csv"), name="BIST_SANAYI"),
            point_in_time=PointInTimeConfig(),
            strategy=StrategyConfig(),
            scoring=ScoringConfig(),
            costs=CostsConfig(),
            filters=FiltersConfig(),
            backtest=BacktestRangeConfig(start_date=pd.Timestamp("2026-01-01").date(), end_date=pd.Timestamp("2026-12-31").date(), initial_capital=100000.0),
        )
        monthly_results = pd.DataFrame(
            [
                {"month": "2026-04", "net_return": 0.10, "portfolio_value_start": 100000.0, "portfolio_value_end": 110000.0},
                {"month": "2026-05", "net_return": -0.05, "portfolio_value_start": 110000.0, "portfolio_value_end": 104500.0},
            ]
        )
        display_positions = pd.DataFrame([{"month": "2026-05", "symbol": "AAA"}])
        realized_positions = pd.DataFrame([{"month": "2026-05", "symbol": "AAA"}])
        monthly_regimes = pd.DataFrame()
        preview_positions = pd.DataFrame([{"month": "2026-06", "symbol": "BBB"}])

        summary = build_summary(
            config,
            monthly_results,
            display_positions,
            realized_positions,
            monthly_regimes,
            preview_available=True,
            preview_positions=preview_positions,
            latest_data_month_closed=True,
        )

        assert summary["latest_selected_month"] == "2026-05"
        assert summary["metrics_through_month"] == "2026-05"
        assert summary["open_month_excluded_from_metrics"] is False
        assert summary["number_of_months"] == 2

    def test_buildSummary_usesCurrentOpenMonthFromPlannedPositions(self):
        config = BacktestConfig(
            project=ProjectConfig(name="test"),
            data=DataConfig(duckdb_path=Path("dummy.duckdb")),
            universe=UniverseConfig(symbols_file=Path("symbols.csv"), membership_file=Path("membership.csv"), name="BIST_SANAYI"),
            point_in_time=PointInTimeConfig(),
            strategy=StrategyConfig(),
            scoring=ScoringConfig(),
            costs=CostsConfig(),
            filters=FiltersConfig(),
            backtest=BacktestRangeConfig(start_date=pd.Timestamp("2026-01-01").date(), end_date=pd.Timestamp("2026-12-31").date(), initial_capital=100000.0),
        )
        monthly_results = pd.DataFrame(
            [
                {"month": "2026-05", "net_return": 0.10, "portfolio_value_start": 100000.0, "portfolio_value_end": 110000.0},
                {"month": "2026-06", "net_return": -0.05, "portfolio_value_start": 110000.0, "portfolio_value_end": 104500.0},
            ]
        )
        display_positions = pd.DataFrame(
            [
                {"month": "2026-05", "symbol": "AAA"},
                {"month": "2026-06", "symbol": "BBB"},
                {"month": "2026-07", "symbol": "CCC"},
            ]
        )
        realized_positions = pd.DataFrame([{"month": "2026-05", "symbol": "AAA"}, {"month": "2026-06", "symbol": "BBB"}])
        monthly_regimes = pd.DataFrame()

        summary = build_summary(
            config,
            monthly_results,
            display_positions,
            realized_positions,
            monthly_regimes,
            preview_available=False,
            latest_data_month_closed=True,
            current_open_month="2026-07",
        )

        assert summary["current_month"] == "2026-07"
        assert summary["latest_selected_month"] == "2026-06"
        assert summary["metrics_through_month"] == "2026-06"
        assert summary["open_month_excluded_from_metrics"] is False

    def test_buildDisplayPositions_keepsRealizedRowsWhenLatestMonthAlreadyClosed(self):
        planned_positions = pd.DataFrame([{"month": "2026-06", "symbol": "BBB"}])
        realized_positions = pd.DataFrame(
            [
                {
                    "month": "2026-05",
                    "symbol": "AAA",
                    "fiscal_year": 2025,
                    "fiscal_quarter": 4,
                    "buy_date": "2026-05-04",
                }
            ]
        )

        result = build_display_positions(
            planned_positions=planned_positions,
            realized_positions=realized_positions,
            rejected_candidates=pd.DataFrame(),
            latest_data_month=None,
        )

        assert result["month"].tolist() == ["2026-05", "2026-06"]
        assert result["symbol"].tolist() == ["AAA", "BBB"]
        assert result["position_status"].tolist() == ["realized", "open"]

    def test_buildDisplayPositions_appendsCurrentOpenMonthWithoutDroppingLatestClosedMonth(self):
        planned_positions = pd.DataFrame([{"month": "2026-07", "symbol": "BBB"}])
        realized_positions = pd.DataFrame(
            [
                {"month": "2026-05", "symbol": "AAA"},
                {"month": "2026-06", "symbol": "CCC"},
            ]
        )

        result = build_display_positions(
            planned_positions=planned_positions,
            realized_positions=realized_positions,
            rejected_candidates=pd.DataFrame(),
            latest_data_month=None,
        )

        assert result["month"].tolist() == ["2026-05", "2026-06", "2026-07"]
        assert result["symbol"].tolist() == ["AAA", "CCC", "BBB"]
        assert result["position_status"].tolist() == ["realized", "realized", "open"]

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

    def test_mergeSymbolConfidence_preservesExistingColumnAndFillsMissing(self):
        frame = pd.DataFrame(
            [
                {"symbol": "WIN", "confidence_level": None, "repeat_count": None},
                {"symbol": "KEEP", "confidence_level": "manual", "repeat_count": 9},
            ]
        )
        confidence = pd.DataFrame(
            [
                {"symbol": "WIN", "confidence_level": "winner", "repeat_count": 3},
                {"symbol": "KEEP", "confidence_level": "loser", "repeat_count": 2},
            ]
        )

        result = _merge_symbol_confidence(frame, confidence).set_index("symbol")

        assert result.loc["WIN", "confidence_level"] == "winner"
        assert result.loc["KEEP", "confidence_level"] == "manual"
        assert result.loc["WIN", "repeat_count"] == 3
        assert result.loc["KEEP", "repeat_count"] == 9

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

    def test_annotateFinancialBaseFreshness_handlesSingleScalarFiscalValues(self):
        positions = pd.DataFrame(
            [
                {
                    "month": "2026-05",
                    "symbol": "AAA",
                    "fiscal_year": 2025.0,
                    "fiscal_quarter": 4.0,
                    "buy_date": "2026-05-04",
                }
            ]
        )

        result = _annotate_financial_base_freshness(positions)

        assert result["financial_base_quarter_lag"].iloc[0] == 2
        assert bool(result["stale_financial_base"].iloc[0]) is False

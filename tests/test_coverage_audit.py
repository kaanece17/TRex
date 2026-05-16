from __future__ import annotations

from datetime import date

import pandas as pd

from bist_factor_backtest.data.coverage_audit import (
    build_alternative_coverage_audit,
    build_alternative_fill_queue,
    summarize_alternative_coverage,
)


class TestCoverageAudit:
    def test_buildAlternativeCoverageAudit_classifiesSymbols(self):
        symbols = ["AAA", "BBB", "CCC"]
        statements = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2019-03-31",
                    "announcement_date": "2019-05-10",
                    "shares_outstanding": 100,
                },
                {
                    "symbol": "AAA",
                    "period_end": "2019-06-30",
                    "announcement_date": "2019-08-12",
                    "shares_outstanding": 100,
                },
                {
                    "symbol": "BBB",
                    "period_end": "2020-03-31",
                    "announcement_date": None,
                    "shares_outstanding": None,
                },
            ]
        )
        registry = pd.DataFrame(
            [
                {"symbol": "AAA", "investing_slug": "aaa", "earnings_url": "https://example.com/aaa", "is_active": True},
                {"symbol": "BBB", "investing_slug": None, "earnings_url": None, "is_active": None},
            ]
        )
        aliases = pd.DataFrame(
            [
                {"canonical_symbol": "BBB", "symbol": "OLDBBB"},
            ]
        )

        result = build_alternative_coverage_audit(
            symbols=symbols,
            statements=statements,
            registry=registry,
            aliases=aliases,
            audit_start_date=date(2019, 1, 1),
        )

        aaa = result[result["symbol"] == "AAA"].iloc[0]
        bbb = result[result["symbol"] == "BBB"].iloc[0]
        ccc = result[result["symbol"] == "CCC"].iloc[0]

        assert aaa["coverage_class"] == "fully_covered"
        assert aaa["announcement_coverage_ratio"] == 1.0
        assert aaa["shares_coverage_ratio"] == 1.0
        assert aaa["registry_present"] == True
        assert bbb["coverage_class"] == "partial_history"
        assert bbb["alias_mapping_present"] == True
        assert bbb["missing_announcement_count"] == 1
        assert bbb["missing_shares_count"] == 1
        assert bbb["needs_manual_mapping"] == True
        assert ccc["coverage_class"] == "needs_manual_mapping"
        assert ccc["total_statement_count"] == 0
        assert ccc["registry_missing"] == True

    def test_buildAlternativeCoverageAudit_handlesEmptyInputs(self):
        result = build_alternative_coverage_audit(
            symbols=[],
            statements=pd.DataFrame(),
            registry=pd.DataFrame(),
            aliases=pd.DataFrame(),
            audit_start_date=date(2019, 1, 1),
        )

        assert result.empty

    def test_buildAlternativeCoverageAudit_tracksFirstDatesAndCounts(self):
        statements = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "period_end": "2018-12-31",
                    "announcement_date": "2019-03-10",
                    "shares_outstanding": 0,
                },
                {
                    "symbol": "AAA",
                    "period_end": "2019-03-31",
                    "announcement_date": "2019-05-10",
                    "shares_outstanding": 150,
                },
            ]
        )

        result = build_alternative_coverage_audit(
            symbols=["AAA"],
            statements=statements,
            registry=pd.DataFrame([{"symbol": "AAA", "investing_slug": "aaa"}]),
            aliases=pd.DataFrame(),
            audit_start_date=date(2019, 1, 1),
        )

        row = result.iloc[0]
        assert row["first_statement_period_end"].isoformat() == "2018-12-31"
        assert row["first_statement_period_end_since_start"].isoformat() == "2019-03-31"
        assert row["first_announcement_date"].isoformat() == "2019-03-10"
        assert row["first_shares_period_end"].isoformat() == "2019-03-31"
        assert row["statement_count_since_start"] == 1

    def test_summarizeAlternativeCoverage_returnsMetrics(self):
        audit = pd.DataFrame(
            [
                {
                    "coverage_class": "fully_covered",
                    "registry_missing": False,
                    "registry_url_missing": False,
                    "alias_mapping_present": False,
                    "total_statement_count": 2,
                    "missing_announcement_count": 0,
                    "missing_shares_count": 0,
                },
                {
                    "coverage_class": "needs_manual_mapping",
                    "registry_missing": True,
                    "registry_url_missing": False,
                    "alias_mapping_present": True,
                    "total_statement_count": 0,
                    "missing_announcement_count": 0,
                    "missing_shares_count": 0,
                },
                {
                    "coverage_class": "partial_history",
                    "registry_missing": False,
                    "registry_url_missing": True,
                    "alias_mapping_present": False,
                    "total_statement_count": 1,
                    "missing_announcement_count": 1,
                    "missing_shares_count": 1,
                },
            ]
        )

        result = summarize_alternative_coverage(audit)
        metric_map = dict(result.itertuples(index=False, name=None))

        assert metric_map["symbol_count"] == 3
        assert metric_map["fully_covered_count"] == 1
        assert metric_map["partial_history_count"] == 1
        assert metric_map["needs_manual_mapping_count"] == 1
        assert metric_map["registry_missing_count"] == 1
        assert metric_map["registry_url_missing_count"] == 1
        assert metric_map["alias_mapping_present_count"] == 1
        assert metric_map["statement_covered_count"] == 2
        assert metric_map["announcement_gap_count"] == 1
        assert metric_map["shares_gap_count"] == 1

    def test_summarizeAlternativeCoverage_emptyAudit_returnsEmptyFrame(self):
        result = summarize_alternative_coverage(pd.DataFrame())

        assert result.empty
        assert result.columns.tolist() == ["metric", "value"]

    def test_buildAlternativeFillQueue_prioritizesBlockingReasons(self):
        audit = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "coverage_class": "needs_manual_mapping",
                    "registry_missing": True,
                    "registry_url_missing": False,
                    "total_statement_count": 0,
                    "missing_announcement_count": 0,
                    "missing_shares_count": 0,
                    "needs_manual_mapping": True,
                },
                {
                    "symbol": "BBB",
                    "coverage_class": "partial_history",
                    "registry_missing": False,
                    "registry_url_missing": True,
                    "total_statement_count": 0,
                    "missing_announcement_count": 0,
                    "missing_shares_count": 0,
                    "needs_manual_mapping": True,
                },
                {
                    "symbol": "CCC",
                    "coverage_class": "needs_manual_mapping",
                    "registry_missing": False,
                    "registry_url_missing": False,
                    "total_statement_count": 0,
                    "missing_announcement_count": 0,
                    "missing_shares_count": 0,
                    "needs_manual_mapping": True,
                },
                {
                    "symbol": "DDD",
                    "coverage_class": "partial_history",
                    "registry_missing": False,
                    "registry_url_missing": False,
                    "total_statement_count": 2,
                    "missing_announcement_count": 2,
                    "missing_shares_count": 0,
                    "needs_manual_mapping": False,
                },
                {
                    "symbol": "EEE",
                    "coverage_class": "partial_history",
                    "registry_missing": False,
                    "registry_url_missing": False,
                    "total_statement_count": 2,
                    "missing_announcement_count": 0,
                    "missing_shares_count": 1,
                    "needs_manual_mapping": False,
                },
                {
                    "symbol": "FFF",
                    "coverage_class": "fully_covered",
                    "registry_missing": False,
                    "registry_url_missing": False,
                    "total_statement_count": 2,
                    "missing_announcement_count": 0,
                    "missing_shares_count": 0,
                    "needs_manual_mapping": True,
                },
            ]
        )

        result = build_alternative_fill_queue(audit)

        assert result["symbol"].tolist() == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
        assert result["queue_reason"].tolist() == [
            "missing_registry_mapping",
            "missing_registry_url",
            "missing_statement_coverage",
            "missing_announcement_dates",
            "missing_shares_outstanding",
            "needs_review",
        ]

    def test_buildAlternativeFillQueue_emptyOrCompleteAudit_returnsEmptyFrame(self):
        empty_result = build_alternative_fill_queue(pd.DataFrame())
        complete_result = build_alternative_fill_queue(
            pd.DataFrame(
                [
                    {
                        "symbol": "AAA",
                        "coverage_class": "fully_covered",
                        "registry_missing": False,
                        "registry_url_missing": False,
                        "total_statement_count": 1,
                        "missing_announcement_count": 0,
                        "missing_shares_count": 0,
                        "needs_manual_mapping": False,
                    }
                ]
            )
        )

        assert empty_result.empty
        assert complete_result.empty

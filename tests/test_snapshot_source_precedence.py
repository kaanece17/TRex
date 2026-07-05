from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from bist_factor_backtest.cli import _build_financial_snapshots_from_statements
from bist_factor_backtest.config import DataConfig


def _data_config() -> DataConfig:
    return DataConfig.model_validate(
        {
            "duckdb_path": Path("dummy.duckdb"),
            "primary_statement_source": "queenstocks",
            "statement_fallback_sources": ["isyatirim", "financial_fallback_registry"],
            "primary_announcement_source": "queenstocks",
            "announcement_fallback_sources": ["investing", "issuer_ir"],
        }
    )


def _fallback_data_config() -> DataConfig:
    return DataConfig.model_validate(
        {
            "duckdb_path": Path("dummy.duckdb"),
            "primary_statement_source": "isyatirim",
            "statement_fallback_sources": ["queenstocks", "financial_fallback_registry"],
            "primary_announcement_source": "investing",
            "announcement_fallback_sources": ["queenstocks", "issuer_ir"],
        }
    )


def test_buildFinancialSnapshots_prefersCompletePrimaryStatementSource():
    statements = pd.DataFrame(
        [
            {
                "statement_id": "QUEENSTOCKS-AAA-20260331-1",
                "symbol": "AAA",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": 1000.0,
                "announcement_date": date(2026, 5, 11),
                "source_url": "https://queenstocks.com/report/1",
                "source_system": "queenstocks",
                "announcement_source_url": "https://queenstocks.com/report/1",
                "announcement_source_system": "queenstocks_kap_news",
            },
            {
                "statement_id": "ISYATIRIM-AAA-20260331",
                "symbol": "AAA",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": 1000.0,
                "announcement_date": date(2026, 5, 12),
                "source_url": "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/default.aspx",
                "source_system": "isyatirim",
                "announcement_source_url": "https://tr.investing.com/equities/aaa-earnings",
                "announcement_source_system": "investing",
            },
        ]
    )
    items = pd.DataFrame(
        [
            {"statement_id": "QUEENSTOCKS-AAA-20260331-1", "symbol": "AAA", "item_code": "net_income", "value": 10.0},
            {"statement_id": "QUEENSTOCKS-AAA-20260331-1", "symbol": "AAA", "item_code": "equity", "value": 20.0},
            {
                "statement_id": "QUEENSTOCKS-AAA-20260331-1",
                "symbol": "AAA",
                "item_code": "operating_profit",
                "value": 30.0,
            },
            {"statement_id": "ISYATIRIM-AAA-20260331", "symbol": "AAA", "item_code": "net_income", "value": 11.0},
            {"statement_id": "ISYATIRIM-AAA-20260331", "symbol": "AAA", "item_code": "equity", "value": 21.0},
            {"statement_id": "ISYATIRIM-AAA-20260331", "symbol": "AAA", "item_code": "operating_profit", "value": 31.0},
        ]
    )

    result = _build_financial_snapshots_from_statements(statements, items, data_config=_data_config())

    assert result["source_system"].tolist() == ["queenstocks"]
    assert result["source_statement_id"].tolist() == ["QUEENSTOCKS-AAA-20260331-1"]
    assert result["announcement_source_system"].tolist() == ["queenstocks_kap_news"]
    assert result["net_income"].tolist() == [10.0]


def test_buildFinancialSnapshots_fallsBackWhenPrimaryStatementIsIncomplete():
    statements = pd.DataFrame(
        [
            {
                "statement_id": "QUEENSTOCKS-BBB-20260331-1",
                "symbol": "BBB",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": None,
                "announcement_date": date(2026, 5, 11),
                "source_url": "https://queenstocks.com/report/2",
                "source_system": "queenstocks",
                "announcement_source_url": "https://queenstocks.com/report/2",
                "announcement_source_system": "queenstocks_kap_news",
            },
            {
                "statement_id": "ISYATIRIM-BBB-20260331",
                "symbol": "BBB",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": 500.0,
                "announcement_date": date(2026, 5, 12),
                "source_url": "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/default.aspx",
                "source_system": "isyatirim",
                "announcement_source_url": "https://tr.investing.com/equities/bbb-earnings",
                "announcement_source_system": "investing",
            },
        ]
    )
    items = pd.DataFrame(
        [
            {"statement_id": "QUEENSTOCKS-BBB-20260331-1", "symbol": "BBB", "item_code": "net_income", "value": 10.0},
            {"statement_id": "QUEENSTOCKS-BBB-20260331-1", "symbol": "BBB", "item_code": "equity", "value": 20.0},
            {
                "statement_id": "QUEENSTOCKS-BBB-20260331-1",
                "symbol": "BBB",
                "item_code": "operating_profit",
                "value": 30.0,
            },
            {"statement_id": "ISYATIRIM-BBB-20260331", "symbol": "BBB", "item_code": "net_income", "value": 11.0},
            {"statement_id": "ISYATIRIM-BBB-20260331", "symbol": "BBB", "item_code": "equity", "value": 21.0},
            {"statement_id": "ISYATIRIM-BBB-20260331", "symbol": "BBB", "item_code": "operating_profit", "value": 31.0},
        ]
    )

    result = _build_financial_snapshots_from_statements(statements, items, data_config=_data_config())

    assert result["source_system"].tolist() == ["isyatirim"]
    assert result["source_statement_id"].tolist() == ["ISYATIRIM-BBB-20260331"]
    assert result["shares_outstanding"].tolist() == [500.0]


def test_buildFinancialSnapshots_resolvesAnnouncementSourceIndependently():
    statements = pd.DataFrame(
        [
            {
                "statement_id": "QUEENSTOCKS-CCC-20260331-1",
                "symbol": "CCC",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": 700.0,
                "announcement_date": None,
                "source_url": "https://queenstocks.com/report/3",
                "source_system": "queenstocks",
                "announcement_source_url": None,
                "announcement_source_system": None,
            },
            {
                "statement_id": "ISYATIRIM-CCC-20260331",
                "symbol": "CCC",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": 700.0,
                "announcement_date": date(2026, 5, 13),
                "source_url": "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/default.aspx",
                "source_system": "isyatirim",
                "announcement_source_url": "https://tr.investing.com/equities/ccc-earnings",
                "announcement_source_system": "investing",
            },
        ]
    )
    items = pd.DataFrame(
        [
            {"statement_id": "QUEENSTOCKS-CCC-20260331-1", "symbol": "CCC", "item_code": "net_income", "value": 10.0},
            {"statement_id": "QUEENSTOCKS-CCC-20260331-1", "symbol": "CCC", "item_code": "equity", "value": 20.0},
            {
                "statement_id": "QUEENSTOCKS-CCC-20260331-1",
                "symbol": "CCC",
                "item_code": "operating_profit",
                "value": 30.0,
            },
            {"statement_id": "ISYATIRIM-CCC-20260331", "symbol": "CCC", "item_code": "net_income", "value": 11.0},
            {"statement_id": "ISYATIRIM-CCC-20260331", "symbol": "CCC", "item_code": "equity", "value": 21.0},
            {"statement_id": "ISYATIRIM-CCC-20260331", "symbol": "CCC", "item_code": "operating_profit", "value": 31.0},
        ]
    )

    result = _build_financial_snapshots_from_statements(statements, items, data_config=_data_config())

    assert result["source_system"].tolist() == ["queenstocks"]
    assert result["announcement_source_system"].tolist() == ["investing"]
    assert result["announcement_date"].tolist() == [date(2026, 5, 13)]


def test_buildFinancialSnapshots_prefersCurrentPrimaryWhenQueenstocksIsFallback():
    statements = pd.DataFrame(
        [
            {
                "statement_id": "QUEENSTOCKS-DDD-20260331-1",
                "symbol": "DDD",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": 1000.0,
                "announcement_date": date(2026, 5, 11),
                "source_url": "https://queenstocks.com/report/4",
                "source_system": "queenstocks",
                "announcement_source_url": "https://queenstocks.com/report/4",
                "announcement_source_system": "queenstocks_kap_news",
            },
            {
                "statement_id": "ISYATIRIM-DDD-20260331",
                "symbol": "DDD",
                "period_end": date(2026, 3, 31),
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "shares_outstanding": 1000.0,
                "announcement_date": date(2026, 5, 12),
                "source_url": "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/default.aspx",
                "source_system": "isyatirim",
                "announcement_source_url": "https://tr.investing.com/equities/ddd-earnings",
                "announcement_source_system": "investing",
            },
        ]
    )
    items = pd.DataFrame(
        [
            {"statement_id": "QUEENSTOCKS-DDD-20260331-1", "symbol": "DDD", "item_code": "net_income", "value": 10.0},
            {"statement_id": "QUEENSTOCKS-DDD-20260331-1", "symbol": "DDD", "item_code": "equity", "value": 20.0},
            {"statement_id": "QUEENSTOCKS-DDD-20260331-1", "symbol": "DDD", "item_code": "operating_profit", "value": 30.0},
            {"statement_id": "ISYATIRIM-DDD-20260331", "symbol": "DDD", "item_code": "net_income", "value": 11.0},
            {"statement_id": "ISYATIRIM-DDD-20260331", "symbol": "DDD", "item_code": "equity", "value": 21.0},
            {"statement_id": "ISYATIRIM-DDD-20260331", "symbol": "DDD", "item_code": "operating_profit", "value": 31.0},
        ]
    )

    result = _build_financial_snapshots_from_statements(
        statements,
        items,
        data_config=_fallback_data_config(),
    )

    assert result["source_system"].tolist() == ["isyatirim"]
    assert result["source_statement_id"].tolist() == ["ISYATIRIM-DDD-20260331"]
    assert result["announcement_source_system"].tolist() == ["investing"]
    assert result["net_income"].tolist() == [11.0]

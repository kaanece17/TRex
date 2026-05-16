from datetime import date

import pandas as pd

from bist_factor_backtest.cli import _build_financial_snapshots_from_statements


def test_buildFinancialSnapshotsFromStatements_appliesSymbolAliasesToLegacyTickerRows():
    statements = pd.DataFrame(
        [
            {
                "statement_id": "legacy-1",
                "symbol": "EFORC",
                "period_end": date(2025, 9, 1),
                "fiscal_year": 2025,
                "fiscal_period": "Q3",
                "announcement_date": date(2025, 11, 10),
            },
            {
                "statement_id": "current-1",
                "symbol": "EFOR",
                "period_end": date(2025, 12, 1),
                "fiscal_year": 2025,
                "fiscal_period": "Q4",
                "announcement_date": date(2026, 2, 10),
            },
        ]
    )
    items = pd.DataFrame(
        [
            {"statement_id": "legacy-1", "symbol": "EFORC", "item_code": "net_income", "value": 1.0},
            {"statement_id": "legacy-1", "symbol": "EFORC", "item_code": "equity", "value": 2.0},
            {"statement_id": "legacy-1", "symbol": "EFORC", "item_code": "operating_profit", "value": 3.0},
            {"statement_id": "current-1", "symbol": "EFOR", "item_code": "net_income", "value": 4.0},
            {"statement_id": "current-1", "symbol": "EFOR", "item_code": "equity", "value": 5.0},
            {"statement_id": "current-1", "symbol": "EFOR", "item_code": "operating_profit", "value": 6.0},
        ]
    )
    aliases = pd.DataFrame(
        [
            {
                "canonical_symbol": "EFOR",
                "symbol": "EFORC",
                "valid_from": date(2025, 11, 3),
                "valid_to": None,
            }
        ]
    )

    result = _build_financial_snapshots_from_statements(statements, items, aliases)

    assert result["symbol"].tolist() == ["EFOR", "EFOR"]
    assert result["source_statement_id"].tolist() == ["legacy-1", "current-1"]

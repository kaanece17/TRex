from __future__ import annotations

import pandas as pd

from bist_factor_backtest.cli import (
    _filter_only_incomplete_symbols,
    _replace_items_for_statements,
    _symbol_completeness,
    _upsert_statements,
    _upsert_symbol_load_status,
)
from bist_factor_backtest.data.storage import DuckDbStorage


class TestKapResumeCompleteness:
    def test_symbolCompleteness_fullData_returnsComplete(self, tmp_path):
        storage = DuckDbStorage(tmp_path / "test.duckdb")
        storage.initialize()
        storage.append_table(
            "financial_statements",
            pd.DataFrame(
                [
                    {"statement_id": "AAA-1", "symbol": "AAA", "shares_outstanding": 10.0},
                    {"statement_id": "AAA-2", "symbol": "AAA", "shares_outstanding": 20.0},
                ]
            ),
        )
        storage.append_table(
            "financial_statement_items",
            pd.DataFrame(
                [
                    {"statement_id": "AAA-1", "symbol": "AAA", "item_code": "net_income", "item_name": "net_income", "value": 1.0},
                    {"statement_id": "AAA-1", "symbol": "AAA", "item_code": "equity", "item_name": "equity", "value": 1.0},
                    {"statement_id": "AAA-1", "symbol": "AAA", "item_code": "operating_profit", "item_name": "operating_profit", "value": 1.0},
                    {"statement_id": "AAA-2", "symbol": "AAA", "item_code": "net_income", "item_name": "net_income", "value": 1.0},
                    {"statement_id": "AAA-2", "symbol": "AAA", "item_code": "equity", "item_name": "equity", "value": 1.0},
                    {"statement_id": "AAA-2", "symbol": "AAA", "item_code": "operating_profit", "item_name": "operating_profit", "value": 1.0},
                ]
            ),
        )

        result = _symbol_completeness(storage, "AAA", {"AAA-1", "AAA-2"})

        assert result["is_complete"] is True
        assert result["missing_or_incomplete_statement_ids"] == set()
        storage.close()

    def test_symbolCompleteness_missingItemsOrShares_returnsIncompleteIds(self, tmp_path):
        storage = DuckDbStorage(tmp_path / "test.duckdb")
        storage.initialize()
        storage.append_table(
            "financial_statements",
            pd.DataFrame(
                [
                    {"statement_id": "AAA-1", "symbol": "AAA", "shares_outstanding": None},
                    {"statement_id": "AAA-2", "symbol": "AAA", "shares_outstanding": 20.0},
                ]
            ),
        )
        storage.append_table(
            "financial_statement_items",
            pd.DataFrame(
                [
                    {"statement_id": "AAA-2", "symbol": "AAA", "item_code": "net_income", "item_name": "net_income", "value": 1.0},
                    {"statement_id": "AAA-2", "symbol": "AAA", "item_code": "equity", "item_name": "equity", "value": 1.0},
                ]
            ),
        )

        result = _symbol_completeness(storage, "AAA", {"AAA-1", "AAA-2", "AAA-3"})

        assert result["is_complete"] is False
        assert result["missing_or_incomplete_statement_ids"] == {"AAA-1", "AAA-2", "AAA-3"}
        storage.close()


class TestKapResumeUpsert:
    def test_upsertStatements_existingStatement_replacesRow(self, tmp_path):
        storage = DuckDbStorage(tmp_path / "test.duckdb")
        storage.initialize()
        storage.append_table(
            "financial_statements",
            pd.DataFrame([{"statement_id": "AAA-1", "symbol": "AAA", "shares_outstanding": None}]),
        )

        _upsert_statements(
            storage,
            pd.DataFrame([{"statement_id": "AAA-1", "symbol": "AAA", "shares_outstanding": 123.0}]),
        )
        result = storage.connection.execute(
            "SELECT shares_outstanding FROM financial_statements WHERE statement_id = 'AAA-1'"
        ).fetchone()[0]

        assert result == 123.0
        storage.close()

    def test_replaceItemsForStatements_existingItems_replacesOnlyTargetStatements(self, tmp_path):
        storage = DuckDbStorage(tmp_path / "test.duckdb")
        storage.initialize()
        storage.append_table(
            "financial_statement_items",
            pd.DataFrame(
                [
                    {"statement_id": "AAA-1", "symbol": "AAA", "item_code": "net_income", "item_name": "net_income", "value": 1.0},
                    {"statement_id": "BBB-1", "symbol": "BBB", "item_code": "net_income", "item_name": "net_income", "value": 2.0},
                ]
            ),
        )

        _replace_items_for_statements(
            storage,
            pd.DataFrame(
                [
                    {"statement_id": "AAA-1", "symbol": "AAA", "item_code": "equity", "item_name": "equity", "value": 3.0},
                ]
            ),
        )
        aaa_rows = storage.connection.execute(
            "SELECT item_code FROM financial_statement_items WHERE statement_id = 'AAA-1'"
        ).fetchall()
        bbb_rows = storage.connection.execute(
            "SELECT item_code FROM financial_statement_items WHERE statement_id = 'BBB-1'"
        ).fetchall()

        assert aaa_rows == [("equity",)]
        assert bbb_rows == [("net_income",)]
        storage.close()

    def test_upsertSymbolLoadStatus_completedSymbol_existsInStatusTable(self, tmp_path):
        storage = DuckDbStorage(tmp_path / "test.duckdb")
        storage.initialize()

        _upsert_symbol_load_status(storage, "AAA", "completed", "already_complete")
        result = storage.connection.execute(
            "SELECT status, reason FROM statement_load_status WHERE symbol='AAA' AND statement_id='__SYMBOL__'"
        ).fetchone()

        assert result == ("completed", "already_complete")
        storage.close()

    def test_filterOnlyIncompleteSymbols_completedAndIncompleteSymbols_returnsOnlyIncomplete(self, tmp_path):
        db_path = tmp_path / "test.duckdb"
        storage = DuckDbStorage(db_path)
        storage.initialize()
        _upsert_symbol_load_status(storage, "AAA", "completed", "already_complete")
        _upsert_symbol_load_status(storage, "BBB", "incomplete", "still_incomplete")
        storage.close()

        result = _filter_only_incomplete_symbols(["AAA", "BBB", "CCC"], db_path)
        expected = ["BBB", "CCC"]

        assert result == expected

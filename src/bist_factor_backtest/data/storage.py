from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS securities (
    symbol TEXT,
    yahoo_symbol TEXT,
    company_name TEXT,
    sector TEXT,
    is_active BOOLEAN,
    first_seen_date DATE,
    last_seen_date DATE
);

CREATE TABLE IF NOT EXISTS financial_statements (
    statement_id TEXT,
    symbol TEXT,
    period_end DATE,
    fiscal_year INTEGER,
    fiscal_period TEXT,
    statement_type TEXT,
    announcement_datetime TIMESTAMP,
    announcement_date DATE,
    currency TEXT,
    is_consolidated BOOLEAN,
    is_revised BOOLEAN,
    source_url TEXT,
    announcement_source_url TEXT,
    raw_hash TEXT,
    created_at TIMESTAMP,
    shares_outstanding DOUBLE,
    shares_announcement_datetime TIMESTAMP,
    shares_source_url TEXT
);

CREATE TABLE IF NOT EXISTS financial_statement_items (
    statement_id TEXT,
    symbol TEXT,
    item_code TEXT,
    item_name TEXT,
    value DOUBLE
);

CREATE TABLE IF NOT EXISTS financial_snapshots (
    symbol TEXT,
    period_end DATE,
    fiscal_year INTEGER,
    fiscal_period TEXT,
    fiscal_quarter INTEGER,
    announcement_datetime TIMESTAMP,
    announcement_date DATE,
    net_income DOUBLE,
    equity DOUBLE,
    operating_profit DOUBLE,
    cash DOUBLE,
    total_debt DOUBLE,
    shares_outstanding DOUBLE,
    shares_announcement_datetime TIMESTAMP,
    shares_source_url TEXT,
    net_income_ttm DOUBLE,
    operating_profit_ttm DOUBLE,
    previous_net_income_ttm DOUBLE,
    net_income_growth DOUBLE,
    firm_value_price DOUBLE,
    firm_value_price_date DATE,
    firm_value DOUBLE,
    source_statement_id TEXT,
    source_url TEXT,
    announcement_source_url TEXT,
    raw_hash TEXT
);

CREATE TABLE IF NOT EXISTS market_prices (
    symbol TEXT,
    date DATE,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    adjusted_close DOUBLE,
    volume DOUBLE
);

CREATE TABLE IF NOT EXISTS universe_membership (
    symbol TEXT,
    universe_name TEXT,
    start_date DATE,
    end_date DATE,
    source_type TEXT,
    source_url TEXT,
    confidence TEXT
);

CREATE TABLE IF NOT EXISTS universe_monthly_snapshot (
    month TEXT,
    rebalance_date DATE,
    universe_name TEXT,
    symbol TEXT,
    source_quality TEXT
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT,
    created_at TIMESTAMP,
    config_hash TEXT,
    start_date DATE,
    end_date DATE,
    initial_capital DOUBLE,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS backtest_monthly_results (
    run_id TEXT,
    month TEXT,
    rebalance_datetime TIMESTAMP,
    buy_date DATE,
    sell_date DATE,
    gross_return DOUBLE,
    net_return DOUBLE,
    portfolio_value_start DOUBLE,
    portfolio_value_end DOUBLE,
    selected_symbols TEXT
);

CREATE TABLE IF NOT EXISTS backtest_selected_positions (
    run_id TEXT,
    month TEXT,
    symbol TEXT,
    weight DOUBLE,
    score DOUBLE,
    x1 DOUBLE,
    x2 DOUBLE,
    net_income_ttm DOUBLE,
    previous_net_income_ttm DOUBLE,
    net_income_growth DOUBLE,
    equity DOUBLE,
    operating_profit_ttm DOUBLE,
    firm_value DOUBLE,
    firm_value_price DOUBLE,
    firm_value_price_date DATE,
    shares_outstanding DOUBLE,
    shares_announcement_datetime TIMESTAMP,
    shares_source_url TEXT,
    total_debt DOUBLE,
    cash DOUBLE,
    buy_date DATE,
    buy_price DOUBLE,
    sell_date DATE,
    sell_price DOUBLE,
    gross_return DOUBLE,
    net_return DOUBLE,
    used_period_end DATE,
    used_announcement_datetime TIMESTAMP,
    source_statement_id TEXT,
    source_url TEXT,
    universe_source_type TEXT,
    universe_source_url TEXT,
    universe_confidence TEXT
);

CREATE TABLE IF NOT EXISTS statement_load_status (
    statement_id TEXT,
    symbol TEXT,
    status TEXT,
    reason TEXT,
    updated_at TIMESTAMP
);
"""


class DuckDbStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(self.path))

    def initialize(self) -> None:
        self.connection.execute(SCHEMA_SQL)
        self._migrate_schema()

    def replace_table(self, table: str, data: pd.DataFrame) -> None:
        aligned = self._align_to_table_columns(table, data)
        self.connection.register("incoming_data", aligned)
        self.connection.execute(f"DELETE FROM {table}")
        self.connection.execute(f"INSERT INTO {table} SELECT * FROM incoming_data")
        self.connection.unregister("incoming_data")

    def append_table(self, table: str, data: pd.DataFrame) -> None:
        aligned = self._align_to_table_columns(table, data)
        self.connection.register("incoming_data", aligned)
        self.connection.execute(f"INSERT INTO {table} SELECT * FROM incoming_data")
        self.connection.unregister("incoming_data")

    def read_table(self, table: str) -> pd.DataFrame:
        return self.connection.execute(f"SELECT * FROM {table}").df()

    def close(self) -> None:
        self.connection.close()

    def _align_to_table_columns(self, table: str, data: pd.DataFrame) -> pd.DataFrame:
        columns = self.connection.execute(f"PRAGMA table_info('{table}')").df()["name"].tolist()
        aligned = data.copy()
        for column in columns:
            if column not in aligned.columns:
                aligned[column] = None
        return aligned[columns]

    def _migrate_schema(self) -> None:
        table_columns = self.connection.execute("PRAGMA table_info('universe_membership')").df()["name"].tolist()
        for column in ["source_type", "source_url", "confidence"]:
            if column not in table_columns:
                self.connection.execute(f"ALTER TABLE universe_membership ADD COLUMN {column} TEXT")
        position_columns = self.connection.execute("PRAGMA table_info('backtest_selected_positions')").df()["name"].tolist()
        for column in ["universe_source_type", "universe_source_url", "universe_confidence"]:
            if column not in position_columns:
                self.connection.execute(f"ALTER TABLE backtest_selected_positions ADD COLUMN {column} TEXT")
        statement_columns = self.connection.execute("PRAGMA table_info('financial_statements')").df()["name"].tolist()
        if "announcement_source_url" not in statement_columns:
            self.connection.execute("ALTER TABLE financial_statements ADD COLUMN announcement_source_url TEXT")
        snapshot_columns = self.connection.execute("PRAGMA table_info('financial_snapshots')").df()["name"].tolist()
        if "announcement_source_url" not in snapshot_columns:
            self.connection.execute("ALTER TABLE financial_snapshots ADD COLUMN announcement_source_url TEXT")
        self._ensure_text_column_type(
            table="financial_statements",
            columns=["statement_id", "raw_hash"],
        )
        self._ensure_text_column_type(
            table="financial_snapshots",
            columns=["source_statement_id", "raw_hash"],
        )

    def _ensure_text_column_type(self, table: str, columns: list[str]) -> None:
        info = self.connection.execute(f"PRAGMA table_info('{table}')").df()
        current_types = {
            str(row["name"]): str(row["type"]).upper()
            for _, row in info.iterrows()
        }
        needs_rebuild = any(current_types.get(column, "TEXT") != "TEXT" for column in columns)
        if not needs_rebuild:
            return
        temp_table = f"{table}__migrated"
        self.connection.execute(f"DROP TABLE IF EXISTS {temp_table}")
        table_sql = self.connection.execute(
            "SELECT sql FROM duckdb_tables() WHERE table_name = ?",
            [table],
        ).fetchone()
        if table_sql is None or table_sql[0] is None:
            return
        create_sql = str(table_sql[0]).replace(f"CREATE TABLE {table}", f"CREATE TABLE {temp_table}")
        for column in columns:
            current_type = current_types.get(column)
            if current_type and current_type != "TEXT":
                create_sql = create_sql.replace(f"{column} {current_type}", f"{column} TEXT")
        self.connection.execute(create_sql)
        select_parts: list[str] = []
        for _, row in info.iterrows():
            name = str(row["name"])
            if name in columns:
                select_parts.append(f"CAST({name} AS TEXT) AS {name}")
            else:
                select_parts.append(name)
        self.connection.execute(
            f"INSERT INTO {temp_table} SELECT {', '.join(select_parts)} FROM {table}"
        )
        self.connection.execute(f"DROP TABLE {table}")
        self.connection.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")

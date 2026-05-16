from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


def build_priority(connection: duckdb.DuckDBPyConnection, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    date_df = connection.execute(
        """
        with sel as (
          select symbol, used_period_end
          from backtest_selected_positions
          where run_id = ?
        ),
        snap as (
          select symbol, period_end, announcement_date, announcement_datetime
          from financial_snapshots
        )
        select
          sel.symbol,
          count(*) as selected_positions,
          sum(case when snap.announcement_date is null then 1 else 0 end) as missing_announcement_date_positions,
          round(
            1.0 * sum(case when snap.announcement_date is null then 1 else 0 end) / count(*),
            4
          ) as missing_announcement_date_ratio
        from sel
        left join snap
          on sel.symbol = snap.symbol and sel.used_period_end = snap.period_end
        group by 1
        having sum(case when snap.announcement_date is null then 1 else 0 end) > 0
        order by missing_announcement_date_positions desc, selected_positions desc, symbol
        """,
        [run_id],
    ).df()

    datetime_df = connection.execute(
        """
        with sel as (
          select symbol, used_period_end, used_announcement_datetime
          from backtest_selected_positions
          where run_id = ?
        ),
        snap as (
          select symbol, period_end, announcement_date, announcement_datetime
          from financial_snapshots
        )
        select
          sel.symbol,
          count(*) as selected_positions,
          sum(case when sel.used_announcement_datetime is null then 1 else 0 end) as missing_used_announcement_datetime_positions,
          sum(case when snap.announcement_datetime is null then 1 else 0 end) as missing_snapshot_announcement_datetime_positions,
          round(
            1.0 * sum(case when sel.used_announcement_datetime is null then 1 else 0 end) / count(*),
            4
          ) as missing_used_announcement_datetime_ratio
        from sel
        left join snap
          on sel.symbol = snap.symbol and sel.used_period_end = snap.period_end
        group by 1
        having sum(case when sel.used_announcement_datetime is null then 1 else 0 end) > 0
        order by missing_used_announcement_datetime_positions desc, selected_positions desc, symbol
        """,
        [run_id],
    ).df()

    return date_df, datetime_df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(args.db, read_only=True)
    date_df, datetime_df = build_priority(connection, args.run_id)

    date_path = output_dir / "selected_missing_announcement_date_priority.csv"
    datetime_path = output_dir / "selected_missing_announcement_datetime_priority.csv"

    date_df.to_csv(date_path, index=False)
    datetime_df.to_csv(datetime_path, index=False)

    print(f"wrote {date_path}")
    print(f"wrote {datetime_path}")
    print(f"missing_announcement_date_symbols={len(date_df)}")
    print(f"missing_announcement_datetime_symbols={len(datetime_df)}")


if __name__ == "__main__":
    main()

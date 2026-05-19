from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd


def _load_monthly(con: duckdb.DuckDBPyConnection, run_id: str) -> pd.DataFrame:
    return con.execute(
        """
        select
          month,
          buy_date,
          sell_date,
          gross_return,
          net_return,
          portfolio_value_start,
          portfolio_value_end,
          selected_symbols
        from backtest_monthly_results
        where run_id = ?
        order by month
        """,
        [run_id],
    ).fetchdf()


def _load_selected(con: duckdb.DuckDBPyConnection, run_id: str) -> pd.DataFrame:
    return con.execute(
        """
        select
          month,
          symbol,
          score,
          x1,
          x2,
          used_period_end,
          cast(used_announcement_datetime as date) as used_announcement_date,
          buy_date,
          buy_price,
          sell_date,
          sell_price,
          net_return,
          universe_confidence
        from backtest_selected_positions
        where run_id = ?
        order by month, score desc, symbol
        """,
        [run_id],
    ).fetchdf()


def _load_selected_with_snapshot(con: duckdb.DuckDBPyConnection, run_id: str) -> pd.DataFrame:
    return con.execute(
        """
        with selected as (
          select
            month,
            symbol,
            used_period_end,
            used_announcement_datetime,
            universe_confidence
          from backtest_selected_positions
          where run_id = ?
        ),
        snap as (
          select
            symbol,
            period_end,
            announcement_date,
            announcement_datetime
          from financial_snapshots
        )
        select
          s.month,
          s.symbol,
          s.used_period_end,
          cast(s.used_announcement_datetime as date) as used_announcement_date,
          date_diff('day', cast(s.used_announcement_datetime as date), current_date) as announcement_age_days,
          s.universe_confidence,
          snap.announcement_date as snapshot_announcement_date,
          snap.announcement_datetime as snapshot_announcement_datetime
        from selected s
        left join snap
          on s.symbol = snap.symbol and s.used_period_end = snap.period_end
        order by s.month, s.symbol
        """,
        [run_id],
    ).fetchdf()


def _load_gap_audit(report_path: Path) -> pd.DataFrame:
    audit = pd.read_csv(report_path)
    date_cols = ["listing_date", "first_statement_period", "first_announcement_period", "first_missing_period", "last_missing_period"]
    for col in date_cols:
        if col in audit.columns:
            audit[col] = pd.to_datetime(audit[col], errors="coerce").dt.date
    return audit


def _records(df: pd.DataFrame) -> list[dict]:
    clean = df.copy()
    for col in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[col]):
            clean[col] = clean[col].dt.strftime("%Y-%m-%d")
        elif clean[col].dtype == object:
            clean[col] = clean[col].map(
                lambda value: value.isoformat() if hasattr(value, "isoformat") and value is not None else value
            )
    clean = clean.astype(object)
    clean = clean.where(pd.notnull(clean), None)
    return clean.to_dict(orient="records")


def build_dataset(db_path: Path, run_id: str, report_path: Path, output_dir: Path, config_name: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)

    monthly = _load_monthly(con, run_id)
    selected = _load_selected(con, run_id)
    coverage = _load_selected_with_snapshot(con, run_id)
    audit = _load_gap_audit(report_path)
    con.close()

    selected_cov = coverage.merge(
        audit[
            [
                "symbol",
                "listing_gap_class",
                "post_listing_fetch_gap_count",
                "pre_listing_expected_gap_count",
                "first_missing_period",
                "last_missing_period",
            ]
        ],
        on="symbol",
        how="left",
    )
    selected_cov["selection_gap_flag"] = selected_cov["post_listing_fetch_gap_count"].fillna(0).gt(0).map(
        {True: "open_gap", False: "clean"}
    )

    monthly_cov = (
        selected_cov.groupby("month", dropna=False)
        .agg(
            selected_count=("symbol", "count"),
            open_gap_symbol_count=("post_listing_fetch_gap_count", lambda s: int((s.fillna(0) > 0).sum())),
            clean_symbol_count=("post_listing_fetch_gap_count", lambda s: int((s.fillna(0) <= 0).sum())),
            open_gap_position_ratio=("post_listing_fetch_gap_count", lambda s: float((s.fillna(0) > 0).mean()) if len(s) else 0.0),
            avg_post_listing_gap_count=("post_listing_fetch_gap_count", lambda s: float(s.fillna(0).mean()) if len(s) else 0.0),
            max_post_listing_gap_count=("post_listing_fetch_gap_count", lambda s: int(s.fillna(0).max()) if len(s) else 0),
        )
        .reset_index()
    )
    open_gap_symbols = (
        selected_cov[selected_cov["post_listing_fetch_gap_count"].fillna(0) > 0]
        .groupby("month")["symbol"]
        .apply(lambda s: ", ".join(sorted(set(s))))
        .rename("symbols_with_open_gaps")
        .reset_index()
    )
    monthly_cov = monthly_cov.merge(open_gap_symbols, on="month", how="left")
    monthly_cov["symbols_with_open_gaps"] = monthly_cov["symbols_with_open_gaps"].fillna("")

    open_gaps = audit[audit["post_listing_fetch_gap_count"].fillna(0) > 0].copy()
    open_gaps = open_gaps.sort_values(["post_listing_fetch_gap_count", "missing_periods_2019_plus", "symbol"], ascending=[False, False, True])

    ending_capital = float(monthly["portfolio_value_end"].iloc[-1]) if not monthly.empty else 0.0
    initial_capital = float(monthly["portfolio_value_start"].iloc[0]) if not monthly.empty else 0.0
    open_gap_positions = int((selected_cov["post_listing_fetch_gap_count"].fillna(0) > 0).sum())
    total_positions = int(len(selected_cov))

    summary = {
        "run_id": run_id,
        "config_name": config_name,
        "first_month": str(monthly["month"].iloc[0]) if not monthly.empty else None,
        "last_month": str(monthly["month"].iloc[-1]) if not monthly.empty else None,
        "month_count": int(len(monthly)),
        "position_count": total_positions,
        "months_with_positions": int((monthly["selected_symbols"].fillna("") != "").sum()) if not monthly.empty else 0,
        "empty_months": int((monthly["selected_symbols"].fillna("") == "").sum()) if not monthly.empty else 0,
        "initial_capital": initial_capital,
        "ending_capital": ending_capital,
        "total_return": (ending_capital / initial_capital - 1.0) if initial_capital else None,
        "avg_monthly_return": float(monthly["net_return"].mean()) if not monthly.empty else None,
        "median_monthly_return": float(monthly["net_return"].median()) if not monthly.empty else None,
        "best_month_return": float(monthly["net_return"].max()) if not monthly.empty else None,
        "worst_month_return": float(monthly["net_return"].min()) if not monthly.empty else None,
        "unique_symbol_count": int(selected["symbol"].nunique()) if not selected.empty else 0,
        "positions_with_open_gap": open_gap_positions,
        "positions_without_open_gap": total_positions - open_gap_positions,
        "open_gap_position_ratio": (open_gap_positions / total_positions) if total_positions else 0.0,
        "high_confidence_positions": int((selected["universe_confidence"] == "high").sum()) if not selected.empty else 0,
        "medium_confidence_positions": int((selected["universe_confidence"] == "medium").sum()) if not selected.empty else 0,
        "low_confidence_positions": int((selected["universe_confidence"] == "low").sum()) if not selected.empty else 0,
    }

    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=True, indent=2))
    (output_dir / "monthly_returns.json").write_text(json.dumps(_records(monthly), ensure_ascii=True, indent=2))
    (output_dir / "selected_positions.json").write_text(json.dumps(_records(selected), ensure_ascii=True, indent=2))
    (output_dir / "selected_coverage.json").write_text(json.dumps(_records(selected_cov), ensure_ascii=True, indent=2))
    (output_dir / "monthly_coverage.json").write_text(json.dumps(_records(monthly_cov), ensure_ascii=True, indent=2))
    (output_dir / "open_gaps.json").write_text(
        json.dumps(
            _records(
                open_gaps[
                    [
                        "symbol",
                        "post_listing_fetch_gap_count",
                        "pre_listing_expected_gap_count",
                        "missing_periods_2019_plus",
                        "first_missing_period",
                        "last_missing_period",
                        "listing_gap_class",
                    ]
                ]
            ),
            ensure_ascii=True,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config-name", required=True)
    args = parser.parse_args()

    build_dataset(
        db_path=Path(args.db),
        run_id=args.run_id,
        report_path=Path(args.report_csv),
        output_dir=Path(args.output_dir),
        config_name=args.config_name,
    )


if __name__ == "__main__":
    main()

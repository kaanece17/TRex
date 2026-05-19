from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
AS_OF_DATE = date(2026, 5, 19)
EXPECTED_LATEST_PERIOD_END = date(2025, 12, 1)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    audit = con.execute(
        """
        with latest as (
          select
            symbol,
            max(period_end) as latest_period_end,
            max(case when fiscal_quarter = 4 then period_end end) as latest_annual_period_end,
            max(announcement_date) as latest_announcement_date
          from financial_snapshots
          group by 1
        ),
        latest_status as (
          select symbol, status, reason, updated_at
          from (
            select
              symbol,
              status,
              reason,
              updated_at,
              row_number() over (partition by symbol order by updated_at desc) as rn
            from statement_load_status
            where statement_id = '__SYMBOL__'
          )
          where rn = 1
        )
        select
          latest.symbol,
          latest.latest_period_end,
          latest.latest_annual_period_end,
          latest.latest_announcement_date,
          latest_status.status as load_status,
          latest_status.reason as load_reason,
          latest_status.updated_at as status_updated_at
        from latest
        left join latest_status using (symbol)
        order by latest.latest_period_end asc, latest.symbol asc
        """
    ).df()
    con.close()

    audit["latest_period_end"] = pd.to_datetime(audit["latest_period_end"], errors="coerce").dt.date
    audit["latest_annual_period_end"] = pd.to_datetime(audit["latest_annual_period_end"], errors="coerce").dt.date
    audit["latest_announcement_date"] = pd.to_datetime(audit["latest_announcement_date"], errors="coerce").dt.date
    audit["period_stale_vs_2025q4"] = audit["latest_period_end"] < EXPECTED_LATEST_PERIOD_END
    audit["annual_stale_vs_2025q4"] = audit["latest_annual_period_end"] < EXPECTED_LATEST_PERIOD_END
    audit["latest_period_lag_quarters"] = audit["latest_period_end"].map(_quarter_lag_from_expected)
    audit["latest_annual_lag_quarters"] = audit["latest_annual_period_end"].map(_quarter_lag_from_expected)
    audit["announcement_age_days"] = audit["latest_announcement_date"].map(
        lambda value: (AS_OF_DATE - value).days if value is not None and pd.notna(value) else None
    )

    stale = audit[audit["annual_stale_vs_2025q4"]].copy().sort_values(
        ["latest_annual_period_end", "latest_period_end", "symbol"]
    )

    audit.to_csv(OUTPUT_DIR / "financial_freshness_audit.csv", index=False)
    stale.to_csv(OUTPUT_DIR / "financial_freshness_stale_2025q4.csv", index=False)

    lines = [
        f"as_of_date: {AS_OF_DATE.isoformat()}",
        f"expected_latest_period_end: {EXPECTED_LATEST_PERIOD_END.isoformat()}",
        "",
        f"total_symbols: {len(audit)}",
        f"stale_vs_2025q4_any: {int(audit['period_stale_vs_2025q4'].sum())}",
        f"stale_vs_2025q4_annual: {int(audit['annual_stale_vs_2025q4'].sum())}",
        "",
        "Stale annual symbols:",
    ]
    for row in stale.to_dict(orient="records"):
        lines.append(
            f"- {row['symbol']}: latest={row['latest_period_end']}, "
            f"latest_annual={row['latest_annual_period_end']}, "
            f"announcement={row['latest_announcement_date']}, "
            f"status={row['load_status']}/{row['load_reason']}"
        )
    (OUTPUT_DIR / "financial_freshness_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _quarter_lag_from_expected(period_end: date | None) -> int | None:
    if period_end is None or pd.isna(period_end):
        return None
    return ((EXPECTED_LATEST_PERIOD_END.year - period_end.year) * 4) + (
        ((EXPECTED_LATEST_PERIOD_END.month - 1) // 3) - ((period_end.month - 1) // 3)
    )


if __name__ == "__main__":
    main()

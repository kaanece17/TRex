from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class AnalystYFinanceLoadResult:
    consensus_history: pd.DataFrame
    snapshot_history: pd.DataFrame
    failures: pd.DataFrame


class AnalystYFinanceLoader:
    def load(self, symbols: list[str]) -> AnalystYFinanceLoadResult:
        consensus_rows: list[dict[str, object]] = []
        snapshot_rows: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        as_of_datetime = datetime.now(UTC)
        as_of_date = as_of_datetime.date()

        for symbol in symbols:
            symbol_upper = str(symbol).upper()
            try:
                ticker = yf.Ticker(symbol_upper)
                consensus_rows.extend(self._build_consensus_history(symbol_upper, ticker))
                snapshot_rows.extend(self._build_snapshot_history(symbol_upper, ticker, as_of_datetime, as_of_date))
            except Exception as error:
                failures.append({"symbol": symbol_upper, "reason": "analyst_yfinance_failed", "detail": str(error)})

        return AnalystYFinanceLoadResult(
            consensus_history=pd.DataFrame(consensus_rows),
            snapshot_history=pd.DataFrame(snapshot_rows),
            failures=pd.DataFrame(failures),
        )

    def _build_consensus_history(self, symbol: str, ticker: yf.Ticker) -> list[dict[str, object]]:
        history = ticker.earnings_history
        if history is None or history.empty:
            return []
        rows: list[dict[str, object]] = []
        working = history.reset_index().rename(columns={"quarter": "period_end"})
        for row in working.to_dict(orient="records"):
            period_end = pd.to_datetime(row.get("period_end"), errors="coerce")
            if pd.isna(period_end):
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "period_end": period_end.date(),
                    "eps_actual": _as_float(row.get("epsActual")),
                    "eps_estimate": _as_float(row.get("epsEstimate")),
                    "eps_difference": _as_float(row.get("epsDifference")),
                    "eps_surprise_percent": _as_float(row.get("surprisePercent")),
                }
            )
        return rows

    def _build_snapshot_history(
        self,
        symbol: str,
        ticker: yf.Ticker,
        as_of_datetime: datetime,
        as_of_date,
    ) -> list[dict[str, object]]:
        earnings_estimate = ticker.earnings_estimate
        revenue_estimate = ticker.revenue_estimate
        eps_revisions = ticker.eps_revisions
        recommendations = ticker.recommendations

        rec_map: dict[str, dict[str, object]] = {}
        if recommendations is not None and not recommendations.empty:
            for row in recommendations.to_dict(orient="records"):
                period = str(row.get("period") or "")
                if not period:
                    continue
                rec_map[period] = row

        period_index: set[str] = set()
        for df in [earnings_estimate, revenue_estimate, eps_revisions]:
            if df is not None and not df.empty:
                period_index.update([str(idx) for idx in df.index.tolist()])
        period_index.update(rec_map.keys())

        rows: list[dict[str, object]] = []
        for period in sorted(period_index):
            ee = _safe_row(earnings_estimate, period)
            re = _safe_row(revenue_estimate, period)
            rev = _safe_row(eps_revisions, period)
            rec = rec_map.get(period, {})
            rows.append(
                {
                    "symbol": symbol,
                    "as_of_datetime": as_of_datetime,
                    "as_of_date": as_of_date,
                    "period": period,
                    "earnings_estimate_avg": _as_float(ee.get("avg")),
                    "earnings_estimate_low": _as_float(ee.get("low")),
                    "earnings_estimate_high": _as_float(ee.get("high")),
                    "earnings_estimate_analysts": _as_float(ee.get("numberOfAnalysts")),
                    "revenue_estimate_avg": _as_float(re.get("avg")),
                    "revenue_estimate_low": _as_float(re.get("low")),
                    "revenue_estimate_high": _as_float(re.get("high")),
                    "revenue_estimate_analysts": _as_float(re.get("numberOfAnalysts")),
                    "up_last7days": _as_float(rev.get("upLast7days")),
                    "up_last30days": _as_float(rev.get("upLast30days")),
                    "down_last7days": _as_float(rev.get("downLast7Days")),
                    "down_last30days": _as_float(rev.get("downLast30days")),
                    "strong_buy": _as_float(rec.get("strongBuy")),
                    "buy": _as_float(rec.get("buy")),
                    "hold": _as_float(rec.get("hold")),
                    "sell": _as_float(rec.get("sell")),
                    "strong_sell": _as_float(rec.get("strongSell")),
                }
            )
        return rows


def _safe_row(df: pd.DataFrame | None, period: str) -> dict[str, object]:
    if df is None or df.empty or period not in df.index:
        return {}
    return df.loc[period].to_dict()


def _as_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

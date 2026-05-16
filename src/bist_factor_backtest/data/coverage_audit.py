from __future__ import annotations

from datetime import date

import pandas as pd


def build_alternative_coverage_audit(
    symbols: list[str],
    statements: pd.DataFrame,
    registry: pd.DataFrame,
    aliases: pd.DataFrame,
    audit_start_date: date,
) -> pd.DataFrame:
    normalized_symbols = [str(symbol).upper() for symbol in symbols]
    statement_data = _normalize_statements(statements)
    registry_data = _normalize_registry(registry)
    alias_data = _normalize_aliases(aliases)
    rows = []
    for symbol in normalized_symbols:
        symbol_statements = statement_data[statement_data["symbol"] == symbol].copy()
        total_statement_count = len(symbol_statements)
        statements_since_start = symbol_statements[symbol_statements["period_end"] >= audit_start_date]
        statement_count_since_start = len(statements_since_start)
        announcement_count = int(symbol_statements["announcement_date"].notna().sum()) if not symbol_statements.empty else 0
        shares_count = (
            int((symbol_statements["shares_outstanding"].notna() & (symbol_statements["shares_outstanding"] > 0)).sum())
            if not symbol_statements.empty
            else 0
        )
        first_statement_period_end = _series_min_date(symbol_statements.get("period_end"))
        first_statement_period_end_since_start = _series_min_date(statements_since_start.get("period_end"))
        first_announcement_date = _series_min_date(symbol_statements.get("announcement_date"))
        first_shares_period_end = _series_min_date(
            symbol_statements.loc[
                symbol_statements["shares_outstanding"].notna() & (symbol_statements["shares_outstanding"] > 0),
                "period_end",
            ]
            if not symbol_statements.empty
            else pd.Series(dtype="object")
        )

        registry_row = registry_data[registry_data["symbol"] == symbol].head(1)
        registry_present = not registry_row.empty
        registry_active = _registry_active_value(registry_row)
        registry_has_url = _registry_has_url(registry_row)
        alias_rows = alias_data[(alias_data["canonical_symbol"] == symbol) | (alias_data["symbol"] == symbol)]
        alias_mapping_present = not alias_rows.empty
        alias_symbol_count = int(alias_rows["symbol"].astype(str).nunique()) if not alias_rows.empty else 0

        rows.append(
            {
                "symbol": symbol,
                "total_statement_count": total_statement_count,
                "statement_count_since_start": statement_count_since_start,
                "first_statement_period_end": first_statement_period_end,
                "first_statement_period_end_since_start": first_statement_period_end_since_start,
                "first_announcement_date": first_announcement_date,
                "first_shares_period_end": first_shares_period_end,
                "announcement_count": announcement_count,
                "shares_count": shares_count,
                "announcement_coverage_ratio": _ratio(announcement_count, total_statement_count),
                "shares_coverage_ratio": _ratio(shares_count, total_statement_count),
                "missing_announcement_count": total_statement_count - announcement_count,
                "missing_shares_count": total_statement_count - shares_count,
                "registry_present": registry_present,
                "registry_active": registry_active,
                "registry_has_url": registry_has_url,
                "registry_missing": not registry_present,
                "registry_url_missing": registry_present and not registry_has_url,
                "alias_mapping_present": alias_mapping_present,
                "alias_symbol_count": alias_symbol_count,
                "coverage_class": _coverage_class(
                    total_statement_count=total_statement_count,
                    registry_present=registry_present,
                    registry_has_url=registry_has_url,
                    announcement_count=announcement_count,
                    shares_count=shares_count,
                ),
                "needs_manual_mapping": _needs_manual_mapping(
                    total_statement_count=total_statement_count,
                    registry_present=registry_present,
                    registry_has_url=registry_has_url,
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_alternative_coverage(audit: pd.DataFrame) -> pd.DataFrame:
    if audit.empty:
        return pd.DataFrame(columns=["metric", "value"])
    metrics = [
        ("symbol_count", len(audit)),
        ("fully_covered_count", int((audit["coverage_class"] == "fully_covered").sum())),
        ("partial_history_count", int((audit["coverage_class"] == "partial_history").sum())),
        ("needs_manual_mapping_count", int((audit["coverage_class"] == "needs_manual_mapping").sum())),
        ("registry_missing_count", int(audit["registry_missing"].sum())),
        ("registry_url_missing_count", int(audit["registry_url_missing"].sum())),
        ("alias_mapping_present_count", int(audit["alias_mapping_present"].sum())),
        ("statement_covered_count", int((audit["total_statement_count"] > 0).sum())),
        ("announcement_gap_count", int((audit["missing_announcement_count"] > 0).sum())),
        ("shares_gap_count", int((audit["missing_shares_count"] > 0).sum())),
    ]
    return pd.DataFrame(metrics, columns=["metric", "value"])


def build_alternative_fill_queue(audit: pd.DataFrame) -> pd.DataFrame:
    if audit.empty:
        return pd.DataFrame(
            columns=[
                "priority",
                "queue_reason",
                "symbol",
                "coverage_class",
                "registry_missing",
                "registry_url_missing",
                "total_statement_count",
                "missing_announcement_count",
                "missing_shares_count",
                "needs_manual_mapping",
            ]
        )
    queue = audit.copy()
    queue["queue_reason"] = queue.apply(_queue_reason, axis=1)
    queue["priority"] = queue["queue_reason"].map(
        {
            "missing_registry_mapping": 1,
            "missing_registry_url": 2,
            "missing_statement_coverage": 3,
            "missing_announcement_dates": 4,
            "missing_shares_outstanding": 5,
            "needs_review": 6,
        }
    )
    queue = queue[queue["queue_reason"].notna()].copy()
    if queue.empty:
        return pd.DataFrame(
            columns=[
                "priority",
                "queue_reason",
                "symbol",
                "coverage_class",
                "registry_missing",
                "registry_url_missing",
                "total_statement_count",
                "missing_announcement_count",
                "missing_shares_count",
                "needs_manual_mapping",
            ]
        )
    queue = queue.sort_values(
        [
            "priority",
            "needs_manual_mapping",
            "missing_announcement_count",
            "missing_shares_count",
            "symbol",
        ],
        ascending=[True, False, False, False, True],
    )
    return queue[
        [
            "priority",
            "queue_reason",
            "symbol",
            "coverage_class",
            "registry_missing",
            "registry_url_missing",
            "total_statement_count",
            "missing_announcement_count",
            "missing_shares_count",
            "needs_manual_mapping",
        ]
    ].reset_index(drop=True)


def _normalize_statements(statements: pd.DataFrame) -> pd.DataFrame:
    if statements.empty:
        return pd.DataFrame(columns=["symbol", "period_end", "announcement_date", "shares_outstanding"])
    result = statements.copy()
    result["symbol"] = result["symbol"].astype(str).str.upper()
    result["period_end"] = pd.to_datetime(result["period_end"], errors="coerce").dt.date
    result["announcement_date"] = pd.to_datetime(result["announcement_date"], errors="coerce").dt.date
    result["shares_outstanding"] = pd.to_numeric(result["shares_outstanding"], errors="coerce")
    return result


def _normalize_registry(registry: pd.DataFrame) -> pd.DataFrame:
    if registry.empty:
        return pd.DataFrame(columns=["symbol", "investing_slug", "earnings_url", "is_active"])
    result = registry.copy()
    result["symbol"] = result["symbol"].astype(str).str.upper()
    for column in ["investing_slug", "earnings_url", "is_active"]:
        if column not in result.columns:
            result[column] = None
    return result


def _normalize_aliases(aliases: pd.DataFrame) -> pd.DataFrame:
    if aliases.empty:
        return pd.DataFrame(columns=["canonical_symbol", "symbol"])
    result = aliases.copy()
    result["canonical_symbol"] = result["canonical_symbol"].astype(str).str.upper()
    result["symbol"] = result["symbol"].astype(str).str.upper()
    return result


def _series_min_date(values: pd.Series | None):
    if values is None or values.empty:
        return None
    cleaned = pd.to_datetime(values, errors="coerce").dropna()
    if cleaned.empty:
        return None
    return cleaned.min().date()


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator / denominator)


def _registry_active_value(registry_row: pd.DataFrame):
    if registry_row.empty:
        return None
    value = registry_row.iloc[0].get("is_active")
    if pd.isna(value):
        return None
    return bool(value)


def _registry_has_url(registry_row: pd.DataFrame) -> bool:
    if registry_row.empty:
        return False
    row = registry_row.iloc[0]
    return bool(
        _has_text(row.get("earnings_url"))
        or _has_text(row.get("investing_slug"))
    )


def _has_text(value) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip() != ""


def _coverage_class(
    total_statement_count: int,
    registry_present: bool,
    registry_has_url: bool,
    announcement_count: int,
    shares_count: int,
) -> str:
    if total_statement_count <= 0:
        return "needs_manual_mapping"
    if registry_present and registry_has_url and announcement_count == total_statement_count and shares_count == total_statement_count:
        return "fully_covered"
    return "partial_history"


def _needs_manual_mapping(
    total_statement_count: int,
    registry_present: bool,
    registry_has_url: bool,
) -> bool:
    return total_statement_count <= 0 or not registry_present or not registry_has_url


def _queue_reason(row: pd.Series) -> str | None:
    if bool(row.get("registry_missing", False)):
        return "missing_registry_mapping"
    if bool(row.get("registry_url_missing", False)):
        return "missing_registry_url"
    if int(row.get("total_statement_count", 0)) <= 0:
        return "missing_statement_coverage"
    if int(row.get("missing_announcement_count", 0)) > 0:
        return "missing_announcement_dates"
    if int(row.get("missing_shares_count", 0)) > 0:
        return "missing_shares_outstanding"
    if bool(row.get("needs_manual_mapping", False)):
        return "needs_review"
    return None

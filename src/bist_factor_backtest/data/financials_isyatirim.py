from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from bs4 import BeautifulSoup
import pandas as pd
import requests


ITEM_ALIASES = {
    "net_income": [
        "net_income",
        "net_kar",
        "net_kâr",
        "net kâr",
        "net kar",
        "dönem net kar/zararı",
        "donem net kar/zarari",
        "dönem karı (zararı)",
        "donem kari (zarari)",
        "ana ortaklık payları",
    ],
    "equity": ["equity", "ozkaynaklar", "özkaynaklar"],
    "operating_profit": [
        "operating_profit",
        "faaliyet_kari",
        "faaliyet_karı",
        "esas_faaliyet_kari",
        "esas_faaliyet_karı",
        "esas faaliyet karı",
        "faaliyet karı (zararı)",
        "faaliyet kari (zarari)",
        "net faaliyet kar/zararı",
        "net faaliyet kar/zarari",
        "finansman gideri öncesi faaliyet karı/zararı",
        "finansman gideri oncesi faaliyet kari/zarari",
    ],
    "cash": ["cash", "nakit", "nakit ve nakit benzerleri"],
    "total_debt": ["total_debt", "toplam_borc", "toplam_borc", "finansal borclar", "finansal borçlar"],
    "shares_outstanding": ["shares_outstanding", "odenmis_sermaye", "ödenmiş sermaye", "odenmis sermaye"],
}

REQUIRED_ITEMS = ("net_income", "equity", "operating_profit")
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
MALI_TABLO_ENDPOINT = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"


@dataclass(frozen=True)
class IsYatirimLoadResult:
    statements: pd.DataFrame
    items: pd.DataFrame
    failures: pd.DataFrame


class IsYatirimFinancialLoader:
    def __init__(self, request_timeout_seconds: int = 20):
        self.request_timeout_seconds = request_timeout_seconds

    def fetch_records(self, symbol: str) -> list[dict]:
        url = f"https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/sirket-karti.aspx?hisse={symbol.upper()}"
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=self.request_timeout_seconds)
        response.raise_for_status()
        endpoint_records = self._fetch_endpoint_records(symbol=symbol, html=response.text)
        if endpoint_records:
            return endpoint_records
        return self.parse_html(symbol=symbol, html=response.text, source_url=url)

    def _fetch_endpoint_records(self, symbol: str, html: str) -> list[dict]:
        metadata = _extract_endpoint_metadata(html)
        if metadata is None:
            return []

        period_values = metadata["period_values"]
        exchange = metadata["exchange"]
        financial_group = metadata["financial_group"]
        records: dict[date, dict] = {}

        for period_batch in _chunk_period_values(period_values, size=4):
            params = {
                "companyCode": symbol.upper(),
                "exchange": exchange,
                "financialGroup": financial_group,
            }
            for index, period_value in enumerate(period_batch, start=1):
                year, period = period_value.split("/", maxsplit=1)
                params[f"year{index}"] = year
                params[f"period{index}"] = period

            response = requests.get(
                MALI_TABLO_ENDPOINT,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok") or not payload.get("value"):
                continue

            for row in payload["value"]:
                row_name = row.get("itemDescTr") or row.get("itemDescEng") or ""
                item_code = _resolve_item_code(str(row_name))
                if item_code is None:
                    continue
                for value_index, period_value in enumerate(period_batch, start=1):
                    period_end = _parse_period_end(period_value)
                    if period_end is None:
                        continue
                    value = _coerce_float(row.get(f"value{value_index}"))
                    if value is None:
                        continue
                    record = records.setdefault(
                        period_end,
                        {
                            "symbol": symbol.upper(),
                            "period_end": period_end,
                            "source_url": MALI_TABLO_ENDPOINT,
                            "shares_source_url": MALI_TABLO_ENDPOINT,
                        },
                    )
                    if item_code == "total_debt":
                        record[item_code] = (record.get(item_code) or 0.0) + value
                    else:
                        record[item_code] = value

        return [records[period_end] for period_end in sorted(records)]

    def parse_html(self, symbol: str, html: str, source_url: str) -> list[dict]:
        records: dict[date, dict] = {}

        detailed_rows = _extract_detailed_financial_rows(html)
        if detailed_rows:
            for row_name, period_end, value in detailed_rows:
                item_code = _resolve_item_code(row_name)
                if item_code is None:
                    continue
                record = records.setdefault(
                    period_end,
                    {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "source_url": source_url,
                        "shares_source_url": source_url,
                    },
                )
                if item_code == "total_debt":
                    record[item_code] = (record.get(item_code) or 0.0) + value
                else:
                    record[item_code] = value

        if records:
            return [records[period_end] for period_end in sorted(records)]

        tables = _read_html_tables(html)
        for table in tables:
            for row_name, period_end, value in _iter_financial_table_values(table):
                item_code = _resolve_item_code(row_name)
                if item_code is None:
                    continue
                record = records.setdefault(
                    period_end,
                    {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "source_url": source_url,
                        "shares_source_url": source_url,
                    },
                )
                record[item_code] = value
        return [records[period_end] for period_end in sorted(records)]

    def build_from_records(self, symbol: str, records: list[dict]) -> IsYatirimLoadResult:
        statement_rows: list[dict] = []
        item_rows: list[dict] = []
        failures: list[dict] = []
        symbol_upper = symbol.upper()

        for record in records:
            period_end = _coerce_date(record.get("period_end") or record.get("donem_sonu") or record.get("Dönem Sonu"))
            if period_end is None:
                failures.append(
                    {
                        "symbol": symbol_upper,
                        "reason": "missing_period_end",
                        "detail": str(record),
                    }
                )
                continue

            item_values = {item_code: _extract_value(record, item_code) for item_code in ITEM_ALIASES}
            if any(item_values[item_code] is None for item_code in REQUIRED_ITEMS):
                failures.append(
                    {
                        "symbol": symbol_upper,
                        "reason": "missing_core_items",
                        "detail": f"{period_end.isoformat()}",
                    }
                )
                continue

            statement_id = str(record.get("statement_id") or f"ISYATIRIM-{symbol_upper}-{period_end:%Y%m%d}")
            announcement_datetime = _coerce_datetime(record.get("announcement_datetime"))
            announcement_date = _coerce_date(record.get("announcement_date")) or (
                announcement_datetime.date() if announcement_datetime is not None else None
            )
            statement_rows.append(
                {
                    "statement_id": statement_id,
                    "symbol": symbol_upper,
                    "period_end": period_end,
                    "fiscal_year": _coerce_int(record.get("fiscal_year")) or period_end.year,
                    "fiscal_period": str(record.get("fiscal_period") or _infer_fiscal_period(period_end)),
                    "statement_type": str(record.get("statement_type") or "financial_statement"),
                    "announcement_datetime": announcement_datetime,
                    "announcement_date": announcement_date,
                    "currency": str(record.get("currency") or "TRY"),
                    "is_consolidated": _coerce_bool(record.get("is_consolidated"), default=True),
                    "is_revised": _coerce_bool(record.get("is_revised"), default=False),
                    "source_url": record.get("source_url"),
                    "raw_hash": record.get("raw_hash"),
                    "created_at": _coerce_datetime(record.get("created_at")) or datetime.now(UTC),
                    "shares_outstanding": item_values["shares_outstanding"],
                    "shares_announcement_datetime": _coerce_datetime(record.get("shares_announcement_datetime"))
                    or announcement_datetime,
                    "shares_source_url": record.get("shares_source_url") or record.get("source_url"),
                }
            )
            for item_code in ("net_income", "equity", "operating_profit", "cash", "total_debt"):
                value = item_values[item_code]
                if value is None:
                    continue
                item_rows.append(
                    {
                        "statement_id": statement_id,
                        "symbol": symbol_upper,
                        "item_code": item_code,
                        "item_name": item_code,
                        "value": value,
                    }
                )

        return IsYatirimLoadResult(
            statements=pd.DataFrame(statement_rows),
            items=pd.DataFrame(item_rows),
            failures=pd.DataFrame(failures),
        )


def _extract_value(record: dict, item_code: str) -> float | None:
    for alias in ITEM_ALIASES[item_code]:
        for key, value in record.items():
            if _normalize_key(str(key)) == _normalize_key(alias):
                return _coerce_float(value)
    return None


def _normalize_key(value: str) -> str:
    normalized = value.strip().lower()
    replacements = {
        "ı": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "â": "a",
        "î": "i",
        "û": "u",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized.replace("_", " ").replace("-", " ")


def _iter_financial_table_values(table: pd.DataFrame):
    normalized = table.copy()
    normalized.columns = [_flatten_column_name(column) for column in normalized.columns]
    if normalized.empty or len(normalized.columns) < 2:
        return
    label_column = normalized.columns[0]
    period_columns = [column for column in normalized.columns[1:] if _parse_period_end(column) is not None]
    if not period_columns:
        return
    for _, row in normalized.iterrows():
        row_name = str(row[label_column]).strip()
        if row_name == "" or row_name.lower() == "nan":
            continue
        for period_column in period_columns:
            value = _coerce_float(row[period_column])
            if value is None:
                continue
            yield row_name, _parse_period_end(period_column), value


def _flatten_column_name(column) -> str:
    if isinstance(column, tuple):
        return " ".join(str(part).strip() for part in column if str(part).strip() and str(part) != "nan")
    return str(column).strip()


def _resolve_item_code(row_name: str) -> str | None:
    normalized_row_name = _normalize_key(row_name)
    for item_code, aliases in ITEM_ALIASES.items():
        for alias in aliases:
            if normalized_row_name == _normalize_key(alias):
                return item_code
    return None


def _parse_period_end(value: str) -> date | None:
    parsed = _parse_datetime_like(value)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _read_html_tables(html: str) -> list[pd.DataFrame]:
    soup = BeautifulSoup(html, "html.parser")
    tables: list[pd.DataFrame] = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            rows.append([cell.get_text(" ", strip=True) for cell in cells])
        if len(rows) < 2:
            continue
        header = rows[0]
        body = [row for row in rows[1:] if row]
        if not body:
            continue
        width = max(len(header), max(len(row) for row in body))
        header = header + [f"column_{index}" for index in range(len(header), width)]
        normalized_body = [row + [None] * (width - len(row)) for row in body]
        tables.append(pd.DataFrame(normalized_body, columns=header))
    return tables


def _extract_detailed_financial_rows(html: str) -> list[tuple[str, date, float]]:
    soup = BeautifulSoup(html, "html.parser")
    period_ids = (
        "ddlMaliTabloDonem1",
        "ddlMaliTabloDonem2",
        "ddlMaliTabloDonem3",
        "ddlMaliTabloDonem4",
        "ddlMaliTabloFirst",
        "ddlMaliTabloSecond",
    )
    period_ends: list[date] = []
    for element_id in period_ids:
        select = soup.find("select", id=element_id)
        if select is None:
            continue
        selected = select.find("option", selected=True) or select.find("option")
        if selected is None:
            continue
        period_end = _parse_period_end(selected.get("value") or selected.get_text(" ", strip=True))
        if period_end is not None:
            period_ends.append(period_end)
    if not period_ends:
        return []

    body = soup.find("tbody", id="tbodyMTablo")
    if body is None:
        return []

    rows: list[tuple[str, date, float]] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        row_name = cells[0].get_text(" ", strip=True)
        if not row_name or row_name.startswith("("):
            continue
        for period_end, cell in zip(period_ends, cells[1:], strict=False):
            value = _coerce_float(cell.get_text(" ", strip=True))
            if value is None:
                continue
            rows.append((row_name, period_end, value))
    return rows


def _extract_endpoint_metadata(html: str) -> dict[str, str | list[str]] | None:
    soup = BeautifulSoup(html, "html.parser")
    period_select = soup.find("select", id="ddlMaliTabloDonem1")
    exchange_select = soup.find("select", id="ddlMaliTabloExchange")
    group_select = soup.find("select", id="ddlMaliTabloGroup")
    if period_select is None or exchange_select is None or group_select is None:
        return None

    period_values = [
        option.get("value", "").strip()
        for option in period_select.find_all("option")
        if option.get("value", "").strip()
    ]
    if not period_values:
        return None

    exchange_option = exchange_select.find("option", selected=True) or exchange_select.find("option")
    group_option = group_select.find("option", selected=True) or group_select.find("option")
    if exchange_option is None or group_option is None:
        return None

    return {
        "period_values": period_values,
        "exchange": exchange_option.get("value", "").strip(),
        "financial_group": group_option.get("value", "").strip(),
    }


def _chunk_period_values(period_values: list[str], size: int) -> list[list[str]]:
    return [period_values[index : index + size] for index in range(0, len(period_values), size)]


def _coerce_date(value) -> date | None:
    if _is_missing(value):
        return None
    parsed = _parse_datetime_like(value)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _coerce_datetime(value) -> datetime | None:
    if _is_missing(value):
        return None
    parsed = _parse_datetime_like(value, utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _coerce_float(value) -> float | None:
    if _is_missing(value):
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace(".", "").replace(",", ".")
        if cleaned == "":
            return None
        value = cleaned
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def _coerce_int(value) -> int | None:
    number = _coerce_float(value)
    return None if number is None else int(number)


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "evet"}


def _infer_fiscal_period(period_end: date) -> str:
    quarter = ((period_end.month - 1) // 3) + 1
    return f"Q{quarter}"


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    return bool(pd.isna(value))


def _parse_datetime_like(value, utc: bool = False):
    text = str(value).strip()
    if "." in text and "-" not in text:
        return pd.to_datetime(text, errors="coerce", dayfirst=True, utc=utc)
    return pd.to_datetime(value, errors="coerce", utc=utc)

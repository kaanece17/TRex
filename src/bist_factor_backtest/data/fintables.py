from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import re
import time
import unicodedata

from bs4 import BeautifulSoup
import pandas as pd

try:
    from curl_cffi import requests as curl_requests
except Exception:  # pragma: no cover
    curl_requests = None


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
SCREENER_URL = (
    "https://api.fintables.com/screener/"
    "?period=null&filter=published_at||!period||!kapanis||!gunluk_getiri||"
    "!piyasa_degeri||!net_kar||!yillik_net_kar_degisimi||!fk||!pddd||"
)
COMPANY_FINANCIALS_URL = "https://fintables.com/sirketler/{symbol}/finansal-tablolar"
BALANCE_SHEET_URL = "https://fintables.com/sirketler/{symbol}/finansal-tablolar/bilanco"
INCOME_STATEMENT_URL = "https://fintables.com/sirketler/{symbol}/finansal-tablolar/gelir-tablosu"

ITEM_ALIASES = {
    "shares_outstanding": (
        "odenmis sermaye",
        "cikarilmis sermaye",
    ),
    "equity": (
        "toplam ozkaynaklar",
        "ana ortakliga ait ozkaynaklar",
        "ozkaynaklar",
    ),
    "cash": (
        "nakit ve nakit benzerleri",
    ),
    "net_income": (
        "donem kari zarari",
        "surdurulen faaliyetler donem kari zarari",
        "net donem kari zarari",
    ),
    "operating_profit": (
        "finansman geliri gideri oncesi faaliyet kari zarari",
        "finansman gideri oncesi faaliyet kari zarari",
        "faaliyet kari zarari",
    ),
}
DEBT_COMPONENT_ALIASES = (
    "kisa vadeli borclanmalar",
    "uzun vadeli borclanmalarin kisa vadeli kisimlari",
    "uzun vadeli borclanmalar",
    "kiralama islemlerinden kaynaklanan yukumlulukler",
    "finansal borclar",
)
SCALE_THOUSANDS = 1_000.0


@dataclass(frozen=True)
class FintablesLoadResult:
    statements: pd.DataFrame
    items: pd.DataFrame
    failures: pd.DataFrame


class FintablesClient:
    def __init__(
        self,
        request_timeout_seconds: int = 30,
        min_request_interval_seconds: float = 0.2,
    ):
        self.request_timeout_seconds = request_timeout_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_monotonic = 0.0

    def fetch_latest_screener_rows(self, symbols: list[str] | None = None) -> pd.DataFrame:
        payload = self._get_json(SCREENER_URL)
        rows = payload.get("data") or []
        result: list[dict] = []
        target = {symbol.upper() for symbol in symbols} if symbols else None
        for row in rows:
            symbol = str(row.get("code") or "").upper()
            if not symbol:
                continue
            if target is not None and symbol not in target:
                continue
            period_end = _parse_period_end(row.get("period"))
            if period_end is None:
                continue
            published_at = _coerce_datetime(row.get("published_at"))
            result.append(
                {
                    "symbol": symbol,
                    "period_end": period_end,
                    "announcement_datetime": published_at,
                    "announcement_date": published_at.date() if published_at is not None else None,
                    "announcement_source_url": SCREENER_URL,
                    "announcement_source_system": "fintables_son_bilancolar",
                    "net_income": _coerce_float(row.get("net_kar")),
                    "published_at_raw": row.get("published_at"),
                }
            )
        return pd.DataFrame(result)

    def fetch_statement_records(self, symbol: str) -> list[dict]:
        symbol_upper = symbol.upper()
        balance_html = self._get_text(BALANCE_SHEET_URL.format(symbol=symbol_upper))
        income_html = self._get_text(INCOME_STATEMENT_URL.format(symbol=symbol_upper))
        balance_values = _extract_statement_values_from_html(balance_html)
        income_values = _extract_statement_values_from_html(income_html)
        periods = sorted(set(balance_values.keys()) | set(income_values.keys()))
        source_url = COMPANY_FINANCIALS_URL.format(symbol=symbol_upper)
        records: list[dict] = []
        for period_end in periods:
            record = {
                "symbol": symbol_upper,
                "period_end": period_end,
                "fiscal_year": period_end.year,
                "fiscal_period": _infer_fiscal_period(period_end),
                "statement_type": "financial_statement",
                "currency": "TRY",
                "is_consolidated": True,
                "is_revised": False,
                "source_url": source_url,
                "source_system": "fintables",
                "shares_source_url": source_url,
            }
            record.update(balance_values.get(period_end, {}))
            record.update(income_values.get(period_end, {}))
            records.append(record)
        return records

    def _respect_request_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self.min_request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get_json(self, url: str) -> dict:
        if curl_requests is None:  # pragma: no cover
            raise RuntimeError("curl_cffi is required for Fintables access")
        self._respect_request_interval()
        response = curl_requests.get(
            url,
            headers=REQUEST_HEADERS,
            impersonate="chrome124",
            timeout=self.request_timeout_seconds,
        )
        self._last_request_monotonic = time.monotonic()
        response.raise_for_status()
        return response.json()

    def _get_text(self, url: str) -> str:
        if curl_requests is None:  # pragma: no cover
            raise RuntimeError("curl_cffi is required for Fintables access")
        self._respect_request_interval()
        response = curl_requests.get(
            url,
            headers=REQUEST_HEADERS,
            impersonate="chrome124",
            timeout=self.request_timeout_seconds,
        )
        self._last_request_monotonic = time.monotonic()
        response.raise_for_status()
        return response.text


class FintablesFinancialLoader:
    def build_from_records(self, symbol: str, records: list[dict]) -> FintablesLoadResult:
        statement_rows: list[dict] = []
        item_rows: list[dict] = []
        failures: list[dict] = []
        symbol_upper = symbol.upper()
        for record in records:
            period_end = _coerce_date(record.get("period_end"))
            if period_end is None:
                failures.append({"symbol": symbol_upper, "reason": "missing_period_end", "detail": str(record)})
                continue
            values = {key: _coerce_float(record.get(key)) for key in ("shares_outstanding", "equity", "cash", "net_income", "operating_profit", "total_debt")}
            missing = [key for key in ("equity", "net_income", "operating_profit") if values.get(key) is None]
            if missing:
                failures.append(
                    {
                        "symbol": symbol_upper,
                        "reason": "missing_core_items",
                        "detail": f"{period_end.isoformat()} missing={','.join(missing)}",
                    }
                )
                continue
            statement_id = str(record.get("statement_id") or f"FINTABLES-{symbol_upper}-{period_end:%Y%m%d}")
            announcement_datetime = _coerce_datetime(record.get("announcement_datetime"))
            announcement_date = _coerce_date(record.get("announcement_date")) or (
                announcement_datetime.date() if announcement_datetime is not None else None
            )
            statement_rows.append(
                {
                    "statement_id": statement_id,
                    "symbol": symbol_upper,
                    "period_end": period_end,
                    "fiscal_year": int(record.get("fiscal_year") or period_end.year),
                    "fiscal_period": str(record.get("fiscal_period") or _infer_fiscal_period(period_end)),
                    "statement_type": str(record.get("statement_type") or "financial_statement"),
                    "announcement_datetime": announcement_datetime,
                    "announcement_date": announcement_date,
                    "currency": str(record.get("currency") or "TRY"),
                    "is_consolidated": bool(record.get("is_consolidated", True)),
                    "is_revised": bool(record.get("is_revised", False)),
                    "source_url": record.get("source_url"),
                    "source_system": str(record.get("source_system") or "fintables"),
                    "announcement_source_url": record.get("announcement_source_url"),
                    "announcement_source_system": record.get("announcement_source_system"),
                    "raw_hash": record.get("raw_hash"),
                    "created_at": _coerce_datetime(record.get("created_at")) or datetime.now(UTC),
                    "shares_outstanding": values.get("shares_outstanding"),
                    "shares_announcement_datetime": announcement_datetime,
                    "shares_source_url": record.get("shares_source_url") or record.get("source_url"),
                }
            )
            for item_code in ("net_income", "equity", "operating_profit", "cash", "total_debt"):
                value = values.get(item_code)
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
        return FintablesLoadResult(
            statements=pd.DataFrame(statement_rows),
            items=pd.DataFrame(item_rows),
            failures=pd.DataFrame(failures),
        )


def _extract_statement_values_from_html(html: str) -> dict[date, dict]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return {}
    header_cells = [
        cell.get_text(" ", strip=True)
        for cell in tables[0].find_all("tr")[0].find_all(["th", "td"])
    ]
    periods = [_parse_period_end(text) for text in header_cells[1:]]
    periods = [period for period in periods if period is not None]
    if not periods:
        return {}
    values_by_period: dict[date, dict] = {period: {} for period in periods}
    for tr in tables[1].find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        if len(cells) < 2:
            continue
        label = _normalize_text(cells[0])
        if not label:
            continue
        row_values = cells[1 : 1 + len(periods)]
        if any(alias == label for alias in (_normalize_text(item) for item in ITEM_ALIASES["shares_outstanding"])):
            _assign_period_values(values_by_period, periods, row_values, "shares_outstanding")
            continue
        if any(alias == label for alias in (_normalize_text(item) for item in ITEM_ALIASES["equity"])):
            _assign_period_values(values_by_period, periods, row_values, "equity")
            continue
        if any(alias == label for alias in (_normalize_text(item) for item in ITEM_ALIASES["cash"])):
            _assign_period_values(values_by_period, periods, row_values, "cash")
            continue
        if any(alias == label for alias in (_normalize_text(item) for item in ITEM_ALIASES["net_income"])):
            _assign_period_values(values_by_period, periods, row_values, "net_income")
            continue
        if any(alias == label for alias in (_normalize_text(item) for item in ITEM_ALIASES["operating_profit"])):
            _assign_period_values(values_by_period, periods, row_values, "operating_profit")
            continue
        if any(alias in label for alias in (_normalize_text(item) for item in DEBT_COMPONENT_ALIASES)):
            _assign_period_values(values_by_period, periods, row_values, "total_debt", additive=True)
    return values_by_period


def _assign_period_values(
    values_by_period: dict[date, dict],
    periods: list[date],
    row_values: list[str],
    field: str,
    additive: bool = False,
) -> None:
    for period_end, raw_value in zip(periods, row_values):
        numeric = _extract_table_numeric(raw_value)
        if numeric is None:
            continue
        scaled = numeric * SCALE_THOUSANDS
        if additive:
            values_by_period[period_end][field] = values_by_period[period_end].get(field, 0.0) + scaled
        else:
            values_by_period[period_end][field] = scaled


def _extract_table_numeric(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    matches = re.findall(r"-?[\d\.,]+", text)
    if not matches:
        return None
    return _coerce_float(matches[-1])


def _parse_period_end(value) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    match = re.search(r"(\d{4})\s*/\s*(3|6|9|12)", text)
    if match is None:
        return None
    return date(int(match.group(1)), int(match.group(2)), 1)


def _infer_fiscal_period(period_end: date) -> str:
    quarter = ((period_end.month - 1) // 3) + 1
    return f"Q{quarter}"


def _coerce_date(value) -> date | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _coerce_datetime(value):
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace("%", "").replace("\xa0", " ").replace("−", "-")
    text = re.sub(r"\s+", "", text)
    if "." in text and "," in text:
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    else:
        text = text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    replacements = {
        "ı": "i",
        "ö": "o",
        "ü": "u",
        "ş": "s",
        "ç": "c",
        "ğ": "g",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()

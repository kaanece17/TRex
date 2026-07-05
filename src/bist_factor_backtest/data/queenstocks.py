from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
import os
import re
import time
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd
import requests


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

LOGIN_URL = "https://queenstocks.com/queenstockspro/Uye/GirisYap"
SERVICE_KEY_URL = "https://queenstocks.com/queenstockspro/Uye/GetServisKey"
DEFAULT_RETURN_URL = "/QueenStocksPro"
FINNET_API_BASE = "https://internalapi.finnet.com.tr/FinnetPlusServis/queenStocks/tr"
HABER_API_BASE = "https://internalapi.finnet.com.tr/HaberExpertServisV2/queenStocks"
FINANCIAL_REPORT_PATTERN = re.compile(r"finansal rapor", re.IGNORECASE)
DATE_PATTERN = re.compile(r"(\d{2})[./](\d{2})[./](\d{4})")

LINE_ITEM_ALIASES = {
    "equity": (
        "toplam ozkaynaklar",
        "ozkaynaklar",
        "total equity",
        "equity",
    ),
    "net_income": (
        "net donem kari (zarari)",
        "net donem kari (zarari)",
        "donem kari (zarari)",
        "donem karı (zararı)",
        "profit (loss) attributable to owners of parent",
        "current period net profit or loss",
        "ana ortakliga ait net donem kari (zarari)",
    ),
    "operating_profit": (
        "esas faaliyet kari (zarari)",
        "esas faaliyet kari (zarari)",
        "faaliyet kari (zarari)",
        "faaliyet kari",
        "profit (loss) from operating activities",
        "profit (loss) before financing income (expense)",
        "finansman geliri (gideri) oncesi faaliyet kari (zarari)",
        "finansman gideri oncesi faaliyet kari (zarari)",
    ),
    "cash": (
        "nakit ve nakit benzerleri",
        "cash and cash equivalents",
    ),
    "shares_outstanding": (
        "odenmis sermaye",
        "cikarilmis sermaye",
        "issued capital",
        "paid-in capital",
    ),
}
DEBT_COMPONENT_ALIASES = (
    "kisa vadeli borclanmalar",
    "uzun vadeli borclanmalarin kisa vadeli kisimlari",
    "uzun vadeli borclanmalar",
    "kiralama islemlerinden kaynaklanan yukumlulukler",
    "finansal borclar",
    "financial liabilities",
    "short-term borrowings",
    "current portions of long-term borrowings",
    "long-term borrowings",
    "lease liabilities",
)
NORMALIZED_DEBT_COMPONENT_ALIASES: tuple[str, ...] = ()
REQUIRED_VALUES = ("equity", "net_income", "operating_profit")


@dataclass(frozen=True)
class QueenStocksLoadResult:
    statements: pd.DataFrame
    items: pd.DataFrame
    failures: pd.DataFrame


class QueenStocksClient:
    def __init__(
        self,
        username: str,
        password: str,
        request_timeout_seconds: int = 30,
        min_request_interval_seconds: float = 0.2,
    ):
        self.username = username
        self.password = password
        self.request_timeout_seconds = request_timeout_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)
        self._service_key: str | None = None
        self._last_request_monotonic = 0.0

    @classmethod
    def from_env(
        cls,
        username_env: str = "QUEENSTOCKS_USERNAME",
        password_env: str = "QUEENSTOCKS_PASSWORD",
        request_timeout_seconds: int = 30,
        min_request_interval_seconds: float = 0.2,
    ) -> "QueenStocksClient":
        username = os.environ.get(username_env)
        password = os.environ.get(password_env)
        if not username or not password:
            missing = [env for env, value in [(username_env, username), (password_env, password)] if not value]
            raise ValueError(f"missing QueenStocks credentials env vars: {', '.join(missing)}")
        return cls(
            username=username,
            password=password,
            request_timeout_seconds=request_timeout_seconds,
            min_request_interval_seconds=min_request_interval_seconds,
        )

    def fetch_financial_report_details(self, symbol: str, page_size: int = 100) -> list[dict]:
        rows = self._list_company_news(symbol=symbol, page_size=page_size)
        details: list[dict] = []
        for row in rows:
            if not _looks_like_financial_report(row):
                continue
            detail = self._get_news_detail(int(row["HaberId"]), piyasa_id=1)
            parsed = _parse_news_detail_payload(detail)
            if not parsed:
                continue
            if not _is_canonical_financial_report_detail(parsed):
                continue
            details.append(parsed)
        return details

    def fetch_balance_format(self, symbol: str) -> str | None:
        response = self._request_json(
            "POST",
            f"{FINNET_API_BASE}/HisseBilancoFormat",
            json_body={"hisseKod": symbol.upper()},
        )
        value = response.get("HisseBilancoFormatResult")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def fetch_company_periods(self, symbol: str) -> list[dict]:
        response = self._request_json(
            "POST",
            f"{FINNET_API_BASE}/HisseDonemListesi",
            json_body={"Param": {"Kod": symbol.upper()}},
        )
        return response.get("HisseDonemListesiResult") or []

    def fetch_report_table(self, report_url_slug: str, symbol: str, son_tarih: str = "") -> dict:
        payload = {
            "RaporParams": {
                "Url": report_url_slug,
                "RaporParametreleri": [
                    {"key": "Kod", "value": symbol.upper()},
                    {"key": "sonTarih", "value": son_tarih},
                ],
            }
        }
        return self._request_json(
            "POST",
            f"{FINNET_API_BASE}/RaporTabloHesapla",
            json_body=payload,
        )

    def _ensure_authenticated(self) -> None:
        if self._service_key:
            return
        self._login()
        self._service_key = self._fetch_service_key()

    def _login(self) -> None:
        response = self.session.get(LOGIN_URL, timeout=self.request_timeout_seconds)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.find("form")
        payload = {
            "mail": self.username,
            "password": self.password,
            "ReturnUrl": DEFAULT_RETURN_URL,
        }
        action = LOGIN_URL
        if form is not None:
            action = urljoin(LOGIN_URL, form.get("action") or LOGIN_URL)
            for input_tag in form.find_all("input"):
                name = input_tag.get("name")
                if not name or name in {"mail", "password"}:
                    continue
                payload[name] = input_tag.get("value") or payload.get(name, "")
        post = self.session.post(action, data=payload, timeout=self.request_timeout_seconds, allow_redirects=True)
        post.raise_for_status()

    def _fetch_service_key(self) -> str:
        response = self.session.post(SERVICE_KEY_URL, timeout=self.request_timeout_seconds)
        response.raise_for_status()
        service_key = response.json()
        if not isinstance(service_key, str) or not service_key.strip():
            raise ValueError("QueenStocks GetServisKey returned empty value")
        return service_key

    def _request_json(self, method: str, url: str, *, json_body: dict | None = None) -> dict:
        for attempt in range(2):
            self._ensure_authenticated()
            self._respect_request_interval()
            response = self.session.request(
                method,
                url,
                json=json_body,
                timeout=self.request_timeout_seconds,
                headers={"authorization-serviskey": self._service_key or ""},
            )
            self._last_request_monotonic = time.monotonic()
            if response.ok:
                return response.json()
            if attempt == 0 and response.status_code in {401, 403}:
                self._service_key = None
                continue
            response.raise_for_status()
        raise ValueError(f"QueenStocks request failed for {url}")

    def _respect_request_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self.min_request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _list_company_news(self, symbol: str, page_size: int) -> list[dict]:
        results: list[dict] = []
        page = 1
        while True:
            payload = {
                "Hisse_EndeksIdList": symbol.upper(),
                "TurId": "",
                "KayitSayisi": page_size,
                "HaberTur": 1,
                "PiyasaId": "1,5",
                "Sayfa": page,
                "EndeksSektorId": None,
                "AramaKriterListe": None,
            }
            response = self._request_json("POST", f"{HABER_API_BASE}/FirmaHaberListeV2", json_body=payload)
            rows = response.get("HaberListesi") or []
            if not rows:
                break
            results.extend(rows)
            if len(rows) < page_size:
                break
            page += 1
        return results

    def _get_news_detail(self, haber_id: int, piyasa_id: int = 1) -> dict:
        payload = {"HaberId": haber_id, "PiyasaId": piyasa_id}
        return self._request_json("POST", f"{HABER_API_BASE}/HaberDetayGetir", json_body=payload)


class QueenStocksFinancialLoader:
    def __init__(
        self,
        client: QueenStocksClient,
        timezone: str = "Europe/Istanbul",
    ):
        self.client = client
        self.timezone = timezone

    def fetch_records(self, symbol: str) -> list[dict]:
        details = self.client.fetch_financial_report_details(symbol)
        records: list[dict] = []
        for detail in details:
            record = _build_statement_record_from_detail(symbol, detail, self.timezone)
            if record is not None:
                records.append(record)
        return records

    def build_from_records(self, symbol: str, records: list[dict]) -> QueenStocksLoadResult:
        statement_rows: list[dict] = []
        item_rows: list[dict] = []
        failures: list[dict] = []
        symbol_upper = symbol.upper()

        for record in records:
            period_end = _coerce_date(record.get("period_end"))
            if period_end is None:
                failures.append({"symbol": symbol_upper, "reason": "missing_period_end", "detail": str(record)})
                continue

            missing = [key for key in REQUIRED_VALUES if record.get(key) is None]
            if missing:
                failures.append(
                    {
                        "symbol": symbol_upper,
                        "reason": "missing_core_items",
                        "detail": f"{period_end.isoformat()}:{','.join(sorted(missing))}",
                    }
                )
                continue

            statement_id = str(
                record.get("statement_id")
                or f"QUEENSTOCKS-{symbol_upper}-{period_end:%Y%m%d}-{record.get('bildirim_id') or '0'}"
            )
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
                    "source_system": "queenstocks",
                    "announcement_source_url": record.get("announcement_source_url") or record.get("source_url"),
                    "announcement_source_system": record.get("announcement_source_system") or "queenstocks_kap_news",
                    "raw_hash": record.get("raw_hash"),
                    "created_at": _coerce_datetime(record.get("created_at")) or datetime.now(UTC),
                    "shares_outstanding": _coerce_float(record.get("shares_outstanding")),
                    "shares_announcement_datetime": _coerce_datetime(record.get("shares_announcement_datetime"))
                    or announcement_datetime,
                    "shares_source_url": record.get("shares_source_url") or record.get("source_url"),
                }
            )
            for item_code in ("net_income", "equity", "operating_profit", "cash", "total_debt"):
                value = _coerce_float(record.get(item_code))
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

        return QueenStocksLoadResult(
            statements=pd.DataFrame(statement_rows),
            items=pd.DataFrame(item_rows),
            failures=pd.DataFrame(failures),
        )


class QueenStocksAnnouncementLoader:
    def __init__(self, client: QueenStocksClient, timezone: str = "Europe/Istanbul"):
        self.client = client
        self.timezone = timezone

    def fetch_records(self, symbol: str) -> list[dict]:
        details = self.client.fetch_financial_report_details(symbol)
        records: list[dict] = []
        for detail in details:
            period_end = _extract_period_end_from_detail(detail)
            announcement_datetime = _coerce_datetime_string(detail.get("AciklanmaTarihi"), timezone=self.timezone)
            announcement_date = announcement_datetime.date() if announcement_datetime is not None else None
            if period_end is None or announcement_date is None:
                continue
            bildirim_id = detail.get("BildirimId")
            records.append(
                {
                    "statement_id": (
                        f"QUEENSTOCKS-{symbol.upper()}-{period_end:%Y%m%d}-{bildirim_id}"
                        if bildirim_id is not None
                        else None
                    ),
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_datetime": announcement_datetime,
                    "announcement_source_url": _build_detail_source_url(symbol, detail),
                }
            )
        return records


def _build_statement_record_from_detail(symbol: str, detail: dict, timezone: str) -> dict | None:
    period_end = _extract_period_end_from_detail(detail)
    announcement_datetime = _coerce_datetime_string(detail.get("AciklanmaTarihi"), timezone=timezone)
    if period_end is None or announcement_datetime is None:
        return None
    values = _extract_financial_values_from_detail(detail)
    bildirim_id = detail.get("BildirimId")
    source_url = _build_detail_source_url(symbol, detail)
    return {
        "statement_id": f"QUEENSTOCKS-{symbol.upper()}-{period_end:%Y%m%d}-{bildirim_id or '0'}",
        "symbol": symbol.upper(),
        "period_end": period_end,
        "fiscal_year": period_end.year,
        "fiscal_period": _infer_fiscal_period(period_end),
        "statement_type": "financial_statement",
        "announcement_datetime": announcement_datetime,
        "announcement_date": announcement_datetime.date(),
        "currency": "TRY",
        "is_consolidated": True,
        "is_revised": False,
        "source_url": source_url,
        "announcement_source_url": source_url,
        "announcement_source_system": "queenstocks_kap_news",
        "shares_announcement_datetime": announcement_datetime,
        "shares_source_url": source_url,
        "created_at": datetime.now(UTC),
        "raw_hash": _build_raw_hash(symbol, period_end, bildirim_id, announcement_datetime),
        "bildirim_id": bildirim_id,
        **values,
    }


def _extract_financial_values_from_detail(detail: dict) -> dict[str, float | None]:
    rows = list(_iter_table_rows_from_detail(detail))
    values: dict[str, float | None] = {
        "net_income": None,
        "equity": None,
        "operating_profit": None,
        "cash": None,
        "total_debt": None,
        "shares_outstanding": None,
    }
    for item_code, aliases in LINE_ITEM_ALIASES.items():
        value = _find_first_matching_row_value(rows, aliases)
        if value is not None:
            values[item_code] = value
    debt_total = 0.0
    found_debt = False
    for row in rows:
        label = _normalize_text(row[0]) if row else ""
        if not label:
            continue
        if any(alias in label for alias in NORMALIZED_DEBT_COMPONENT_ALIASES):
            number = _first_numeric_value(row[1:])
            if number is not None:
                debt_total += number
                found_debt = True
    if found_debt:
        values["total_debt"] = debt_total
    return values


def extract_current_report_value(report_payload: dict, row_label: str) -> float | None:
    current_property = _current_report_property_name(report_payload)
    if not current_property:
        return None
    row_map = _report_row_map(report_payload)
    row = row_map.get(str(row_label).strip())
    if not row:
        return None
    return _coerce_float(row.get(current_property))


def derive_company_card_statement_probe(
    symbol: str,
    *,
    balance_format: str | None,
    hisse_payload: dict,
    onemli_gt_payload: dict,
    piyasacarpan_payload: dict,
    yatirimharcamalari_payload: dict,
) -> dict[str, float | str | bool | None]:
    paid_in_capital_mio = extract_current_report_value(hisse_payload, "Ödenmiş Sermaye(Mio TL)")
    market_cap_mio = extract_current_report_value(hisse_payload, "PD(Mio TL)")
    pd_dd = extract_current_report_value(piyasacarpan_payload, "PD/DD")
    net_income_mio = extract_current_report_value(onemli_gt_payload, "Net Kar/Zarar")
    ebitda_mio = extract_current_report_value(onemli_gt_payload, "FAVÖK")
    amort_mio = extract_current_report_value(yatirimharcamalari_payload, "Amortisman Gid.")

    shares_outstanding = paid_in_capital_mio * 1_000_000 if paid_in_capital_mio is not None else None
    equity = ((market_cap_mio * 1_000_000) / pd_dd) if market_cap_mio is not None and pd_dd not in (None, 0) else None
    net_income = net_income_mio * 1_000_000 if net_income_mio is not None else None
    ebitda = ebitda_mio * 1_000_000 if ebitda_mio is not None else None
    amortization = amort_mio * 1_000_000 if amort_mio is not None else None
    operating_profit_est = (
        ebitda - amortization
        if ebitda is not None and amortization is not None
        else None
    )

    return {
        "symbol": symbol.upper(),
        "balance_format": balance_format,
        "shares_outstanding": shares_outstanding,
        "equity": equity,
        "net_income": net_income,
        "ebitda": ebitda,
        "amortization": amortization,
        "operating_profit_est": operating_profit_est,
        "can_derive_required_fields": bool(
            shares_outstanding is not None
            and equity is not None
            and net_income is not None
            and operating_profit_est is not None
        ),
    }


def _report_row_map(report_payload: dict) -> dict[str, dict]:
    table = _first_report_table(report_payload)
    rows = table.get("JSVeriler") or []
    row_map: dict[str, dict] = {}
    for row in rows:
        label = row.get("o", {}).get("Baslik")
        if label is None:
            continue
        row_map[str(label).strip()] = row.get("o", {})
    return row_map


def _current_report_property_name(report_payload: dict) -> str | None:
    table = _first_report_table(report_payload)
    headers = table.get("BaslikListe") or []
    property_names = [header.get("PropertyName") for header in headers if header.get("PropertyName")]
    if not property_names:
        return None
    return str(property_names[-1])


def _first_report_table(report_payload: dict) -> dict:
    tables = report_payload.get("TabloListesi") or []
    if not tables:
        return {}
    first = tables[0]
    return first if isinstance(first, dict) else {}


def _iter_table_rows_from_detail(detail: dict):
    tables = detail.get("HaberTablolarList") or {}
    if isinstance(tables, list):
        iterable = tables
    else:
        iterable = tables.values()
    for table in iterable:
        for row in table.get("Rows") or []:
            cells = row.get("Cells") or []
            row_text = []
            for cell in cells:
                value = cell.get("Data")
                if value in (None, ""):
                    value = cell.get("Deger")
                row_text.append(str(value).strip() if value is not None else "")
            if any(text for text in row_text):
                yield row_text


def _find_first_matching_row_value(rows: list[list[str]], aliases: tuple[str, ...]) -> float | None:
    normalized_aliases = tuple(_normalize_text(alias) for alias in aliases)
    for row in rows:
        label = _normalize_text(row[0]) if row else ""
        if not label:
            continue
        if any(alias in label for alias in normalized_aliases):
            value = _first_numeric_value(row[1:])
            if value is not None:
                return value
    return None


def _first_numeric_value(values: list[str]) -> float | None:
    for value in values:
        parsed = _coerce_float(value)
        if parsed is not None:
            return parsed
    return None


def _extract_period_end_from_detail(detail: dict) -> date | None:
    candidates: list[date] = []
    for row in _iter_table_rows_from_detail(detail):
        for cell in row:
            for match in DATE_PATTERN.finditer(str(cell)):
                day, month, year = match.groups()
                try:
                    parsed = date(int(year), int(month), int(day))
                except ValueError:
                    continue
                if parsed.month in {3, 6, 9, 12}:
                    candidates.append(_normalize_period_end_convention(parsed))
    if not candidates:
        yil = _coerce_int(detail.get("Yil"))
        donem = _coerce_int(detail.get("Donem"))
        if yil is not None and donem is not None and donem in {3, 6, 9, 12}:
            return _normalize_period_end_convention(date(yil, donem, _month_end_day(yil, donem)))
        return None
    return max(candidates)


def _build_detail_source_url(symbol: str, detail: dict) -> str:
    direct = detail.get("Url")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    haber_id = detail.get("HaberId")
    if haber_id:
        return f"https://queenstocks.com/queenstockspro/haber-detay?symbol={symbol.upper()}&haberId={haber_id}"
    return f"https://queenstocks.com/queenstockspro/TemelAnaliz/SirketKartiAnalizi#{symbol.upper()}"


def _build_raw_hash(symbol: str, period_end: date, bildirim_id, announcement_datetime: datetime) -> str:
    payload = f"{symbol.upper()}|{period_end.isoformat()}|{bildirim_id}|{announcement_datetime.isoformat()}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _looks_like_financial_report(row: dict) -> bool:
    bildirim_tip = str(row.get("BildirimTip") or "").upper()
    if bildirim_tip == "FR":
        return True
    ozet = str(row.get("Ozet") or "")
    return bool(FINANCIAL_REPORT_PATTERN.search(ozet))


def _is_canonical_financial_report_detail(detail: dict) -> bool:
    bildirim_tip = str(detail.get("BildirimTip") or "").strip().upper()
    return bildirim_tip == "FR"


def _parse_news_detail_payload(payload: dict) -> dict:
    raw = payload.get("HaberDetayGetirResult")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace("%", "").replace(" ", "")
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


def _coerce_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "evet"}:
        return True
    if text in {"0", "false", "no", "hayir", "hayır"}:
        return False
    return default


def _coerce_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _coerce_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _coerce_datetime_string(value, timezone: str) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, format="%d.%m.%Y %H:%M", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    localized = parsed.tz_localize(timezone)
    return localized.tz_convert("UTC").to_pydatetime()


def _infer_fiscal_period(period_end: date) -> str:
    quarter = ((period_end.month - 1) // 3) + 1
    return f"Q{quarter}"


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_only).strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def _month_end_day(year: int, month: int) -> int:
    return pd.Timestamp(year=year, month=month, day=1).days_in_month


def _normalize_period_end_convention(period_end: date) -> date:
    return date(period_end.year, period_end.month, 1)


NORMALIZED_DEBT_COMPONENT_ALIASES = tuple(_normalize_text(alias) for alias in DEBT_COMPONENT_ALIASES)

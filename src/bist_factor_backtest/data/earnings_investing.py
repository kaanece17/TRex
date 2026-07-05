from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup
import pandas as pd
import requests

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

SEARCH_BOOTSTRAP_URL = "https://tr.investing.com/search/service/search"
SEARCH_API_URL = "https://api.investing.com/api/search/v2/search"
EARNINGS_API_URL_TEMPLATE = "https://endpoints.investing.com/earnings/v1/instruments/{instrument_id}/earnings"
TOKEN_PATTERN = re.compile(r'(?:\\"accessToken\\":\\"([^\\"]+)\\"|"accessToken":"([^"]+)")')


@dataclass(frozen=True)
class InvestingAnnouncementsResult:
    announcements: pd.DataFrame
    failures: pd.DataFrame


class InvestingEarningsLoader:
    def __init__(
        self,
        request_timeout_seconds: int = 20,
        min_request_interval_seconds: float = 1.0,
        max_retry_attempts: int = 4,
    ):
        self.request_timeout_seconds = request_timeout_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self.max_retry_attempts = max_retry_attempts
        self._last_request_monotonic = 0.0
        self._access_token: str | None = None

    def fetch_records(self, symbol: str, earnings_url: str) -> list[dict]:
        instrument_id = self._resolve_instrument_id(symbol=symbol, earnings_url=earnings_url)
        if instrument_id is not None:
            try:
                return self._fetch_api_records(symbol=symbol, earnings_url=earnings_url, instrument_id=instrument_id)
            except Exception:
                pass
        return self._fetch_html_records(symbol=symbol, earnings_url=earnings_url)

    def _respect_request_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self.min_request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _bootstrap_access_token(self, query: str) -> str:
        if self._access_token:
            return self._access_token

        response = self._request_with_retries(
            SEARCH_BOOTSTRAP_URL,
            params={
                "search_text": query,
                "term": query,
                "country_id": "0",
                "tab_id": "All",
            },
        )
        match = TOKEN_PATTERN.search(response.text)
        if match is None:
            raise ValueError("Could not extract Investing access token")
        self._access_token = match.group(1) or match.group(2)
        return self._access_token

    def _resolve_instrument_id(self, symbol: str, earnings_url: str) -> int | None:
        token = self._bootstrap_access_token(symbol)
        response = self._request_with_retries(
            SEARCH_API_URL,
            params={"q": symbol},
            headers={"Authorization": f"Bearer {token}"},
        )
        payload = response.json()
        quotes = payload.get("quotes") or []
        target_url = _normalize_investing_quote_url(earnings_url)
        symbol_upper = symbol.upper()
        candidates = []
        for quote in quotes:
            quote_symbol = str(quote.get("symbol") or "").upper()
            quote_type = str(quote.get("type") or "")
            quote_flag = str(quote.get("flag") or "")
            if quote_symbol != symbol_upper:
                continue
            if "Stock" not in quote_type or quote_flag != "Turkey":
                continue
            candidates.append(quote)

        if not candidates:
            return None

        for quote in candidates:
            if _normalize_investing_quote_url(quote.get("url")) == target_url:
                return int(quote["id"])

        if len(candidates) == 1:
            return int(candidates[0]["id"])

        for quote in candidates:
            if str(quote.get("exchange") or "").lower() == "istanbul":
                return int(quote["id"])
        return int(candidates[0]["id"])

    def _fetch_api_records(self, symbol: str, earnings_url: str, instrument_id: int) -> list[dict]:
        token = self._bootstrap_access_token(symbol)
        records: list[dict] = []
        cursor: str | None = None

        while True:
            params = {"limit": 10}
            if cursor:
                params["cursor"] = cursor
            try:
                response = self._request_with_retries(
                    EARNINGS_API_URL_TEMPLATE.format(instrument_id=instrument_id),
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except requests.HTTPError as error:
                response = getattr(error, "response", None)
                if cursor and response is not None and response.status_code == 404:
                    break
                raise
            payload = response.json()
            page_records = self._parse_api_payload(symbol=symbol, payload=payload, source_url=earnings_url)
            records.extend(page_records)
            cursor = payload.get("cursor")
            if not cursor:
                break

        deduplicated: dict[tuple[str, date], dict] = {}
        for record in records:
            deduplicated[(record["symbol"], record["period_end"])] = record
        return list(deduplicated.values())

    def _parse_api_payload(self, symbol: str, payload: dict, source_url: str) -> list[dict]:
        records: list[dict] = []
        for entry in payload.get("earnings") or []:
            report_year = entry.get("report_year")
            report_month = entry.get("report_month")
            announcement_date = _coerce_date(entry.get("date"))
            if report_year is None or report_month is None or announcement_date is None:
                continue
            try:
                period_end = date(int(report_year), int(report_month), 1)
            except ValueError:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": source_url,
                    "announcement_source_system": "investing",
                }
            )
        return records

    def _fetch_html_records(self, symbol: str, earnings_url: str) -> list[dict]:
        response = self._request_with_retries(earnings_url)
        return self.parse_html(symbol=symbol, html=response.text, source_url=earnings_url)

    def _request_with_retries(self, url: str, params: dict | None = None, headers: dict | None = None):
        last_response = None
        merged_headers = dict(REQUEST_HEADERS)
        if headers:
            merged_headers.update(headers)

        for attempt in range(1, self.max_retry_attempts + 1):
            self._respect_request_interval()
            response = _http_get(url, timeout=self.request_timeout_seconds, params=params, headers=merged_headers)
            self._last_request_monotonic = time.monotonic()
            last_response = response
            if getattr(response, "status_code", 200) != 429:
                response.raise_for_status()
                return response
            if attempt < self.max_retry_attempts:
                time.sleep(min(45, 5 * attempt))

        assert last_response is not None
        last_response.raise_for_status()
        return last_response

    def parse_html(self, symbol: str, html: str, source_url: str) -> list[dict]:
        next_data_records = _read_next_data_earnings(symbol=symbol, html=html, source_url=source_url)
        if next_data_records:
            return next_data_records
        tables = _read_html_tables(html)
        if not tables:
            return []
        records: list[dict] = []
        for table in tables:
            normalized = table.copy()
            normalized.columns = [str(column).strip() for column in normalized.columns]
            period_column = _find_column(normalized.columns, {"Dönem Sonu", "Donem Sonu", "Fiscal Quarter End"})
            announcement_column = _find_column(normalized.columns, {"Yayın Tarihi", "Yayin Tarihi", "Release Date"})
            if period_column is None or announcement_column is None:
                continue
            for _, row in normalized.iterrows():
                period_end = _coerce_date(row.get(period_column))
                announcement_date = _coerce_date(row.get(announcement_column))
                if period_end is None or announcement_date is None:
                    continue
                records.append(
                    {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "announcement_date": announcement_date,
                        "announcement_source_url": source_url,
                        "announcement_source_system": "investing",
                    }
                )
        return records

    def build_from_records(self, symbol: str, records: list[dict]) -> InvestingAnnouncementsResult:
        normalized_rows: list[dict] = []
        failures: list[dict] = []
        symbol_upper = symbol.upper()

        for record in records:
            period_end = _coerce_date(record.get("period_end") or record.get("donem_sonu") or record.get("Dönem Sonu"))
            announcement_date = _coerce_date(
                record.get("announcement_date") or record.get("yayin_tarihi") or record.get("Yayın Tarihi")
            )
            if period_end is None:
                failures.append({"symbol": symbol_upper, "reason": "missing_period_end", "detail": str(record)})
                continue
            if announcement_date is None:
                failures.append(
                    {
                        "symbol": symbol_upper,
                        "reason": "missing_announcement_date",
                        "detail": f"{period_end.isoformat()}",
                    }
                )
                continue
            normalized_rows.append(
                {
                    "statement_id": record.get("statement_id"),
                    "symbol": symbol_upper,
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_datetime": _coerce_datetime(record.get("announcement_datetime")),
                    "announcement_source_url": _coalesce_value(
                        record.get("announcement_source_url"),
                        record.get("source_url"),
                    ),
                    "announcement_source_system": _coalesce_value(
                        record.get("announcement_source_system"),
                        "investing",
                    ),
                }
            )

        return InvestingAnnouncementsResult(
            announcements=pd.DataFrame(normalized_rows),
            failures=pd.DataFrame(failures),
        )


def merge_announcements_into_statements(
    statements: pd.DataFrame,
    announcements: pd.DataFrame,
    overwrite_existing: bool = True,
) -> pd.DataFrame:
    if statements.empty or announcements.empty:
        return statements.copy()

    merged = statements.copy()
    merged["period_end"] = pd.to_datetime(merged["period_end"], errors="coerce").dt.date
    merged["announcement_date"] = pd.to_datetime(merged.get("announcement_date"), errors="coerce").dt.date
    merged["announcement_datetime"] = pd.to_datetime(merged.get("announcement_datetime"), errors="coerce", utc=True)
    updates = announcements.copy()
    updates["period_end"] = pd.to_datetime(updates["period_end"], errors="coerce").dt.date

    if "announcement_source_url" not in merged.columns:
        merged["announcement_source_url"] = None
    if "announcement_source_system" not in merged.columns:
        merged["announcement_source_system"] = None

    updates_by_id = updates[updates["statement_id"].notna()].copy()
    if not updates_by_id.empty:
        updates_by_id["statement_id"] = updates_by_id["statement_id"].astype(str)
        id_map = updates_by_id.set_index("statement_id").to_dict(orient="index")
        for index, statement_id in merged["statement_id"].astype(str).items():
            update = id_map.get(statement_id)
            if update is not None:
                _apply_update(merged, index, update, overwrite_existing=overwrite_existing)

    updates_by_period = updates[updates["statement_id"].isna()].copy()
    if not updates_by_period.empty:
        period_map = updates_by_period.set_index(["symbol", "period_end"]).to_dict(orient="index")
        for index, row in merged[["symbol", "period_end"]].iterrows():
            update = period_map.get((str(row["symbol"]).upper(), row["period_end"]))
            if update is not None:
                _apply_update(merged, index, update, overwrite_existing=overwrite_existing)

    merged["announcement_date"] = pd.to_datetime(merged["announcement_date"], errors="coerce").dt.date
    return merged


def _apply_update(statements: pd.DataFrame, index: int, update: dict, overwrite_existing: bool = True) -> None:
    existing_announcement_date = pd.to_datetime(statements.at[index, "announcement_date"], errors="coerce")
    period_end = pd.to_datetime(statements.at[index, "period_end"], errors="coerce")
    if not overwrite_existing and pd.notna(existing_announcement_date):
        if pd.notna(period_end) and existing_announcement_date.date() < period_end.date():
            pass
        else:
            return
    statements.at[index, "announcement_date"] = pd.Timestamp(update["announcement_date"])
    statements.at[index, "announcement_source_url"] = update.get("announcement_source_url")
    statements.at[index, "announcement_source_system"] = update.get("announcement_source_system")
    announcement_datetime = update.get("announcement_datetime")
    if announcement_datetime is not None:
        statements.at[index, "announcement_datetime"] = pd.Timestamp(announcement_datetime)


def _coerce_date(value):
    if _is_missing(value):
        return None
    parsed = _parse_datetime_like(value)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _coerce_datetime(value):
    if _is_missing(value):
        return None
    parsed = _parse_datetime_like(value, utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    return bool(pd.isna(value))


def _coalesce_value(primary, fallback):
    return fallback if _is_missing(primary) else primary


def _find_column(columns, candidates: set[str]) -> str | None:
    candidate_map = {str(candidate).strip().lower(): candidate for candidate in candidates}
    for column in columns:
        if str(column).strip().lower() in candidate_map:
            return str(column)
    return None


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


def _read_next_data_earnings(symbol: str, html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    next_data_script = soup.find("script", id="__NEXT_DATA__")
    if next_data_script is None or not next_data_script.string:
        return []

    try:
        payload = json.loads(next_data_script.string)
    except json.JSONDecodeError:
        return []

    earnings = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("state", {})
        .get("earningsStore", {})
        .get("earnings", [])
    )
    records: list[dict] = []
    for entry in earnings:
        report_year = entry.get("reportYear")
        report_month = entry.get("reportMonth")
        announcement_date = _coerce_date(entry.get("date"))
        if report_year is None or report_month is None or announcement_date is None:
            continue
        try:
            period_end = date(int(report_year), int(report_month), 1)
        except ValueError:
            continue
        records.append(
            {
                "symbol": symbol.upper(),
                "period_end": period_end,
                "announcement_date": announcement_date,
                "announcement_source_url": source_url,
            }
        )
    return records


def _http_get(url: str, timeout: int, params: dict | None = None, headers: dict | None = None):
    request_headers = REQUEST_HEADERS if headers is None else headers
    # curl_cffi helps with some HTML pages behind bot protection, but the cursor-based
    # Investing JSON endpoints behave more reliably with regular requests.
    if curl_requests is not None and "endpoints.investing.com" not in url and "api.investing.com" not in url:
        return curl_requests.get(url, params=params, headers=request_headers, impersonate="chrome", timeout=timeout)
    return requests.get(url, params=params, headers=request_headers, timeout=timeout)


def _normalize_investing_quote_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://tr.investing.com{url}")
    path = parsed.path.rstrip("/")
    if path.endswith("-earnings"):
        path = path[: -len("-earnings")]
    query_items = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key == "cid"]
    query = urlencode(query_items)
    return urlunparse(("", "", path, "", query, ""))


def _parse_datetime_like(value, utc: bool = False):
    text = str(value).strip()
    if "." in text and "-" not in text:
        return pd.to_datetime(text, errors="coerce", dayfirst=True, utc=utc)
    return pd.to_datetime(value, errors="coerce", utc=utc)

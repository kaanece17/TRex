from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import io
import re
import subprocess
import time
import zipfile

import pandas as pd
import requests
from bs4 import BeautifulSoup

from bist_factor_backtest.data.kap_xbrl import ParsedFinancialReport, parse_financial_report_html


@dataclass(frozen=True)
class KapLoadResult:
    statements: pd.DataFrame
    items: pd.DataFrame
    failures: pd.DataFrame


class KapNameResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class _SimpleResponse:
    status_code: int
    content: bytes
    text: str
    headers: dict

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


ITEM_ALIASES = {
    "net_income": [
        "Dönem Karı (Zararı)",
        "Net Dönem Karı veya Zararı",
        "Ana Ortaklık Payları",
    ],
    "equity": [
        "Özkaynaklar",
        "Ana Ortaklığa Ait Özkaynaklar",
    ],
    "operating_profit": [
        "Esas Faaliyet Karı (Zararı)",
        "Esas Faaliyet Karı/Zararı",
    ],
    "cash": [
        "Nakit ve Nakit Benzerleri",
    ],
    "total_debt": [
        "Finansal Borçlar",
        "Kısa Vadeli Borçlanmalar",
        "Uzun Vadeli Borçlanmalar",
    ],
}


class KapFinancialLoader:
    def __init__(
        self,
        max_retries: int = 5,
        backoff_seconds: float = 1.5,
        request_timeout_seconds: int = 20,
        min_request_interval_seconds: float = 1.0,
        rate_limit_sleep_seconds: float = 30.0,
    ):
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self.rate_limit_sleep_seconds = rate_limit_sleep_seconds
        self._parsed_report_cache: dict[str, ParsedFinancialReport] = {}
        self._disclosure_financial_table_cache: dict[str, bool] = {}
        self._last_request_monotonic: float | None = None

    def load(self, symbols: list[str], start: datetime | date, end: datetime | date) -> KapLoadResult:
        try:
            import pykap
        except ImportError as error:
            raise RuntimeError("pykap is required for live KAP loading") from error

        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end
        statements = []
        items = []
        failures = []
        for symbol in symbols:
            try:
                disclosures = self.list_disclosures(symbol, start_date, end_date)
            except KapNameResolutionError:
                raise
            except Exception as error:
                failures.append({"symbol": symbol, "reason": "kap_fetch_failed", "detail": str(error)})
                continue

            result = self.build_from_disclosures(symbol, disclosures)
            if not result.statements.empty:
                statements.extend(result.statements.to_dict(orient="records"))
            if not result.items.empty:
                items.extend(result.items.to_dict(orient="records"))
            if not result.failures.empty:
                failures.extend(result.failures.to_dict(orient="records"))

        return KapLoadResult(pd.DataFrame(statements), pd.DataFrame(items), pd.DataFrame(failures))

    def list_disclosures(self, symbol: str, start: datetime | date, end: datetime | date) -> list[dict]:
        try:
            import pykap
        except ImportError as error:
            raise RuntimeError("pykap is required for live KAP loading") from error

        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end
        try:
            company = pykap.BISTCompany(symbol)
        except Exception as error:
            if _is_name_resolution_error(error):
                raise KapNameResolutionError(str(error)) from error
            raise
        return self._fetch_disclosures_with_retry(company, symbol, start_date, end_date)

    def build_from_disclosures(self, symbol: str, disclosures: list[dict]) -> KapLoadResult:
        statements = []
        items = []
        failures = []
        if not disclosures:
            failures.append({"symbol": symbol, "reason": "missing_financial_disclosures", "detail": ""})
            return KapLoadResult(pd.DataFrame(statements), pd.DataFrame(items), pd.DataFrame(failures))

        for disclosure in disclosures:
            disclosure_index = disclosure.get("disclosureIndex")
            statement_id = f"{symbol.upper()}-{disclosure_index}"
            announcement_datetime = _parse_announcement_datetime(disclosure)
            period_end = _parse_period_end(disclosure)
            if (
                period_end is not None
                and announcement_datetime is not None
                and period_end > announcement_datetime.date()
            ):
                failures.append(
                    {
                        "symbol": symbol,
                        "reason": "kap_invalid_period_end_after_announcement",
                        "detail": f"{disclosure_index}: period_end={period_end.isoformat()} announcement={announcement_datetime.date().isoformat()}",
                    }
                )
                continue
            statements.append(
                {
                    "statement_id": statement_id,
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "fiscal_year": disclosure.get("year"),
                    "fiscal_period": disclosure.get("ruleType") or disclosure.get("ruleTypeTerm"),
                    "statement_type": disclosure.get("financialTableType") or disclosure.get("statementType"),
                    "announcement_datetime": announcement_datetime,
                    "announcement_date": announcement_datetime.date() if announcement_datetime is not None else None,
                    "currency": disclosure.get("currency"),
                    "is_consolidated": _is_consolidated(disclosure),
                    "is_revised": bool(disclosure.get("isOldVersion") or disclosure.get("isRevision")),
                    "source_url": f"https://www.kap.org.tr/tr/Bildirim/{disclosure_index}" if disclosure_index else None,
                    "raw_hash": str(hash(str(disclosure))),
                    "created_at": datetime.utcnow(),
                    "shares_outstanding": None,
                    "shares_announcement_datetime": announcement_datetime,
                    "shares_source_url": f"https://www.kap.org.tr/tr/Bildirim/{disclosure_index}" if disclosure_index else None,
                }
            )
            try:
                parsed = self._fetch_and_parse_report_with_retry(disclosure_index)
                items.extend(_items_from_parsed_report(statement_id, symbol, parsed.to_items()))
                statements[-1]["shares_outstanding"] = parsed.shares_outstanding
            except KapNameResolutionError:
                raise
            except Exception as error:
                failures.append(
                    {
                        "symbol": symbol,
                        "reason": "kap_item_parse_failed",
                        "detail": f"{disclosure_index}: {error}",
                    }
                )
        return KapLoadResult(pd.DataFrame(statements), pd.DataFrame(items), pd.DataFrame(failures))

    def _fetch_disclosures_with_retry(self, company, symbol: str, start_date: date, end_date: date):
        search_error = None
        search_disclosures = []
        try:
            search_disclosures = self._fetch_disclosures_from_search_page(
                company_id=getattr(company, "company_id", None),
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as error:
            search_error = error
            if _is_name_resolution_error(error):
                raise KapNameResolutionError(str(error)) from error

        file_by_year_error = None
        fallback_disclosures = []
        try:
            fallback_disclosures = self._fetch_disclosures_from_file_by_year(
                company_id=getattr(company, "company_id", None),
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as error:
            file_by_year_error = error
            if _is_name_resolution_error(error):
                raise KapNameResolutionError(str(error)) from error

        merged_disclosures = {}
        for disclosure in [*search_disclosures, *fallback_disclosures]:
            disclosure_index = disclosure.get("disclosureIndex")
            if disclosure_index is None:
                continue
            merged_disclosures[str(disclosure_index)] = disclosure
        if merged_disclosures:
            return sorted(
                merged_disclosures.values(),
                key=lambda disclosure: str(disclosure.get("publishDateTime") or disclosure.get("publishDate") or ""),
            )

        if search_error is not None or file_by_year_error is not None:
            raise RuntimeError(
                f"symbol={symbol} disclosure_fetch_failed search_page_failed={search_error}; "
                f"file_by_year_fallback_failed={file_by_year_error}"
            )
        return []

    def _fetch_disclosures_from_search_page(
        self,
        company_id: str | None,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        if not company_id:
            raise RuntimeError("missing_company_id")
        response = self._get_with_retry(
            f"https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?member={company_id}&disclosureClass=FR",
            f"search_page_fetch_failed symbol={symbol}",
        )
        rows = _extract_financial_report_indexes(response.text, symbol.upper())
        disclosures = []
        for row in rows:
            publish_datetime = _parse_publish_datetime_value(row["publish_date"])
            if pd.isna(publish_datetime):
                continue
            publish_date = publish_datetime.to_pydatetime()
            if publish_date.date() < start_date or publish_date.date() > end_date:
                continue
            disclosure_index = row["disclosure_index"]
            if not self._disclosure_has_financial_tables(disclosure_index):
                continue
            quarter = row["period"]
            disclosures.append(
                {
                    "disclosureIndex": disclosure_index,
                    "publishDateTime": publish_date.isoformat(),
                    "publishDate": publish_date.isoformat(),
                    "periodEndDate": _period_end_from_year_period(row["year"], quarter).isoformat(),
                    "year": row["year"],
                    "ruleType": f"Q{quarter}",
                    "financialTableType": None,
                    "statementType": None,
                }
            )
        disclosures.sort(key=lambda disclosure: str(disclosure.get("publishDateTime") or ""))
        return disclosures

    def _fetch_and_parse_report_with_retry(self, disclosure_index: int | str):
        disclosure_key = str(disclosure_index)
        if disclosure_key in self._parsed_report_cache:
            return self._parsed_report_cache[disclosure_key]
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._get_with_retry(
                    f"https://www.kap.org.tr/tr/Bildirim/{disclosure_index}",
                    f"disclosure={disclosure_index} page_fetch_failed",
                )
                parsed = parse_financial_report_html(response.text)
                if not _parsed_report_has_core_fields(parsed):
                    export_html = self._fetch_export_excel_with_retry(disclosure_key)
                    parsed_export = parse_financial_report_html(export_html)
                    if _parsed_report_has_core_fields(parsed_export):
                        parsed = parsed_export
                if not _parsed_report_has_core_fields(parsed):
                    parsed_attachment = self._fetch_and_parse_attachment_reports_with_retry(
                        disclosure_key=disclosure_key,
                        report_page_html=response.text,
                    )
                    if parsed_attachment is not None and _parsed_report_has_core_fields(parsed_attachment):
                        parsed = parsed_attachment
                self._parsed_report_cache[disclosure_key] = parsed
                return parsed
            except Exception as error:
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(self.backoff_seconds * attempt)
                    continue
        raise RuntimeError(
            f"disclosure={disclosure_index} parse_failed retries={self.max_retries}: {last_error}"
        ) from last_error

    def _fetch_and_parse_attachment_reports_with_retry(
        self,
        disclosure_key: str,
        report_page_html: str,
    ) -> ParsedFinancialReport | None:
        attachment_urls = _extract_attachment_urls(report_page_html, disclosure_key)
        for attachment_url in attachment_urls:
            try:
                attachment_texts = self._fetch_attachment_texts_with_retry(attachment_url)
                for attachment_text in attachment_texts:
                    parsed = parse_financial_report_html(attachment_text)
                    if _parsed_report_has_core_fields(parsed):
                        return parsed
            except Exception:
                continue
        return None

    def _fetch_attachment_texts_with_retry(self, attachment_url: str) -> list[str]:
        response = self._get_with_retry(
            attachment_url,
            f"attachment_fetch_failed url={attachment_url}",
        )
        content = response.content
        if attachment_url.lower().endswith(".zip") or _looks_like_zip(content):
            return _decode_zip_text_files(content)
        return [content.decode("utf-8", errors="ignore")]

    def _fetch_disclosures_from_file_by_year(
        self,
        company_id: str | None,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        if not company_id:
            raise RuntimeError("missing_company_id")

        disclosures = []
        seen_ids = set()
        parse_failures = []
        for year in range(start_date.year, end_date.year + 1):
            report_ids = self._fetch_report_ids_for_year(company_id, year)
            for report_id in report_ids:
                if report_id in seen_ids:
                    continue
                seen_ids.add(report_id)

                try:
                    report_html = self._fetch_export_excel_with_retry(report_id)
                    metadata = _parse_export_excel_metadata(report_html)
                    if metadata["disclosure_type"] != "FR":
                        continue

                    announcement_datetime = metadata["announcement_datetime"]
                    if announcement_datetime is None:
                        continue
                    if announcement_datetime.date() < start_date or announcement_datetime.date() > end_date:
                        continue

                    parsed_report = parse_financial_report_html(report_html)
                    self._parsed_report_cache[report_id] = parsed_report
                    disclosures.append(
                        {
                            "disclosureIndex": int(report_id),
                            "publishDateTime": announcement_datetime.isoformat(),
                            "publishDate": announcement_datetime.isoformat(),
                            "periodEndDate": metadata["period_end"].isoformat() if metadata["period_end"] is not None else None,
                            "year": metadata["fiscal_year"],
                            "ruleType": metadata["fiscal_period"],
                            "financialTableType": metadata["statement_type"],
                            "statementType": metadata["statement_type"],
                        }
                    )
                except Exception as error:
                    parse_failures.append(f"{report_id}: {error}")
                    continue

        disclosures.sort(key=lambda disclosure: str(disclosure.get("publishDateTime") or ""))
        if not disclosures and parse_failures:
            raise RuntimeError(f"file_by_year_no_valid_fr_disclosure; errors={parse_failures[:3]}")
        return disclosures

    def _disclosure_has_financial_tables(self, disclosure_index: int | str) -> bool:
        disclosure_key = str(disclosure_index)
        cached = self._disclosure_financial_table_cache.get(disclosure_key)
        if cached is not None:
            return cached

        has_tables = False
        try:
            response = self._get_with_retry(
                f"https://www.kap.org.tr/tr/Bildirim/{disclosure_key}",
                f"disclosure={disclosure_key} page_fetch_failed",
            )
            has_tables = self._report_html_has_financial_tables(response.text)
        except Exception:
            has_tables = False

        if not has_tables:
            try:
                export_html = self._fetch_export_excel_with_retry(disclosure_key)
                has_tables = self._report_html_has_financial_tables(export_html)
            except Exception:
                has_tables = False

        self._disclosure_financial_table_cache[disclosure_key] = has_tables
        return has_tables

    def _report_html_has_financial_tables(self, html: str) -> bool:
        text = html.lower()
        return (
            "financial-table" in text
            or "taxonomy-field-name" in text
            or "taxonomy-context-value" in text
            or "ifrs-full_" in text
        )

    def _fetch_report_ids_for_year(self, company_id: str, year: int) -> list[str]:
        response = self._get_with_retry(
            f"https://www.kap.org.tr/tr/api/batch-news/file-by-year/{company_id}/{year}",
            f"file_by_year_fetch_failed year={year}",
        )
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            if not names:
                return []
            content = archive.read(names[0])
        text = content.decode("utf-8", errors="ignore")
        if "/Bildirim/" not in text:
            text = content.decode("latin-1", errors="ignore")
        report_ids = re.findall(r"/Bildirim/(\d+)", text)
        return sorted(set(report_ids))

    def _fetch_export_excel_with_retry(self, disclosure_index: str) -> str:
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._get_with_retry(
                    f"https://www.kap.org.tr/tr/api/notification/export/excel/{disclosure_index}",
                    f"disclosure={disclosure_index} export_excel_failed",
                )
                return response.content.decode("utf-8", errors="ignore")
            except Exception as error:
                if _is_name_resolution_error(error):
                    raise KapNameResolutionError(str(error)) from error
                last_error = error
                if attempt < self.max_retries:
                    sleep_seconds = self.backoff_seconds * attempt
                    if "429" in str(error):
                        sleep_seconds = max(sleep_seconds, self.rate_limit_sleep_seconds * attempt)
                    time.sleep(sleep_seconds)
                    continue
        raise RuntimeError(
            f"disclosure={disclosure_index} export_excel_failed retries={self.max_retries}: {last_error}"
        ) from last_error

    def _get_with_retry(self, url: str, context: str):
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._respect_request_interval()
                response = requests.get(url, timeout=self.request_timeout_seconds)
                self._last_request_monotonic = time.monotonic()
                if response.status_code == 429:
                    retry_after_header = response.headers.get("Retry-After")
                    retry_after_seconds = _parse_retry_after_seconds(retry_after_header)
                    wait_seconds = max(self.rate_limit_sleep_seconds, retry_after_seconds or 0.0)
                    time.sleep(wait_seconds)
                    last_error = RuntimeError(f"429 Client Error: Request Limit Exceeded for url: {url}")
                    continue
                response.raise_for_status()
                return response
            except Exception as error:
                if _is_name_resolution_error(error):
                    curl_response = self._curl_get_with_resolve(url)
                    if curl_response is not None:
                        self._last_request_monotonic = time.monotonic()
                        return curl_response
                    raise KapNameResolutionError(str(error)) from error
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(self.backoff_seconds * attempt)
                    continue
        raise RuntimeError(f"{context} retries={self.max_retries}: {last_error}") from last_error

    def _respect_request_interval(self) -> None:
        if self._last_request_monotonic is None:
            return
        elapsed = time.monotonic() - self._last_request_monotonic
        if elapsed < self.min_request_interval_seconds:
            time.sleep(self.min_request_interval_seconds - elapsed)

    def _curl_get_with_resolve(self, url: str):
        ip_candidates = ["185.53.60.150", "185.53.61.150"]
        for ip in ip_candidates:
            command = [
                "curl",
                "-sS",
                "-L",
                "--resolve",
                f"www.kap.org.tr:443:{ip}",
                "--max-time",
                str(self.request_timeout_seconds),
                url,
            ]
            try:
                content = subprocess.check_output(command, stderr=subprocess.STDOUT)
                text = content.decode("utf-8", errors="ignore")
                return _SimpleResponse(
                    status_code=200,
                    content=content,
                    text=text,
                    headers={},
                )
            except Exception:
                continue
        return None


def _parse_announcement_datetime(disclosure: dict) -> datetime | None:
    for key in ["publishDate", "publishDateTime", "disclosureTime", "date"]:
        value = disclosure.get(key)
        if value:
            parsed = pd.to_datetime(value, errors="coerce")
            return None if pd.isna(parsed) else parsed.to_pydatetime()
    return None


def _parse_period_end(disclosure: dict):
    for key in ["periodEndDate", "donemSonu", "period"]:
        value = disclosure.get(key)
        if value:
            parsed = pd.to_datetime(value, errors="coerce")
            return None if pd.isna(parsed) else parsed.date()
    year = disclosure.get("year")
    term = str(disclosure.get("ruleType") or disclosure.get("ruleTypeTerm") or "")
    if year and "3" in term:
        return datetime(int(year), 3, 31).date()
    if year and "6" in term:
        return datetime(int(year), 6, 30).date()
    if year and "9" in term:
        return datetime(int(year), 9, 30).date()
    if year:
        return datetime(int(year), 12, 31).date()
    return None


def _is_consolidated(disclosure: dict) -> bool:
    text = " ".join(str(disclosure.get(key, "")) for key in ["financialTableType", "statementType", "title"]).lower()
    return "konsolide" in text or "consolidated" in text


def _normalize_items(statement_id: str, symbol: str, raw_items: dict) -> list[dict]:
    normalized = []
    for item_code, aliases in ITEM_ALIASES.items():
        matches = [(name, raw_items[name]) for name in aliases if name in raw_items]
        if item_code == "total_debt":
            value = sum(float(value or 0) for _, value in matches)
            item_name = "+".join(name for name, _ in matches)
        elif matches:
            item_name, value = matches[0]
        else:
            continue
        normalized.append(
            {
                "statement_id": statement_id,
                "symbol": symbol.upper(),
                "item_code": item_code,
                "item_name": item_name,
                "value": float(value or 0),
            }
        )
    return normalized


def _items_from_parsed_report(statement_id: str, symbol: str, values: dict[str, float]) -> list[dict]:
    return [
        {
            "statement_id": statement_id,
            "symbol": symbol.upper(),
            "item_code": item_code,
            "item_name": item_code,
            "value": float(value),
        }
        for item_code, value in values.items()
    ]


def _parse_export_excel_metadata(report_html: str) -> dict:
    announcement_datetime = None
    period_end = None
    fiscal_year = None
    fiscal_period = None
    disclosure_type = None
    statement_type = None

    announcement_match = re.search(r"Gönderim Tarihi\s*:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})", report_html)
    if announcement_match is not None:
        parsed = pd.to_datetime(announcement_match.group(1), dayfirst=True, errors="coerce")
        if not pd.isna(parsed):
            announcement_datetime = parsed.to_pydatetime()

    period_match = re.search(r"Cari Dönem\s*<br>\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})", report_html)
    if period_match is not None:
        parsed_period = pd.to_datetime(period_match.group(1), dayfirst=True, errors="coerce")
        if not pd.isna(parsed_period):
            period_end = parsed_period.date()

    disclosure_type_match = re.search(r"Bildirim Tipi\s*:\s*([A-Za-z]+)", report_html)
    if disclosure_type_match is not None:
        disclosure_type = disclosure_type_match.group(1).upper()

    year_match = re.search(r"Yıl\s*:\s*([0-9]{4})", report_html)
    if year_match is not None:
        fiscal_year = int(year_match.group(1))

    period_value_match = re.search(r"Periyot\s*:\s*([0-9]+)", report_html)
    if period_value_match is not None:
        period_value = period_value_match.group(1)
        fiscal_period = f"Q{period_value}"

    statement_type_match = re.search(
        r"Finansal Tablo Niteliği</td>\s*<td>([^<]+)</td>",
        report_html,
        flags=re.IGNORECASE,
    )
    if statement_type_match is not None:
        statement_type = statement_type_match.group(1).strip()

    return {
        "announcement_datetime": announcement_datetime,
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "disclosure_type": disclosure_type,
        "statement_type": statement_type,
    }


def _parse_retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return float(parsed)


def _parse_publish_datetime_value(value: str):
    text = str(value)
    if "." in text and "-" not in text:
        return pd.to_datetime(text, dayfirst=True, errors="coerce")
    return pd.to_datetime(text, errors="coerce")


def _extract_attachment_urls(report_page_html: str, disclosure_key: str) -> list[str]:
    soup = BeautifulSoup(report_page_html, "html.parser")
    urls = set()
    for link in soup.find_all("a", href=True):
        href = str(link.get("href", "")).strip()
        if not href:
            continue
        lower_href = href.lower()
        if "attachment" not in lower_href and not any(ext in lower_href for ext in [".xbrl", ".xml", ".xhtml", ".zip"]):
            continue
        if href.startswith("/"):
            href = f"https://www.kap.org.tr{href}"
        elif href.startswith("http://"):
            href = f"https://{href[len('http://'):]}"
        if "disclosureindex" not in lower_href and disclosure_key not in lower_href and "/api/notification/" not in lower_href:
            pass
        urls.add(href)

    raw_matches = re.findall(
        r'https?://[^"\']+(?:attachment|xbrl|xml|xhtml|zip)[^"\']*',
        report_page_html,
        flags=re.IGNORECASE,
    )
    for match in raw_matches:
        urls.add(match.replace("http://", "https://"))

    return sorted(urls)


def _looks_like_zip(content: bytes) -> bool:
    return content.startswith(b"PK\x03\x04")


def _decode_zip_text_files(content: bytes) -> list[str]:
    extracted = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            if not any(name.lower().endswith(ext) for ext in [".xml", ".xbrl", ".xhtml", ".html", ".htm", ".txt"]):
                continue
            payload = archive.read(name)
            extracted.append(payload.decode("utf-8", errors="ignore"))
    return extracted


def _is_name_resolution_error(error: Exception) -> bool:
    message = str(error).lower()
    patterns = [
        "nameresolutionerror",
        "failed to resolve",
        "nodename nor servname",
        "temporary failure in name resolution",
        "name or service not known",
        "getaddrinfo failed",
    ]
    return any(pattern in message for pattern in patterns)


def _parsed_report_has_core_fields(parsed: ParsedFinancialReport) -> bool:
    return (
        parsed.net_income is not None
        and parsed.equity is not None
        and parsed.operating_profit is not None
        and parsed.shares_outstanding is not None
    )


def _extract_financial_report_indexes(search_html: str, target_symbol: str) -> list[dict]:
    pattern = re.compile(
        r'"publishDate":"([^"]+)","disclosureIndex":(\d+).*?'
        r'"stockCode":"([^"]+)".*?'
        r'"title":"([^"]+)".*?'
        r'"year":(\d+),"period":(\d+),"donem":"([^"]+)"',
        re.S,
    )
    rows = []
    for publish_date, disclosure_index, stock_code, title, year, period, donem in pattern.findall(search_html):
        if stock_code.upper() != target_symbol:
            continue
        if title != "Finansal Rapor":
            continue
        period_value = int(period)
        if period_value not in {3, 6, 9, 12}:
            continue
        rows.append(
            {
                "disclosure_index": int(disclosure_index),
                "stock_code": stock_code,
                "year": int(year),
                "period": _period_to_quarter(period_value),
                "period_label": donem,
                "publish_date": publish_date,
            }
        )
    unique = {}
    for row in rows:
        unique[row["disclosure_index"]] = row
    if unique:
        return sorted(unique.values(), key=lambda row: row["publish_date"])

    return _extract_financial_report_indexes_from_table(search_html, target_symbol)


def _period_to_quarter(period: int) -> int:
    if period == 3:
        return 1
    if period == 6:
        return 2
    if period == 9:
        return 3
    return 4


def _period_end_from_year_period(year: int, quarter: int) -> date:
    if quarter == 1:
        return date(year, 3, 31)
    if quarter == 2:
        return date(year, 6, 30)
    if quarter == 3:
        return date(year, 9, 30)
    return date(year, 12, 31)


def _extract_financial_report_indexes_from_table(search_html: str, target_symbol: str) -> list[dict]:
    soup = BeautifulSoup(search_html, "html.parser")
    rows = []
    for tr in soup.select("tr[id^=notification]"):
        text = tr.get_text(" ", strip=True)
        if "Finansal Rapor" not in text:
            continue
        if target_symbol not in text:
            continue
        checkbox = tr.select_one("input[type='checkbox'][id]")
        if checkbox is None:
            continue
        disclosure_id = checkbox.get("id")
        if disclosure_id is None or not disclosure_id.isdigit():
            continue

        date_match = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", text)
        time_match = re.search(r"\b(\d{2}:\d{2})\b", text)
        publish_datetime_text = None
        if date_match is not None:
            publish_datetime_text = date_match.group(1)
            if time_match is not None:
                publish_datetime_text = f"{publish_datetime_text} {time_match.group(1)}"

        year_match = re.search(r"\b(20\d{2})\b", text)
        period_match = re.search(r"\b(3|6|9|12)\s*Aylık\b", text)
        if year_match is None or period_match is None or publish_datetime_text is None:
            continue

        rows.append(
            {
                "disclosure_index": int(disclosure_id),
                "stock_code": target_symbol,
                "year": int(year_match.group(1)),
                "period": _period_to_quarter(int(period_match.group(1))),
                "period_label": period_match.group(0),
                "publish_date": publish_datetime_text,
            }
        )

    unique = {}
    for row in rows:
        unique[row["disclosure_index"]] = row
    return sorted(unique.values(), key=lambda row: row["publish_date"])

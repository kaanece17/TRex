from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Authorization": "Bearer",
}

MKK_API_ROOT = "https://e-sirket.mkk.com.tr/api"


@dataclass(frozen=True)
class MkkEsirketSourceConfig:
    symbol: str
    tax_no: str
    document_type_text: str = "Bilanço"
    source_url: str | None = None


MKK_ESIR_SOURCES: dict[str, MkkEsirketSourceConfig] = {
    "FADE": MkkEsirketSourceConfig(
        symbol="FADE",
        tax_no="3840626610",
        source_url="https://e-sirket.mkk.com.tr/?page=company&company=18366",
    ),
    "ISKPL": MkkEsirketSourceConfig(
        symbol="ISKPL",
        tax_no="4670832685",
        source_url="https://e-sirket.mkk.com.tr/?page=company&company=22732",
    ),
    "OZRDN": MkkEsirketSourceConfig(
        symbol="OZRDN",
        tax_no="4640169234",
        source_url="https://e-sirket.mkk.com.tr/?page=company&company=13893",
    ),
    "BRKSN": MkkEsirketSourceConfig(
        symbol="BRKSN",
        tax_no="1660002899",
        source_url="https://e-sirket.mkk.com.tr/?page=company&company=10576",
    ),
    "DARDL": MkkEsirketSourceConfig(
        symbol="DARDL",
        tax_no="2700055525",
        source_url="https://e-sirket.mkk.com.tr/?page=company&company=11888",
    ),
    "EPLAS": MkkEsirketSourceConfig(
        symbol="EPLAS",
        tax_no="3250067473",
        source_url="https://e-sirket.mkk.com.tr/?page=company&company=10718",
    ),
    "HATEK": MkkEsirketSourceConfig(
        symbol="HATEK",
        tax_no="4590012972",
        source_url="https://e-sirket.mkk.com.tr/?page=company&company=11256",
    ),
}


class MkkEsirketAnnouncementsLoader:
    def __init__(self, request_timeout_seconds: int = 30) -> None:
        self.request_timeout_seconds = request_timeout_seconds

    def fetch_records(self, symbol: str) -> list[dict]:
        config = MKK_ESIR_SOURCES.get(symbol.upper())
        if config is None:
            raise ValueError(f"mkk e-sirket fallback is not configured for symbol: {symbol.upper()}")
        revisions = self._fetch_revision_ids(config.tax_no, config.document_type_text)
        if not revisions:
            return []
        metadata_rows = self._fetch_revision_metadata(revisions)
        records: list[dict] = []
        for row in metadata_rows:
            metadata = {item["title"]: item["value"] for item in row.get("documentMetaDataValuePairs", [])}
            period_end = _period_end_from_metadata(metadata)
            announcement_date = _announcement_date_from_metadata(metadata)
            if period_end is None or announcement_date is None:
                continue
            records.append(
                {
                    "symbol": config.symbol,
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": config.source_url or "https://e-sirket.mkk.com.tr/",
                }
            )
        deduplicated: dict[tuple[str, date], dict] = {}
        for record in records:
            deduplicated[(record["symbol"], record["period_end"])] = record
        return list(deduplicated.values())

    def _fetch_revision_ids(self, tax_no: str, document_type_text: str) -> list[str]:
        response = self._request_json(
            "POST",
            f"{MKK_API_ROOT}/dys/findDocumentRevisionWithMetadataFromAllDocumentClasses",
            {"TaxNo": tax_no},
        )
        rows = response.get("data", [])
        for row in rows:
            if row.get("documentTypeText") == document_type_text:
                return [item["id"] for item in row.get("documentRevisionDtoList", [])]
        return []

    def _fetch_revision_metadata(self, revision_ids: list[str]) -> list[dict]:
        response = self._request_json(
            "POST",
            f"{MKK_API_ROOT}/dys/findDocumentMetadataWithDocumentRevision",
            revision_ids,
        )
        return response.get("data", [])

    def _request_json(self, method: str, url: str, payload):
        response = requests.request(
            method,
            url,
            json=payload,
            timeout=self.request_timeout_seconds,
            headers=REQUEST_HEADERS,
        )
        response.raise_for_status()
        return response.json()


def _period_end_from_metadata(metadata: dict[str, str]) -> date | None:
    year_raw = metadata.get("Yıl")
    period_raw = metadata.get("Dönem")
    if not year_raw or not period_raw:
        return None
    quarter_map = {"1.Dönem": 3, "2.Dönem": 6, "3.Dönem": 9, "4.Dönem": 12}
    month = quarter_map.get(period_raw)
    if month is None:
        return None
    try:
        year = int(year_raw)
    except ValueError:
        return None
    return date(year, month, 1)


def _announcement_date_from_metadata(metadata: dict[str, str]) -> date | None:
    raw_value = metadata.get("Yükleme Tarihi")
    if not raw_value:
        return None
    try:
        if raw_value.isdigit() and len(raw_value) == 14:
            return pd.to_datetime(raw_value, format="%Y%m%d%H%M%S").date()
        return pd.to_datetime(raw_value, dayfirst=True).date()
    except Exception:
        return None

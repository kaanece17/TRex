from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
from io import BytesIO
import re
from typing import Iterable
import unicodedata

from bs4 import BeautifulSoup
import pandas as pd
from pypdf import PdfReader
from requests import Session


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

REGISTRY_COLUMNS = [
    "symbol",
    "period_end",
    "fiscal_year",
    "fiscal_period",
    "source_type",
    "source_url",
    "announcement_date",
    "is_active",
    "notes",
]

LINE_ITEM_ALIASES = {
    "equity": (
        "toplam ozkaynaklar",
        "total equity",
    ),
    "net_income": (
        "net donem kari (zarari)",
        "donem kari (zarari)",
        "current period net profit or loss",
        "profit (loss) attributable to owners of parent",
        "ana ortakliga ait net donem kari (zarari)",
    ),
    "operating_profit": (
        "esas faaliyet kari (zarari)",
        "profit (loss) from operating activities",
        "profit (loss) before financing income (expense)",
        "finansman geliri (gideri) oncesi faaliyet kari (zarari)",
    ),
    "cash": (
        "nakit ve nakit benzerleri",
        "cash and cash equivalents",
    ),
    "shares_outstanding": (
        "odenmis sermaye",
        "issued capital",
    ),
}

DEBT_COMPONENT_ALIASES = (
    "kisa vadeli borclanmalar",
    "uzun vadeli borclanmalarin kisa vadeli kisimlari",
    "uzun vadeli borclanmalar",
    "kiralama islemlerinden kaynaklanan yukumlulukler",
    "financial liabilities",
    "short-term borrowings",
    "current portions of long-term borrowings",
    "long-term borrowings",
    "lease liabilities",
)

REQUIRED_VALUES = ("equity", "net_income", "operating_profit")
PDF_LINE_ITEM_ALIASES = {
    "equity": (
        "toplam ozkaynaklar",
        "total equity",
    ),
    "net_income": (
        "donem kari / (zarari)",
        "net donem kari / (zarari)",
        "donem kari (zarari)",
    ),
    "operating_profit": (
        "esas faaliyet kari",
        "esas faaliyet kari (zarari)",
    ),
    "cash": (
        "nakit ve nakit benzerleri",
    ),
    "shares_outstanding": (
        "odenmis sermaye",
    ),
}
PDF_DEBT_LINE_ALIASES = (
    "kisa vadeli borclanmalar",
    "uzun vadeli borclanmalarin kisa vadeli kisimlari",
    "uzun vadeli borclanmalar",
)


@dataclass(frozen=True)
class FinancialFallbackRegistryEntry:
    symbol: str
    period_end: date
    fiscal_year: int
    fiscal_period: str
    source_type: str
    source_url: str
    announcement_date: date | None
    is_active: bool = True
    notes: str | None = None


class FinancialFallbackRegistryLoader:
    def __init__(self, request_timeout_seconds: int = 25):
        self.request_timeout_seconds = request_timeout_seconds
        self.session = Session()
        self.session.headers.update(REQUEST_HEADERS)

    def build_record(self, entry: FinancialFallbackRegistryEntry) -> dict:
        if entry.source_type == "financialreports_filing":
            return self._build_from_financialreports_filing(entry)
        if entry.source_type == "issuer_ir_pdf_text":
            return self._build_from_issuer_ir_pdf_text(entry)
        raise ValueError(f"unsupported fallback source_type: {entry.source_type}")

    def _build_from_financialreports_filing(self, entry: FinancialFallbackRegistryEntry) -> dict:
        response = self.session.get(entry.source_url, timeout=self.request_timeout_seconds)
        response.raise_for_status()
        response.encoding = "utf-8"
        cdn_url = _extract_direct_cdn_document_url(response.text)
        source_html = response.text
        if cdn_url and cdn_url.endswith(".html"):
            cdn_response = self.session.get(cdn_url, timeout=self.request_timeout_seconds)
            cdn_response.raise_for_status()
            cdn_response.encoding = "utf-8"
            source_html = cdn_response.text
        soup = BeautifulSoup(source_html, "html.parser")
        values = self._extract_financialreports_values(soup)
        missing = [key for key in REQUIRED_VALUES if values.get(key) is None]
        if missing:
            raise ValueError(
                f"missing required fallback values for {entry.symbol} {entry.period_end.isoformat()}: {', '.join(missing)}"
            )

        statement_id = f"FALLBACK-{entry.symbol}-{entry.period_end:%Y%m%d}"
        raw_hash = hashlib.sha1(
            f"{entry.symbol}|{entry.period_end.isoformat()}|{entry.source_url}|{entry.announcement_date}".encode("utf-8")
        ).hexdigest()
        announcement_date = entry.announcement_date
        announcement_datetime = (
            datetime.combine(announcement_date, datetime.min.time(), tzinfo=UTC)
            if announcement_date is not None
            else None
        )

        return {
            "statement_id": statement_id,
            "symbol": entry.symbol,
            "period_end": entry.period_end,
            "fiscal_year": entry.fiscal_year,
            "fiscal_period": entry.fiscal_period,
            "statement_type": "financial_statement",
            "announcement_datetime": announcement_datetime,
            "announcement_date": announcement_date,
            "currency": "TRY",
            "is_consolidated": True,
            "is_revised": False,
            "source_url": entry.source_url,
            "announcement_source_url": entry.source_url,
            "raw_hash": raw_hash,
            "created_at": datetime.now(UTC),
            "shares_outstanding": values.get("shares_outstanding"),
            "shares_announcement_datetime": announcement_datetime,
            "shares_source_url": entry.source_url,
            "net_income": values.get("net_income"),
            "equity": values.get("equity"),
            "operating_profit": values.get("operating_profit"),
            "cash": values.get("cash"),
            "total_debt": values.get("total_debt"),
        }

    def _build_from_issuer_ir_pdf_text(self, entry: FinancialFallbackRegistryEntry) -> dict:
        response = self.session.get(entry.source_url, timeout=self.request_timeout_seconds)
        response.raise_for_status()
        reader = PdfReader(BytesIO(response.content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        values = self._extract_issuer_ir_pdf_text_values(text)
        missing = [key for key in REQUIRED_VALUES if values.get(key) is None]
        if missing:
            raise ValueError(
                f"missing required fallback values for {entry.symbol} {entry.period_end.isoformat()}: {', '.join(missing)}"
            )

        statement_id = f"FALLBACK-{entry.symbol}-{entry.period_end:%Y%m%d}"
        raw_hash = hashlib.sha1(
            f"{entry.symbol}|{entry.period_end.isoformat()}|{entry.source_url}|{entry.announcement_date}".encode("utf-8")
        ).hexdigest()
        announcement_date = entry.announcement_date
        announcement_datetime = (
            datetime.combine(announcement_date, datetime.min.time(), tzinfo=UTC)
            if announcement_date is not None
            else None
        )

        return {
            "statement_id": statement_id,
            "symbol": entry.symbol,
            "period_end": entry.period_end,
            "fiscal_year": entry.fiscal_year,
            "fiscal_period": entry.fiscal_period,
            "statement_type": "financial_statement",
            "announcement_datetime": announcement_datetime,
            "announcement_date": announcement_date,
            "currency": "TRY",
            "is_consolidated": True,
            "is_revised": False,
            "source_url": entry.source_url,
            "announcement_source_url": entry.source_url,
            "raw_hash": raw_hash,
            "created_at": datetime.now(UTC),
            "shares_outstanding": values.get("shares_outstanding"),
            "shares_announcement_datetime": announcement_datetime,
            "shares_source_url": entry.source_url,
            "net_income": values.get("net_income"),
            "equity": values.get("equity"),
            "operating_profit": values.get("operating_profit"),
            "cash": values.get("cash"),
            "total_debt": values.get("total_debt"),
        }

    def _extract_financialreports_values(self, soup: BeautifulSoup) -> dict[str, float | None]:
        rows = list(_iter_table_rows(soup))
        values: dict[str, float | None] = {key: None for key in (*LINE_ITEM_ALIASES.keys(), "total_debt")}
        normalized_debt_aliases = tuple(_normalize_text(alias) for alias in DEBT_COMPONENT_ALIASES)
        for item_code, aliases in LINE_ITEM_ALIASES.items():
            row = _find_first_matching_row(rows, aliases)
            if row is None:
                continue
            numbers = _extract_numeric_cells(row)
            if len(numbers) >= 2:
                values[item_code] = numbers[-2]
            elif numbers:
                values[item_code] = numbers[-1]

        debt_total = 0.0
        found_debt = False
        for row in rows:
            normalized_cells = [_normalize_text(cell) for cell in row]
            if not any(alias in " ".join(normalized_cells) for alias in normalized_debt_aliases):
                continue
            numbers = _extract_numeric_cells(row)
            if len(numbers) >= 2:
                debt_total += numbers[-2]
                found_debt = True
            elif numbers:
                debt_total += numbers[-1]
                found_debt = True
        values["total_debt"] = debt_total if found_debt else None
        return values

    def _extract_issuer_ir_pdf_text_values(self, text: str) -> dict[str, float | None]:
        normalized_lines = [_normalize_text(line) for line in text.splitlines()]
        raw_lines = [line.strip() for line in text.splitlines()]
        values: dict[str, float | None] = {key: None for key in (*PDF_LINE_ITEM_ALIASES.keys(), "total_debt")}

        for item_code, aliases in PDF_LINE_ITEM_ALIASES.items():
            values[item_code] = _extract_pdf_line_value(raw_lines, normalized_lines, aliases)

        debt_total = 0.0
        found_debt = False
        for raw_line, normalized_line in zip(raw_lines, normalized_lines, strict=False):
            if not any(alias in normalized_line for alias in PDF_DEBT_LINE_ALIASES):
                continue
            line_values = _extract_pdf_line_numbers(raw_line)
            if not line_values:
                continue
            debt_total += line_values[0]
            found_debt = True
        values["total_debt"] = debt_total if found_debt else None
        return values


def load_financial_fallback_registry(path: str) -> list[FinancialFallbackRegistryEntry]:
    frame = pd.read_csv(path)
    for column in REGISTRY_COLUMNS:
        if column not in frame.columns:
            raise ValueError(f"missing registry column: {column}")
    frame = frame.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce").dt.date
    frame["announcement_date"] = pd.to_datetime(frame["announcement_date"], errors="coerce").dt.date
    frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce").astype("Int64")
    frame["fiscal_period"] = frame["fiscal_period"].astype(str)
    frame["is_active"] = frame["is_active"].map(_coerce_bool)
    entries: list[FinancialFallbackRegistryEntry] = []
    for row in frame.to_dict(orient="records"):
        if row["period_end"] is None or pd.isna(row["period_end"]):
            raise ValueError(f"invalid period_end in registry row: {row}")
        if row["fiscal_year"] is pd.NA or pd.isna(row["fiscal_year"]):
            raise ValueError(f"invalid fiscal_year in registry row: {row}")
        entries.append(
            FinancialFallbackRegistryEntry(
                symbol=str(row["symbol"]),
                period_end=row["period_end"],
                fiscal_year=int(row["fiscal_year"]),
                fiscal_period=str(row["fiscal_period"]),
                source_type=str(row["source_type"]),
                source_url=str(row["source_url"]),
                announcement_date=row["announcement_date"] if pd.notna(row["announcement_date"]) else None,
                is_active=bool(row["is_active"]),
                notes=str(row["notes"]) if row["notes"] is not None and pd.notna(row["notes"]) else None,
            )
        )
    return entries


def record_to_statement_rows(record: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    statement = pd.DataFrame(
        [
            {
                key: record.get(key)
                for key in [
                    "statement_id",
                    "symbol",
                    "period_end",
                    "fiscal_year",
                    "fiscal_period",
                    "statement_type",
                    "announcement_datetime",
                    "announcement_date",
                    "currency",
                    "is_consolidated",
                    "is_revised",
                    "source_url",
                    "announcement_source_url",
                    "raw_hash",
                    "created_at",
                    "shares_outstanding",
                    "shares_announcement_datetime",
                    "shares_source_url",
                ]
            }
        ]
    )
    item_rows = []
    for item_code in ("net_income", "equity", "operating_profit", "cash", "total_debt"):
        value = record.get(item_code)
        if value is None or pd.isna(value):
            continue
        item_rows.append(
            {
                "statement_id": record["statement_id"],
                "symbol": record["symbol"],
                "item_code": item_code,
                "item_name": item_code,
                "value": value,
            }
        )
    return statement, pd.DataFrame(item_rows)


def _iter_table_rows(soup: BeautifulSoup) -> Iterable[list[str]]:
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                yield cells


def _find_first_matching_row(rows: Iterable[list[str]], aliases: tuple[str, ...]) -> list[str] | None:
    normalized_aliases = tuple(_normalize_text(alias) for alias in aliases)
    fallback_match: list[str] | None = None
    best_numeric_match: tuple[int, list[str]] | None = None
    for row in rows:
        normalized_joined = " ".join(_normalize_text(cell) for cell in row)
        if any(alias in normalized_joined for alias in normalized_aliases):
            numeric_count = len(_extract_numeric_cells(row))
            if numeric_count > 0:
                if best_numeric_match is None or numeric_count > best_numeric_match[0]:
                    best_numeric_match = (numeric_count, row)
                continue
            if fallback_match is None:
                fallback_match = row
    if best_numeric_match is not None:
        return best_numeric_match[1]
    return fallback_match


def _extract_numeric_cells(cells: list[str]) -> list[float]:
    values: list[float] = []
    for cell in cells:
        value = _coerce_float(cell)
        if value is not None:
            values.append(value)
    return values


def _extract_pdf_line_value(raw_lines: list[str], normalized_lines: list[str], aliases: tuple[str, ...]) -> float | None:
    normalized_aliases = tuple(_normalize_text(alias) for alias in aliases)
    for raw_line, normalized_line in zip(raw_lines, normalized_lines, strict=False):
        if not any(alias in normalized_line for alias in normalized_aliases):
            continue
        values = _extract_pdf_line_numbers(raw_line)
        if values:
            return values[0]
    return None


def _extract_pdf_line_numbers(line: str) -> list[float]:
    matches = re.findall(r"\(?-?\d[\d.]*,\d+|\(?-?\d[\d.]*\)?", line)
    numbers = [_coerce_float(match) for match in matches]
    values = [number for number in numbers if number is not None]
    if len(values) >= 2 and abs(values[0]) < 1000:
        values = values[1:]
    return values


def _coerce_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return None
    text = text.replace("\xa0", " ").replace("−", "-")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9,().-]", "", text)
    if text == "":
        return None
    is_negative = text.startswith("(") and text.endswith(")")
    if is_negative:
        text = text[1:-1]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," not in text and text.count(".") > 1:
        text = text.replace(".", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        result = float(text)
    except ValueError:
        return None
    return -result if is_negative else result


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
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
    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "evet"}


def _extract_direct_cdn_document_url(html: str) -> str | None:
    match = re.search(
        r"https://cdn\.financialreports\.eu/financialreports/media/filings/[^\"']+\.(?:html|pdf)",
        html,
    )
    if match is None:
        return None
    return match.group(0)

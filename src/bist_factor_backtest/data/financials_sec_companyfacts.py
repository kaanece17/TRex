from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import time

import pandas as pd
import requests


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

SUPPORTED_FORMS = {"10-K", "10-Q"}
ITEM_CONCEPTS = {
    "net_income": [
        ("us-gaap", "NetIncomeLoss"),
        ("us-gaap", "ProfitLoss"),
        ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic"),
        ("us-gaap", "IncomeLossFromContinuingOperations"),
    ],
    "equity": [
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ("us-gaap", "StockholdersEquity"),
    ],
    "operating_profit": [
        ("us-gaap", "OperatingIncomeLoss"),
        ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
        ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
        ("us-gaap", "PretaxIncome"),
    ],
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations"),
    ],
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "SalesRevenueNet"),
        ("us-gaap", "Revenues"),
    ],
    "total_assets": [
        ("us-gaap", "Assets"),
    ],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    ],
    "shares_outstanding": [
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
        ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
        ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic"),
    ],
}
TOTAL_DEBT_DIRECT_CONCEPTS = [
    ("us-gaap", "DebtAndFinanceLeaseObligations"),
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligations"),
    ("us-gaap", "LongTermDebtAndCapitalLeaseObligations"),
    ("us-gaap", "DebtLongtermAndShorttermCombinedAmount"),
    ("us-gaap", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"),
]
TOTAL_DEBT_SUM_COMPONENTS = [
    ("us-gaap", "LongTermDebtCurrent"),
    ("us-gaap", "DebtCurrent"),
    ("us-gaap", "ShortTermBorrowings"),
    ("us-gaap", "LongTermDebtNoncurrent"),
    ("us-gaap", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
]


@dataclass(frozen=True)
class SECFinancialLoadResult:
    statements: pd.DataFrame
    items: pd.DataFrame
    failures: pd.DataFrame


class SECCompanyFactsFinancialLoader:
    def __init__(
        self,
        *,
        user_agent: str | None = None,
        request_timeout_seconds: int = 20,
        min_request_interval_seconds: float = 0.2,
    ):
        self.request_timeout_seconds = request_timeout_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent or "TRex Research support@trex.local",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._last_request_at: float | None = None
        self._ticker_map: dict[str, str] | None = None

    def load(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> SECFinancialLoadResult:
        statement_rows: list[dict[str, object]] = []
        item_rows: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        ticker_map = self._load_ticker_map()
        for symbol in symbols:
            symbol_upper = str(symbol).upper()
            cik = ticker_map.get(symbol_upper)
            if cik is None:
                failures.append({"symbol": symbol_upper, "reason": "sec_ticker_not_found", "detail": None})
                continue
            try:
                submissions = self._get_json(SEC_SUBMISSIONS_URL.format(cik=cik))
                company_facts = self._get_json(SEC_COMPANY_FACTS_URL.format(cik=cik))
            except Exception as error:
                failures.append({"symbol": symbol_upper, "reason": "sec_fetch_failed", "detail": str(error)})
                continue

            filings = _recent_supported_filings(submissions, start_date, end_date)
            if not filings:
                failures.append({"symbol": symbol_upper, "reason": "sec_no_supported_filings", "detail": None})
                continue

            facts_index = _build_company_facts_index(company_facts)
            built_any = False
            for filing in filings:
                statement_row, filing_items = _build_filing_rows(symbol_upper, cik, filing, facts_index)
                if statement_row is None:
                    continue
                built_any = True
                statement_rows.append(statement_row)
                item_rows.extend(filing_items)
            if not built_any:
                failures.append({"symbol": symbol_upper, "reason": "sec_missing_required_facts", "detail": None})

        return SECFinancialLoadResult(
            statements=pd.DataFrame(statement_rows),
            items=pd.DataFrame(item_rows),
            failures=pd.DataFrame(failures),
        )

    def _load_ticker_map(self) -> dict[str, str]:
        if self._ticker_map is not None:
            return self._ticker_map
        payload = self._get_json(SEC_TICKERS_URL)
        mapping: dict[str, str] = {}
        if isinstance(payload, dict) and "fields" in payload and "data" in payload:
            fields = [str(field) for field in payload.get("fields", [])]
            for values in payload.get("data", []):
                row = dict(zip(fields, values, strict=False))
                ticker = str(row.get("ticker", "")).upper()
                cik = str(row.get("cik", "")).strip()
                if ticker and cik:
                    mapping[ticker] = cik.zfill(10)
        else:
            for row in payload.values():
                ticker = str(row.get("ticker", "")).upper()
                cik = str(row.get("cik_str", "")).strip()
                if ticker and cik:
                    mapping[ticker] = cik.zfill(10)
        self._ticker_map = mapping
        return mapping

    def _get_json(self, url: str) -> dict:
        now = time.monotonic()
        if self._last_request_at is not None:
            wait = self.min_request_interval_seconds - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        response = self.session.get(url, timeout=self.request_timeout_seconds)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.json()


def _recent_supported_filings(submissions: dict, start_date: date, end_date: date) -> list[dict[str, object]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    acceptance_times = recent.get("acceptanceDateTime", [])
    fy_values = recent.get("fiscalYearEnd", [])
    fp_values = recent.get("reportDate", [])
    rows: list[dict[str, object]] = []
    for index, form in enumerate(forms):
        if form not in SUPPORTED_FORMS:
            continue
        filing_date = _coerce_date(_safe_get(filing_dates, index))
        report_date = _coerce_date(_safe_get(report_dates, index))
        if filing_date is None or report_date is None:
            continue
        if report_date < start_date or report_date > end_date:
            continue
        accession_number = _safe_get(accession_numbers, index)
        acceptance_raw = _safe_get(acceptance_times, index)
        acceptance_dt = _coerce_acceptance_datetime(acceptance_raw)
        fiscal_year = report_date.year
        fiscal_period = "FY" if form == "10-K" else f"Q{((report_date.month - 1) // 3) + 1}"
        rows.append(
            {
                "form": form,
                "accession_number": accession_number,
                "filing_date": filing_date,
                "report_date": report_date,
                "acceptance_datetime": acceptance_dt,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period,
                "fiscal_year_end": _safe_get(fy_values, index),
                "report_date_raw": _safe_get(fp_values, index),
            }
        )
    rows.sort(key=lambda row: (row["report_date"], row["filing_date"], row.get("acceptance_datetime") or datetime.min))
    return rows


def _build_company_facts_index(company_facts: dict) -> dict[tuple[str, str], list[dict[str, object]]]:
    facts = company_facts.get("facts", {})
    index: dict[tuple[str, str], list[dict[str, object]]] = {}
    for taxonomy, concepts in facts.items():
        for concept_name, payload in concepts.items():
            rows: list[dict[str, object]] = []
            for _, values in payload.get("units", {}).items():
                rows.extend(values)
            index[(taxonomy, concept_name)] = rows
    return index


def _build_filing_rows(
    symbol: str,
    cik: str,
    filing: dict[str, object],
    facts_index: dict[tuple[str, str], list[dict[str, object]]],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    accession = str(filing["accession_number"])
    report_date = filing["report_date"]
    filing_date = filing["filing_date"]
    acceptance_dt = filing["acceptance_datetime"]

    item_values: dict[str, float | None] = {}
    for item_code, concepts in ITEM_CONCEPTS.items():
        item_values[item_code] = _extract_filing_fact(
            facts_index,
            concepts,
            accession=accession,
            report_date=report_date,
            filing_date=filing_date,
        )
    item_values["total_debt"] = _extract_total_debt(
        facts_index,
        accession=accession,
        report_date=report_date,
        filing_date=filing_date,
    )

    required = ("net_income", "equity", "operating_profit")
    if any(item_values[item] is None for item in required):
        return None, []

    accession_normalized = accession.replace("-", "")
    source_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_normalized}/"
    statement_id = f"SEC-{symbol}-{report_date:%Y%m%d}-{accession_normalized}"
    raw_hash = hashlib.sha256(f"{symbol}|{accession}|{report_date.isoformat()}".encode("utf-8")).hexdigest()

    statement_row = {
        "statement_id": statement_id,
        "symbol": symbol,
        "period_end": report_date,
        "fiscal_year": filing["fiscal_year"],
        "fiscal_period": filing["fiscal_period"],
        "statement_type": "annual" if filing["form"] == "10-K" else "quarterly",
        "announcement_datetime": acceptance_dt,
        "announcement_date": acceptance_dt.date() if acceptance_dt is not None else filing_date,
        "currency": "USD",
        "is_consolidated": True,
        "is_revised": False,
        "source_url": source_url,
        "announcement_source_url": source_url,
        "raw_hash": raw_hash,
        "created_at": datetime.now(UTC),
        "shares_outstanding": item_values["shares_outstanding"],
        "shares_announcement_datetime": acceptance_dt,
        "shares_source_url": source_url,
    }
    item_rows = [
        {
            "statement_id": statement_id,
            "symbol": symbol,
            "item_code": item_code,
            "item_name": item_code,
            "value": value,
        }
        for item_code, value in item_values.items()
        if item_code in {"net_income", "equity", "operating_profit", "cash", "total_debt", "revenue", "total_assets", "operating_cash_flow"} and value is not None
    ]
    return statement_row, item_rows


def _extract_total_debt(
    facts_index: dict[tuple[str, str], list[dict[str, object]]],
    *,
    accession: str,
    report_date: date,
    filing_date: date,
) -> float | None:
    direct = _extract_filing_fact(
        facts_index,
        TOTAL_DEBT_DIRECT_CONCEPTS,
        accession=accession,
        report_date=report_date,
        filing_date=filing_date,
    )
    if direct is not None:
        return direct
    components = [
        _extract_filing_fact(
            facts_index,
            [concept],
            accession=accession,
            report_date=report_date,
            filing_date=filing_date,
        )
        for concept in TOTAL_DEBT_SUM_COMPONENTS
    ]
    present = [value for value in components if value is not None]
    if not present:
        return None
    return float(sum(present))


def _extract_filing_fact(
    facts_index: dict[tuple[str, str], list[dict[str, object]]],
    concepts: list[tuple[str, str]],
    *,
    accession: str,
    report_date: date,
    filing_date: date,
) -> float | None:
    for taxonomy, concept in concepts:
        rows = facts_index.get((taxonomy, concept), [])
        match = _pick_best_fact(rows, accession=accession, report_date=report_date, filing_date=filing_date)
        if match is not None:
            return match
    return None


def _pick_best_fact(rows: list[dict[str, object]], *, accession: str, report_date: date, filing_date: date) -> float | None:
    candidates: list[tuple[int, date, float]] = []
    for row in rows:
        row_accn = str(row.get("accn") or "")
        if row_accn != accession:
            continue
        row_end = _coerce_date(row.get("end"))
        if row_end != report_date:
            continue
        row_filed = _coerce_date(row.get("filed")) or filing_date
        value = _coerce_float(row.get("val"))
        if value is None:
            continue
        score = 0
        if row.get("frame") in (None, ""):
            score += 2
        if _coerce_date(row.get("filed")) == filing_date:
            score += 2
        if str(row.get("fp") or "").upper() in {"FY", f"Q{((report_date.month - 1) // 3) + 1}"}:
            score += 1
        candidates.append((score, row_filed, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return float(candidates[0][2])


def _safe_get(values: list[object], index: int) -> object | None:
    if index >= len(values):
        return None
    return values[index]


def _coerce_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _coerce_acceptance_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) == 14 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d%H%M%S")
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    if getattr(parsed, "tzinfo", None) is not None:
        return parsed.tz_convert(None).to_pydatetime()
    return parsed.to_pydatetime()


def _coerce_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

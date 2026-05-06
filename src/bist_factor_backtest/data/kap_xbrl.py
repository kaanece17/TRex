from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


CONCEPT_CODES = {
    "net_income": [
        "ifrs-full_ProfitLossAttributableToOwnersOfParent",
        "ifrs-full_ProfitLoss",
        "ifrs-full_ProfitLossFromContinuingOperations",
        "kap-fr_NetProfitLoss",
    ],
    "operating_profit": [
        "ifrs-full_ProfitLossFromOperatingActivities",
        "ifrs-full_OperatingProfitLoss",
        "kap-fr_OperatingProfitLoss",
    ],
    "equity": [
        "ifrs-full_EquityAttributableToOwnersOfParent",
        "kap-fr_EquityAttributableToOwnersOfParent",
    ],
    "cash": ["ifrs-full_CashAndCashEquivalents"],
    "shares_outstanding": [
        "ifrs-full_IssuedCapital",
        "kap-fr_PaidInCapital",
        "ifrs-full_NumberOfSharesOutstanding",
    ],
}


@dataclass(frozen=True)
class ParsedFinancialReport:
    net_income: float | None
    operating_profit: float | None
    equity: float | None
    cash: float | None
    total_debt: float
    shares_outstanding: float | None

    def to_items(self) -> dict[str, float]:
        return {
            key: value
            for key, value in {
                "net_income": self.net_income,
                "operating_profit": self.operating_profit,
                "equity": self.equity,
                "cash": self.cash,
                "total_debt": self.total_debt,
                "shares_outstanding": self.shares_outstanding,
            }.items()
            if value is not None
        }


def parse_financial_report_html(html: str) -> ParsedFinancialReport:
    soup = BeautifulSoup(html, "html.parser")
    values: dict[str, float | None] = {field: None for field in CONCEPT_CODES}
    debt_values = []
    for row in soup.find_all("tr"):
        concept = _extract_concept(row)
        if concept is None:
            continue
        value = _extract_numeric_value_from_row(row)
        if value is None:
            continue
        for field, concepts in CONCEPT_CODES.items():
            if values[field] is None and any(concept.startswith(code) for code in concepts):
                values[field] = value
        if _is_debt_concept(concept):
            debt_values.append(value)
    if _missing_core_values(values):
        xbrl_values = _extract_values_from_xbrl_facts(html)
        for key, value in xbrl_values.items():
            if values.get(key) is None:
                values[key] = value
    return ParsedFinancialReport(
        net_income=values["net_income"],
        operating_profit=values["operating_profit"],
        equity=values["equity"],
        cash=values["cash"],
        total_debt=sum(debt_values) if debt_values else 0.0,
        shares_outstanding=values["shares_outstanding"],
    )


def _extract_concept(row) -> str | None:
    concept_element = row.select_one(".taxonomy-field-name")
    if concept_element is not None:
        concept_text = concept_element.get_text(" ", strip=True).rstrip("|")
        if concept_text:
            return concept_text
    text = row.get_text(" | ", strip=True)
    if "ifrs-full_" in text:
        match = re.search(r"(ifrs-full_[A-Za-z0-9]+)", text)
        if match is not None:
            return match.group(1)
    if "kap-fr_" in text:
        match = re.search(r"(kap-fr_[A-Za-z0-9]+)", text)
        if match is not None:
            return match.group(1)
    return None


def _extract_numeric_value_from_row(row) -> float | None:
    value_cells = row.select(".taxonomy-context-value")
    if value_cells:
        parts = [cell.get_text(" ", strip=True) for cell in value_cells]
    else:
        parts = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])][3:]
    for part in parts:
        cleaned = (
            part.replace(".", "")
            .replace(",", ".")
            .replace("(", "-")
            .replace(")", "")
            .replace(" ", "")
        )
        if re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
            return float(cleaned) * 1000
    return None


def _is_debt_concept(concept: str) -> bool:
    return (
        concept.startswith("kap-fr_CurrentBorowings")
        or concept.startswith("kap-fr_NoncurrentBorrowings")
        or concept.startswith("ifrs-full_NoncurrentBorrowings")
    )


def _missing_core_values(values: dict[str, float | None]) -> bool:
    return values["net_income"] is None or values["equity"] is None or values["operating_profit"] is None


def _extract_values_from_xbrl_facts(content: str) -> dict[str, float]:
    extracted = {}
    for field, concepts in CONCEPT_CODES.items():
        value = None
        for concept in concepts:
            value = _extract_xbrl_value(content, concept)
            if value is not None:
                break
        if value is not None:
            extracted[field] = value
    return extracted


def _extract_xbrl_value(content: str, concept_code: str) -> float | None:
    local_name = concept_code.split("_", 1)[1] if "_" in concept_code else concept_code
    pattern = re.compile(
        rf"<(?:[A-Za-z0-9_-]+:)?{re.escape(local_name)}(?:\s[^>]*)?>([^<]+)</(?:[A-Za-z0-9_-]+:)?{re.escape(local_name)}>",
        re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        candidate = match.group(1).strip()
        cleaned = (
            candidate.replace(".", "")
            .replace(",", ".")
            .replace("(", "-")
            .replace(")", "")
            .replace(" ", "")
        )
        if re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
            return float(cleaned)
    return None

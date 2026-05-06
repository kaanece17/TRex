from __future__ import annotations

import re
import time
from datetime import date, datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

from bist_factor_backtest.data.universe import reconstruct_membership_from_current

BIST_INDEX_ANNOUNCEMENTS_URL = "https://www.borsaistanbul.com/endeksler/endeks-duyurulari?page=0"
CNBCE_XUSIN_URL = "https://www.cnbce.com/borsa/hisseler/bist-sinai-hisseleri"

_AMBIGUOUS_NAME_SYMBOLS = {
    "AKIN TEKSTIL": "ATEKS",
    "MARMARA HOLDING": "MARMR",
    "MEGA POLIETILEN": "MEGAP",
}


def parse_bist_index_announcement_rows(html: str, start_date: date) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for table_row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all("td")]
        link = table_row.find("a", href=True)
        if len(cells) < 5 or link is None:
            continue
        announcement_date = _parse_bist_date(cells[0])
        if announcement_date is None or announcement_date < start_date:
            continue
        if not _is_sector_announcement(cells):
            continue
        rows.append(
            {
                "announcement_date": announcement_date,
                "title": cells[1],
                "url": link["href"],
            }
        )
    return pd.DataFrame(rows)


def extract_xusin_changes_from_kap_html(html: str, source_url: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    related_symbols = _extract_related_symbols(soup)
    rows = []
    for table_row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True).replace("\xa0", " ") for cell in table_row.find_all(["td", "th"])]
        if "XUSIN" not in cells:
            continue
        action = _action_from_cells(cells)
        if action is None:
            continue
        effective_date = _effective_date_from_cells(cells)
        symbol = _symbol_for_row(cells[0], related_symbols)
        confidence = "high" if symbol is not None and len(related_symbols) == 1 else "medium"
        if symbol is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "action": action,
                "effective_date": effective_date,
                "source_type": "kap_announcement",
                "source_url": source_url,
                "confidence": confidence,
            }
        )
    return pd.DataFrame(rows)


def manual_2022_sector_restructure_changes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "action": "remove",
                "effective_date": date(2022, 6, 1),
                "source_type": "bist_pdf_manual_parse",
                "source_url": "https://www.borsaistanbul.com/files/duyuru-8911-TR.pdf",
                "confidence": "medium",
            }
            for symbol in ["DOBUR", "HURGZ", "IHGZT"]
        ]
    )


def fetch_reconstructed_xusin_membership(
    current_symbols: list[str],
    start_date: date,
    today: date,
    universe_name: str = "BIST_SANAYI",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    response = requests.get(BIST_INDEX_ANNOUNCEMENTS_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    announcements = parse_bist_index_announcement_rows(response.text, start_date)
    changes = []
    for item in announcements.to_dict("records"):
        if "kap.org.tr" not in str(item["url"]):
            continue
        kap_response = _get_with_backoff(item["url"])
        if kap_response is None:
            continue
        parsed = extract_xusin_changes_from_kap_html(kap_response.text, item["url"])
        if not parsed.empty:
            changes.append(parsed)
        time.sleep(0.1)
    changes.append(manual_2022_sector_restructure_changes())
    change_data = pd.concat(changes, ignore_index=True) if changes else pd.DataFrame()
    membership = reconstruct_membership_from_current(current_symbols, change_data, today, start_date, universe_name)
    return membership, change_data


def _parse_bist_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _is_sector_announcement(cells: list[str]) -> bool:
    return any("Sektör" in cell for cell in cells[1:5])


def _extract_related_symbols(soup: BeautifulSoup) -> list[str]:
    for table_row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all(["td", "th"])]
        if cells and cells[0].startswith("İlgili Şirketler") and len(cells) > 1:
            return re.findall(r"[A-Z0-9]{2,6}", cells[1])
    return []


def _action_from_cells(cells: list[str]) -> str | None:
    index = cells.index("XUSIN")
    if index in {1, 5}:
        return "add"
    if index in {2, 6}:
        return "remove"
    return None


def _effective_date_from_cells(cells: list[str]) -> date:
    for cell in cells:
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", cell):
            return datetime.strptime(cell, "%d/%m/%Y").date()
    raise ValueError(f"Could not parse effective date from KAP row: {cells}")


def _symbol_for_row(company_name: str, related_symbols: list[str]) -> str | None:
    if len(related_symbols) == 1:
        return related_symbols[0]
    return _AMBIGUOUS_NAME_SYMBOLS.get(company_name.upper())


def _get_with_backoff(url: str):
    for attempt in range(2):
        try:
            response = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        except requests.RequestException:
            time.sleep(2**attempt)
            continue
        if response.status_code != 429:
            response.raise_for_status()
            return response
        time.sleep(2**attempt)
    return None

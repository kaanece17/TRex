from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup


SOURCE_PAGE = ("sp500", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
TARGET_SUBINDUSTRIES = {
    "Semiconductors",
    "Semiconductor Materials & Equipment",
}
UNIVERSE_NAME = "US_LARGE_CAP_SEMIS"
USER_AGENT = "Mozilla/5.0 (compatible; TRex US semis universe builder)"
OUTPUT_SYMBOLS = Path("/Users/kaanece/projects/TRex/data/universe/us_large_cap_semis_symbols.csv")
OUTPUT_MEMBERSHIP = Path("/Users/kaanece/projects/TRex/data/universe/us_large_cap_semis_membership.csv")


def _load_semis_from_page(label: str, url: str) -> pd.DataFrame:
    response = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="wikitable")
    if table is None:
        raise RuntimeError(f"No wikitable found for {label}: {url}")

    rows = table.find_all("tr")
    headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
    symbol_index = headers.index("Symbol")
    sector_index = headers.index("GICS Sector")
    subindustry_index = headers.index("GICS Sub-Industry")

    records: list[dict[str, str]] = []
    for row in rows[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        if len(cells) <= max(symbol_index, sector_index, subindustry_index):
            continue
        sector = cells[sector_index].strip()
        subindustry = cells[subindustry_index].strip()
        if sector != "Information Technology":
            continue
        if subindustry not in TARGET_SUBINDUSTRIES:
            continue
        symbol = cells[symbol_index].strip().upper().replace(".", "-")
        if not symbol:
            continue
        records.append(
            {
                "symbol": symbol,
                "source_label": label,
                "source_url": url,
                "gics_sub_industry": subindustry,
            }
        )
    return pd.DataFrame(records)


def main() -> None:
    label, url = SOURCE_PAGE
    combined = _load_semis_from_page(label, url)
    combined = combined.drop_duplicates(subset=["symbol"]).sort_values("symbol").reset_index(drop=True)

    symbols = combined[["symbol"]].copy()
    membership = combined.assign(
        universe_name=UNIVERSE_NAME,
        start_date=date(2020, 1, 1),
        end_date=None,
        source_type="current_static",
        confidence="medium",
    )[
        ["symbol", "universe_name", "start_date", "end_date", "source_type", "source_url", "confidence"]
    ]

    OUTPUT_SYMBOLS.parent.mkdir(parents=True, exist_ok=True)
    symbols.to_csv(OUTPUT_SYMBOLS, index=False)
    membership.to_csv(OUTPUT_MEMBERSHIP, index=False)
    print(
        f"universe={UNIVERSE_NAME} subindustries={','.join(sorted(TARGET_SUBINDUSTRIES))} "
        f"symbols={len(symbols)} membership={len(membership)}"
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "Mozilla/5.0 (compatible; TRex US tech subtheme audit)"


def _load_inputs():
    settings = load_config(CONFIG_PATH)
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    financials["announcement_datetime"] = pd.to_datetime(financials["announcement_datetime"], errors="coerce")
    financials = (
        financials.sort_values(["symbol", "period_end", "announcement_datetime"])
        .drop_duplicates(["symbol", "period_end", "announcement_datetime"], keep="last")
        .reset_index(drop=True)
    )
    financials = add_earnings_momentum_features(financials)
    membership = _load_membership_for_run(settings)
    storage.close()
    return settings, prices, financials, membership


def _load_sp500_subindustry_map() -> pd.DataFrame:
    response = requests.get(SOURCE_URL, timeout=30, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="wikitable")
    if table is None:
        raise RuntimeError("No S&P 500 wikitable found")

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
        symbol = cells[symbol_index].strip().upper().replace(".", "-")
        sector = cells[sector_index].strip()
        subindustry = cells[subindustry_index].strip()
        records.append({"symbol": symbol, "gics_sector": sector, "gics_sub_industry": subindustry})
    return pd.DataFrame(records)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    monthly = result["monthly_results"].copy()
    positions = result["selected_positions"].copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = _numeric(monthly["net_return"])
    positions["month"] = positions["month"].astype(str)
    positions["net_return"] = _numeric(positions["net_return"])
    positions["weight"] = _numeric(positions["weight"])

    subthemes = _load_sp500_subindustry_map()
    positions = positions.merge(subthemes, on="symbol", how="left")

    worst_months = monthly.nsmallest(15, "net_return").copy()
    worst_positions = positions[positions["month"].isin(set(worst_months["month"]))].copy()

    all_subtheme = (
        positions.groupby("gics_sub_industry", dropna=False, as_index=False)
        .agg(
            rows=("symbol", "size"),
            symbols=("symbol", lambda s: int(pd.Series(s).nunique())),
            avg_return=("net_return", "mean"),
            median_return=("net_return", "median"),
            win_rate=("net_return", lambda s: float((s > 0).mean())),
            total_weighted_damage=("net_return", "sum"),
        )
        .sort_values(["rows", "avg_return"], ascending=[False, True])
        .reset_index(drop=True)
    )
    worst_subtheme = (
        worst_positions.groupby("gics_sub_industry", dropna=False, as_index=False)
        .agg(
            rows=("symbol", "size"),
            symbols=("symbol", lambda s: int(pd.Series(s).nunique())),
            avg_return=("net_return", "mean"),
            median_return=("net_return", "median"),
            win_rate=("net_return", lambda s: float((s > 0).mean())),
            total_weighted_damage=("net_return", "sum"),
            worst_month_hits=("month", lambda s: int(pd.Series(s).nunique())),
        )
        .sort_values(["worst_month_hits", "total_weighted_damage"], ascending=[False, True])
        .reset_index(drop=True)
    )

    subtheme_compare = (
        worst_subtheme.merge(
            all_subtheme[
                [
                    "gics_sub_industry",
                    "rows",
                    "avg_return",
                    "median_return",
                    "win_rate",
                    "total_weighted_damage",
                ]
            ].rename(
                columns={
                    "rows": "all_rows",
                    "avg_return": "all_avg_return",
                    "median_return": "all_median_return",
                    "win_rate": "all_win_rate",
                    "total_weighted_damage": "all_total_weighted_damage",
                }
            ),
            on="gics_sub_industry",
            how="left",
        )
        .sort_values(["worst_month_hits", "total_weighted_damage"], ascending=[False, True])
        .reset_index(drop=True)
    )

    worst_symbol_subtheme = (
        worst_positions.groupby(["gics_sub_industry", "symbol"], dropna=False, as_index=False)
        .agg(
            worst_month_hits=("month", lambda s: int(pd.Series(s).nunique())),
            avg_return=("net_return", "mean"),
            total_weighted_damage=("net_return", "sum"),
        )
        .sort_values(["gics_sub_industry", "worst_month_hits", "total_weighted_damage"], ascending=[True, False, True])
        .reset_index(drop=True)
    )

    all_subtheme.to_csv(OUTPUT_DIR / "us_large_cap_tech_subtheme_all.csv", index=False)
    worst_subtheme.to_csv(OUTPUT_DIR / "us_large_cap_tech_subtheme_worst.csv", index=False)
    subtheme_compare.to_csv(OUTPUT_DIR / "us_large_cap_tech_subtheme_compare.csv", index=False)
    worst_symbol_subtheme.to_csv(OUTPUT_DIR / "us_large_cap_tech_subtheme_symbol_damage.csv", index=False)

    lines = [
        "# US Large-Cap Tech Subtheme Audit",
        "",
        "Method note:",
        "- Current large-cap tech universe is mapped to current S&P 500 GICS sub-industries.",
        "- This is good for theme diagnosis, but not a historical sub-industry reconstruction.",
        "",
        "Worst-month subthemes:",
    ]
    for row in worst_subtheme.head(10).to_dict("records"):
        lines.append(
            f"- `{row['gics_sub_industry']}`: hits `{int(row['worst_month_hits'])}`, rows `{int(row['rows'])}`, "
            f"avg `{row['avg_return']:.2%}`, win `{row['win_rate']:.2%}`, total `{row['total_weighted_damage']:.2%}`"
        )
    lines.append("")
    lines.append("Top symbol damage within worst subthemes:")
    for row in worst_symbol_subtheme.head(15).to_dict("records"):
        lines.append(
            f"- `{row['gics_sub_industry']}` | `{row['symbol']}`: hits `{int(row['worst_month_hits'])}`, "
            f"avg `{row['avg_return']:.2%}`, total `{row['total_weighted_damage']:.2%}`"
        )
    (OUTPUT_DIR / "us_large_cap_tech_subtheme_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(worst_subtheme.head(10).to_string(index=False))
    print(worst_symbol_subtheme.head(15).to_string(index=False))


if __name__ == "__main__":
    main()

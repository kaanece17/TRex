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
USER_AGENT = "Mozilla/5.0 (compatible; TRex US tech subtheme proxy)"
TARGET_SUBTHEMES = {
    "Semiconductors",
    "Technology Hardware, Storage & Peripherals",
}


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
    subindustry_index = headers.index("GICS Sub-Industry")

    records: list[dict[str, str]] = []
    for row in rows[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        if len(cells) <= max(symbol_index, subindustry_index):
            continue
        symbol = cells[symbol_index].strip().upper().replace(".", "-")
        subindustry = cells[subindustry_index].strip()
        records.append({"symbol": symbol, "gics_sub_industry": subindustry})
    return pd.DataFrame(records)


def _max_drawdown(returns: pd.Series) -> float:
    curve = (1 + returns).cumprod()
    return float((curve / curve.cummax() - 1).min())


def _run_variant(selected: pd.DataFrame, monthly: pd.DataFrame, min_hits: int, scale: float) -> tuple[dict[str, object], pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for month in monthly["month"].astype(str).tolist():
        month_positions = selected[selected["month"].astype(str) == month].copy()
        month_positions["cluster_flag"] = month_positions["gics_sub_industry"].isin(TARGET_SUBTHEMES)
        flagged_symbols = int(month_positions.loc[month_positions["cluster_flag"], "symbol"].nunique())
        weights = month_positions["weight"].copy()
        if flagged_symbols >= min_hits and weights.notna().any():
            weights.loc[month_positions["cluster_flag"]] = weights.loc[month_positions["cluster_flag"]] * scale
            total = float(weights.sum())
            if total > 0:
                weights = weights / total
        adjusted_return = float((weights * month_positions["net_return"]).sum()) if not month_positions.empty else 0.0
        rows.append(
            {
                "month": month,
                "net_return": adjusted_return,
                "flagged_symbols": flagged_symbols,
                "flagged_weight_before": float(month_positions.loc[month_positions["cluster_flag"], "weight"].sum()),
            }
        )
    month_df = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    curve = (1 + month_df["net_return"]).cumprod()
    summary = {
        "variant": f"subtheme_{min_hits}p_scale{int(scale * 1000):03d}",
        "min_hits": min_hits,
        "scale": scale,
        "multiple": float(curve.iloc[-1]),
        "win_rate": float((month_df["net_return"] > 0).mean()),
        "max_drawdown": _max_drawdown(month_df["net_return"]),
        "flagged_month_share": float((month_df["flagged_symbols"] >= min_hits).mean()),
        "avg_flagged_symbols": float(month_df["flagged_symbols"].mean()),
    }
    return summary, month_df


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    selected = result["selected_positions"].copy()
    monthly = result["monthly_results"].copy()
    selected["month"] = selected["month"].astype(str)
    selected["weight"] = pd.to_numeric(selected["weight"], errors="coerce")
    selected["net_return"] = pd.to_numeric(selected["net_return"], errors="coerce")
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = pd.to_numeric(monthly["net_return"], errors="coerce")

    subthemes = _load_sp500_subindustry_map()
    selected = selected.merge(subthemes, on="symbol", how="left")

    summary_rows = [
        {
            "variant": "baseline",
            "min_hits": None,
            "scale": None,
            "multiple": float(monthly["portfolio_value_end"].iloc[-1] / settings.backtest.initial_capital),
            "win_rate": float((monthly["net_return"] > 0).mean()),
            "max_drawdown": _max_drawdown(monthly["net_return"]),
            "flagged_month_share": 0.0,
            "avg_flagged_symbols": 0.0,
        }
    ]
    monthly_frames = [monthly.assign(variant="baseline", flagged_symbols=0, flagged_weight_before=0.0)]

    for min_hits, scale in [(2, 0.85), (2, 0.75), (3, 0.85), (3, 0.75)]:
        summary, month_df = _run_variant(selected, monthly, min_hits=min_hits, scale=scale)
        summary_rows.append(summary)
        monthly_frames.append(month_df.assign(variant=summary["variant"]))

    summary = pd.DataFrame(summary_rows)
    baseline = summary.loc[summary["variant"] == "baseline"].iloc[0]
    summary["strict_pass"] = (
        (summary["multiple"] > float(baseline["multiple"]))
        & (summary["win_rate"] >= float(baseline["win_rate"]))
        & (summary["max_drawdown"] >= float(baseline["max_drawdown"]))
    )
    summary = summary.sort_values(["strict_pass", "multiple", "max_drawdown"], ascending=[False, False, False]).reset_index(drop=True)
    monthly_all = pd.concat(monthly_frames, ignore_index=True)

    summary.to_csv(OUTPUT_DIR / "us_large_cap_tech_subtheme_proxy_summary.csv", index=False)
    monthly_all.to_csv(OUTPUT_DIR / "us_large_cap_tech_subtheme_proxy_monthly.csv", index=False)

    lines = [
        "# US Large-Cap Tech Subtheme Proxy",
        "",
        "Target subthemes:",
        "- Semiconductors",
        "- Technology Hardware, Storage & Peripherals",
        "",
    ]
    for row in summary.to_dict("records"):
        lines.append(
            f"- {row['variant']}: multiple={row['multiple']:.2f}x, win={row['win_rate']:.2%}, "
            f"dd={row['max_drawdown']:.2%}, flagged_month_share={row['flagged_month_share']:.2%}, "
            f"strict={'yes' if row['strict_pass'] else 'no'}"
        )
    (OUTPUT_DIR / "us_large_cap_tech_subtheme_proxy_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

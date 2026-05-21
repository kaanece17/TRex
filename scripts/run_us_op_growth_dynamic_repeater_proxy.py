from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path("/Users/kaanece/projects/TRex")
PROFILE_DIR = ROOT / "outputs" / "dashboard" / "us_industrials_quality_op_growth"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


@dataclass(frozen=True)
class Variant:
    name: str
    lookback_months: int
    min_negative_hits: int
    scale: float


VARIANTS = [
    Variant(name="dynrep_12m_hits2_scale850", lookback_months=12, min_negative_hits=2, scale=0.85),
    Variant(name="dynrep_12m_hits2_scale750", lookback_months=12, min_negative_hits=2, scale=0.75),
    Variant(name="dynrep_12m_hits3_scale850", lookback_months=12, min_negative_hits=3, scale=0.85),
    Variant(name="dynrep_6m_hits2_scale850", lookback_months=6, min_negative_hits=2, scale=0.85),
]


def _max_drawdown(returns: pd.Series) -> float:
    curve = (1 + returns).cumprod()
    return float((curve / curve.cummax() - 1).min())


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = pd.DataFrame(json.loads((PROFILE_DIR / "selected_positions.json").read_text()))
    monthly = pd.DataFrame(json.loads((PROFILE_DIR / "monthly_returns.json").read_text()))
    selected["month"] = selected["month"].astype(str)
    selected["weight"] = pd.to_numeric(selected["weight"], errors="coerce")
    selected["net_return"] = pd.to_numeric(selected["net_return"], errors="coerce")
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = pd.to_numeric(monthly["net_return"], errors="coerce")
    return selected, monthly.sort_values("month").reset_index(drop=True)


def _build_dynamic_basket(
    history: pd.DataFrame,
    lookback_months: int,
    min_negative_hits: int,
) -> set[str]:
    if history.empty:
        return set()
    recent_months = sorted(history["month"].astype(str).unique())[-lookback_months:]
    window = history[history["month"].astype(str).isin(recent_months)].copy()
    if window.empty:
        return set()
    grouped = (
        window.groupby("symbol", as_index=False)
        .agg(
            negative_hits=("net_return", lambda s: int((pd.to_numeric(s, errors="coerce") < 0).sum())),
            avg_return=("net_return", lambda s: float(pd.to_numeric(s, errors="coerce").mean())),
        )
    )
    flagged = grouped[
        (grouped["negative_hits"] >= min_negative_hits)
        & (grouped["avg_return"] < 0)
    ]
    return set(flagged["symbol"].astype(str))


def _run_variant(selected: pd.DataFrame, monthly: pd.DataFrame, variant: Variant) -> tuple[dict[str, object], pd.DataFrame]:
    month_order = monthly["month"].astype(str).tolist()
    rows: list[dict[str, object]] = []
    history_rows: list[pd.DataFrame] = []

    for month in month_order:
        month_positions = selected[selected["month"].astype(str) == month].copy()
        prior_history = pd.concat(history_rows, ignore_index=True) if history_rows else month_positions.iloc[0:0].copy()
        dynamic_basket = _build_dynamic_basket(
            prior_history,
            lookback_months=variant.lookback_months,
            min_negative_hits=variant.min_negative_hits,
        )
        month_positions["dynamic_flag"] = month_positions["symbol"].astype(str).isin(dynamic_basket)
        flagged_symbols = int(month_positions.loc[month_positions["dynamic_flag"], "symbol"].nunique())
        weights = month_positions["weight"].copy()
        if flagged_symbols >= 2 and weights.notna().any():
            weights.loc[month_positions["dynamic_flag"]] = (
                weights.loc[month_positions["dynamic_flag"]] * variant.scale
            )
            total = float(weights.sum())
            if total > 0:
                weights = weights / total
        adjusted_return = float((weights * month_positions["net_return"]).sum()) if not month_positions.empty else 0.0
        rows.append(
            {
                "month": month,
                "net_return": adjusted_return,
                "flagged_symbols": flagged_symbols,
                "flagged_weight_before": float(month_positions.loc[month_positions["dynamic_flag"], "weight"].sum()),
                "dynamic_basket_size": len(dynamic_basket),
            }
        )
        history_rows.append(month_positions[["month", "symbol", "net_return"]].copy())

    month_df = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    curve = (1 + month_df["net_return"]).cumprod()
    summary = {
        "variant": variant.name,
        "lookback_months": variant.lookback_months,
        "min_negative_hits": variant.min_negative_hits,
        "scale": variant.scale,
        "multiple": float(curve.iloc[-1]),
        "win_rate": float((month_df["net_return"] > 0).mean()),
        "max_drawdown": _max_drawdown(month_df["net_return"]),
        "flagged_month_share": float((month_df["flagged_symbols"] >= 2).mean()),
        "avg_flagged_symbols": float(month_df["flagged_symbols"].mean()),
    }
    return summary, month_df


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    selected, monthly = _load_inputs()

    baseline_curve = (1 + monthly["net_return"]).cumprod()
    summary_rows = [
        {
            "variant": "baseline",
            "lookback_months": None,
            "min_negative_hits": None,
            "scale": None,
            "multiple": float(baseline_curve.iloc[-1]),
            "win_rate": float((monthly["net_return"] > 0).mean()),
            "max_drawdown": _max_drawdown(monthly["net_return"]),
            "flagged_month_share": 0.0,
            "avg_flagged_symbols": 0.0,
        }
    ]
    monthly_frames = [monthly.assign(variant="baseline", flagged_symbols=0, flagged_weight_before=0.0, dynamic_basket_size=0)]

    for variant in VARIANTS:
        summary, month_df = _run_variant(selected, monthly, variant)
        summary_rows.append(summary)
        monthly_frames.append(month_df.assign(variant=variant.name))

    summary = pd.DataFrame(summary_rows)
    summary["strict_pass"] = (
        (summary["multiple"] > float(summary.loc[summary["variant"] == "baseline", "multiple"].iloc[0]))
        & (summary["win_rate"] >= float(summary.loc[summary["variant"] == "baseline", "win_rate"].iloc[0]))
        & (summary["max_drawdown"] >= float(summary.loc[summary["variant"] == "baseline", "max_drawdown"].iloc[0]))
    )
    summary = summary.sort_values(["strict_pass", "multiple", "max_drawdown"], ascending=[False, False, False]).reset_index(drop=True)
    monthly_all = pd.concat(monthly_frames, ignore_index=True)

    summary.to_csv(OUTPUT_DIR / "us_op_growth_dynamic_repeater_proxy_summary.csv", index=False)
    monthly_all.to_csv(OUTPUT_DIR / "us_op_growth_dynamic_repeater_proxy_monthly.csv", index=False)

    lines = [
        "# US OP-Growth Dynamic Repeater Proxy",
        "",
        "Dynamic basket rule:",
        "- Use only prior realized months.",
        "- Flag symbols with repeated negative realized returns in the lookback window.",
        "- Only scale when the current basket contains 2 or more flagged symbols.",
        "",
    ]
    for row in summary.to_dict("records"):
        lines.append(
            f"- {row['variant']}: multiple={row['multiple']:.2f}x, win={row['win_rate']:.2%}, "
            f"dd={row['max_drawdown']:.2%}, flagged_month_share={row['flagged_month_share']:.2%}, "
            f"strict={'yes' if row['strict_pass'] else 'no'}"
        )
    (OUTPUT_DIR / "us_op_growth_dynamic_repeater_proxy_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

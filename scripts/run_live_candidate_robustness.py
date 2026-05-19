from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/Users/kaanece/projects/TRex")
DASHBOARD_ROOT = ROOT / "outputs" / "dashboard"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
PROFILES = ["accepted_top6", "momentum_watchlist", "technical_confirmation"]


def _load_monthly(profile_id: str) -> pd.DataFrame:
    path = DASHBOARD_ROOT / profile_id / "monthly_returns.json"
    monthly = pd.DataFrame(json.loads(path.read_text()))
    monthly["month"] = monthly["month"].astype(str)
    monthly["net_return"] = pd.to_numeric(monthly["net_return"], errors="coerce")
    return monthly[["month", "net_return"]].copy()


def _max_drawdown(returns: pd.Series) -> float:
    curve = (1 + returns).cumprod()
    peak = curve.cummax()
    dd = curve / peak - 1
    return float(dd.min())


def _rolling_rows(profile_id: str, monthly: pd.DataFrame, window: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    returns = monthly["net_return"].reset_index(drop=True)
    months = monthly["month"].reset_index(drop=True)
    for start in range(0, len(monthly) - window + 1):
        sub = returns.iloc[start : start + window]
        rows.append(
            {
                "profile": profile_id,
                "window_months": window,
                "start_month": months.iloc[start],
                "end_month": months.iloc[start + window - 1],
                "multiple": float((1 + sub).prod()),
                "avg_month_return": float(sub.mean()),
                "win_rate": float((sub > 0).mean()),
                "max_drawdown": _max_drawdown(sub),
            }
        )
    return rows


def _rolling_head_to_head(rolling: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for window, subset in rolling.groupby("window_months"):
        pivot = subset.pivot(index=["start_month", "end_month"], columns="profile", values="multiple").reset_index()
        pivot["winner"] = pivot[PROFILES].idxmax(axis=1)
        for profile in PROFILES:
            rows.append(
                {
                    "window_months": window,
                    "profile": profile,
                    "win_share": float((pivot["winner"] == profile).mean()),
                    "median_multiple": float(pivot[profile].median()),
                    "p25_multiple": float(pivot[profile].quantile(0.25)),
                    "p75_multiple": float(pivot[profile].quantile(0.75)),
                }
            )
    return pd.DataFrame(rows)


def _block_bootstrap(returns_by_profile: dict[str, pd.Series], block_size: int = 6, simulations: int = 2000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_months = len(next(iter(returns_by_profile.values())))
    max_start = n_months - block_size
    rows: list[dict[str, object]] = []
    for sim in range(simulations):
        sampled_idx: list[int] = []
        while len(sampled_idx) < n_months:
            start = int(rng.integers(0, max_start + 1))
            sampled_idx.extend(range(start, start + block_size))
        sampled_idx = sampled_idx[:n_months]
        scores = {}
        for profile, returns in returns_by_profile.items():
            sampled = returns.iloc[sampled_idx].reset_index(drop=True)
            scores[profile] = float((1 + sampled).prod())
            rows.append(
                {
                    "simulation": sim,
                    "profile": profile,
                    "multiple": scores[profile],
                    "max_drawdown": _max_drawdown(sampled),
                    "win_rate": float((sampled > 0).mean()),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    monthly_map = {profile: _load_monthly(profile) for profile in PROFILES}

    rolling_rows: list[dict[str, object]] = []
    for profile, monthly in monthly_map.items():
        for window in (12, 24, 36):
            rolling_rows.extend(_rolling_rows(profile, monthly, window))
    rolling = pd.DataFrame(rolling_rows)
    rolling_summary = _rolling_head_to_head(rolling)

    aligned_returns = {
        profile: monthly_map[profile]["net_return"].reset_index(drop=True)
        for profile in PROFILES
    }
    bootstrap = _block_bootstrap(aligned_returns)
    bootstrap_winners = (
        bootstrap.pivot(index="simulation", columns="profile", values="multiple")[PROFILES]
        .idxmax(axis=1)
        .value_counts(normalize=True)
        .rename_axis("profile")
        .reset_index(name="bootstrap_win_share")
    )
    bootstrap_summary = (
        bootstrap.groupby("profile")
        .agg(
            median_multiple=("multiple", "median"),
            p25_multiple=("multiple", lambda s: float(s.quantile(0.25))),
            p75_multiple=("multiple", lambda s: float(s.quantile(0.75))),
            median_max_drawdown=("max_drawdown", "median"),
            median_win_rate=("win_rate", "median"),
        )
        .reset_index()
        .merge(bootstrap_winners, on="profile", how="left")
        .fillna({"bootstrap_win_share": 0.0})
    )

    rolling.to_csv(OUTPUT_DIR / "live_candidate_robustness_rolling.csv", index=False)
    rolling_summary.to_csv(OUTPUT_DIR / "live_candidate_robustness_rolling_summary.csv", index=False)
    bootstrap.to_csv(OUTPUT_DIR / "live_candidate_robustness_bootstrap.csv", index=False)
    bootstrap_summary.to_csv(OUTPUT_DIR / "live_candidate_robustness_bootstrap_summary.csv", index=False)

    lines = [
        "# Live Candidate Robustness",
        "",
        "Method:",
        "- Rolling windows: 12m, 24m, 36m",
        "- Block bootstrap: 6-aylik bloklar, 2000 simulasyon",
        "",
        "Rolling winner share:",
    ]
    for row in rolling_summary.sort_values(["window_months", "win_share"], ascending=[True, False]).to_dict(orient="records"):
        lines.append(
            f"- {row['window_months']}m | {row['profile']}: "
            f"winner_share={row['win_share']:.2%}, median_multiple={row['median_multiple']:.2f}x"
        )
    lines.append("")
    lines.append("Bootstrap summary:")
    for row in bootstrap_summary.sort_values("bootstrap_win_share", ascending=False).to_dict(orient="records"):
        lines.append(
            f"- {row['profile']}: bootstrap_win_share={row['bootstrap_win_share']:.2%}, "
            f"median_multiple={row['median_multiple']:.2f}x, median_dd={row['median_max_drawdown']:.2%}"
        )
    (OUTPUT_DIR / "live_candidate_robustness_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

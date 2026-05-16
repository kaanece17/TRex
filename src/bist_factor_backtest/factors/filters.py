from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FilterSettings:
    require_complete_financial_snapshot: bool = True
    require_positive_equity: bool = True
    require_positive_net_income_ttm: bool = True
    require_positive_previous_net_income_ttm: bool = True
    require_positive_operating_profit_ttm: bool = True
    require_positive_firm_value: bool = True
    require_shares_outstanding: bool = True
    min_avg_turnover_20d: float = 1_000_000


def apply_filters(data: pd.DataFrame, settings: FilterSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = data.copy()
    rejected = []

    checks = []
    if settings.require_complete_financial_snapshot:
        required_columns = [
            "period_end",
            "equity",
            "net_income_ttm",
            "previous_net_income_ttm",
            "operating_profit_ttm",
            "shares_outstanding",
        ]
        missing_mask = pd.Series(False, index=result.index)
        for column in required_columns:
            if column not in result.columns:
                missing_mask = pd.Series(True, index=result.index)
                break
            missing_mask = missing_mask | result[column].isna()
        # Point-in-time logic accepts date-only announcements when exact datetimes
        # are unavailable, so treat either field as sufficient coverage here.
        if "announcement_datetime" in result.columns or "announcement_date" in result.columns:
            announcement_datetime = result["announcement_datetime"] if "announcement_datetime" in result.columns else pd.Series(pd.NA, index=result.index)
            announcement_date = result["announcement_date"] if "announcement_date" in result.columns else pd.Series(pd.NA, index=result.index)
            missing_mask = missing_mask | (announcement_datetime.isna() & announcement_date.isna())
        else:
            missing_mask = pd.Series(True, index=result.index)
        checks.append(("missing_financial_data", missing_mask))
    if settings.require_positive_equity:
        checks.append(("negative_equity", result["equity"] <= 0))
    if settings.require_positive_net_income_ttm:
        checks.append(("negative_net_income_ttm", result["net_income_ttm"] <= 0))
    if settings.require_positive_previous_net_income_ttm:
        checks.append(("missing_previous_ttm", result["previous_net_income_ttm"] <= 0))
    if settings.require_positive_operating_profit_ttm:
        checks.append(("negative_operating_profit_ttm", result["operating_profit_ttm"].isna() | (result["operating_profit_ttm"] <= 0)))
    if settings.require_positive_firm_value:
        checks.append(("negative_firm_value", result["firm_value"].isna() | (result["firm_value"] <= 0)))
    if settings.require_shares_outstanding:
        checks.append(("missing_shares_outstanding", result["shares_outstanding"].isna() | (result["shares_outstanding"] <= 0)))
    checks.append(("low_liquidity", result["avg_turnover_20d"] < settings.min_avg_turnover_20d))

    rejected_indexes = set()
    for reason, mask in checks:
        failed = result[mask & ~result.index.isin(rejected_indexes)].copy()
        if not failed.empty:
            failed["reason"] = reason
            rejected.append(failed)
            rejected_indexes.update(failed.index.tolist())

    filtered = result[~result.index.isin(rejected_indexes)].copy()
    rejected_data = pd.concat(rejected, ignore_index=True) if rejected else result.iloc[0:0].assign(reason=pd.Series(dtype=str))
    return filtered.reset_index(drop=True), rejected_data.reset_index(drop=True)

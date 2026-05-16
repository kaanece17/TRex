from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.point_in_time import get_latest_known_annual_financials, get_latest_known_financials
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.data.universe import get_universe_for_date, load_universe_membership
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value

MONTH_TARGETS = {
    '2024-05': {
        'expected': ['VESBE', 'KLSYN', 'BUCIM', 'TTRAK', 'BOBET'],
        'outliers': ['KONYA', 'YUNSA', 'AFYON', 'DESA', 'SKTAS', 'DURDO'],
    },
    '2024-06': {
        'expected': ['VESBE', 'BUCIM', 'GENTS', 'BRKSN', 'BVSAN'],
        'outliers': ['KONYA', 'YUNSA', 'AFYON', 'DESA', 'GIPTA', 'MEKAG'],
    },
}


def _safe_growth(current: pd.Series, previous: pd.Series) -> pd.Series:
    denominator = previous.where(previous != 0)
    return (current - previous) / denominator


def _build_month_dataset(snapshots: pd.DataFrame, prices: pd.DataFrame, membership, universe_name: str, month: str) -> pd.DataFrame:
    buy_date = pd.Timestamp(prices.loc[prices['date'].astype(str).str.startswith(month), 'date'].min()).date()
    rebalance_dt = pd.Timestamp(f'{buy_date} 10:00:00')
    universe = get_universe_for_date(membership, universe_name, buy_date)

    annual = get_latest_known_annual_financials(snapshots, rebalance_dt, buy_date)
    latest = get_latest_known_financials(snapshots, rebalance_dt, buy_date)
    annual = annual[annual['symbol'].isin(universe)].copy()
    latest = latest[latest['symbol'].isin(universe)].copy()
    annual = attach_market_cap_firm_value(annual, prices, rebalance_dt)

    known = snapshots.copy()
    known['announcement_datetime'] = pd.to_datetime(known['announcement_datetime'], errors='coerce')
    if isinstance(known['announcement_datetime'].dtype, pd.DatetimeTZDtype):
        known['announcement_datetime'] = known['announcement_datetime'].dt.tz_localize(None)
    known['announcement_date'] = pd.to_datetime(known['announcement_date'], errors='coerce').dt.date
    known_dt = known[known['announcement_datetime'].notna() & (known['announcement_datetime'] <= rebalance_dt)]
    known_date = known[
        known['announcement_datetime'].isna() & known['announcement_date'].notna() & (known['announcement_date'] < buy_date)
    ]
    known = pd.concat([known_dt, known_date], ignore_index=True)

    previous_same_quarter = known[['symbol', 'fiscal_year', 'fiscal_quarter', 'net_income']].copy()
    previous_same_quarter['fiscal_year'] = previous_same_quarter['fiscal_year'] + 1
    previous_same_quarter = previous_same_quarter.rename(columns={'net_income': 'previous_same_quarter_cum_net_income'})

    latest = latest.merge(previous_same_quarter, on=['symbol', 'fiscal_year', 'fiscal_quarter'], how='left')

    dataset = annual.merge(
        latest[['symbol', 'period_end', 'announcement_date', 'fiscal_year', 'fiscal_quarter', 'net_income', 'previous_same_quarter_cum_net_income']].rename(
            columns={
                'period_end': 'latest_period_end',
                'announcement_date': 'latest_announcement_date',
                'net_income': 'latest_cum_net_income',
            }
        ),
        on=['symbol', 'fiscal_year', 'fiscal_quarter'],
        how='left',
    )

    dataset = dataset.rename(
        columns={
            'period_end': 'annual_period_end',
            'announcement_date': 'annual_announcement_date',
            'net_income': 'annual_net_income',
            'previous_annual_net_income': 'previous_annual_net_income',
            'operating_profit': 'annual_operating_profit',
        }
    )
    dataset['buy_date'] = buy_date
    dataset['annual_growth_signed'] = _safe_growth(dataset['annual_net_income'], dataset['previous_annual_net_income'])
    dataset['latest_cum_growth_signed'] = _safe_growth(dataset['latest_cum_net_income'], dataset['previous_same_quarter_cum_net_income'])
    dataset['x1_note_latest_cum'] = (dataset['annual_net_income'] / dataset['equity']) * (1 + dataset['latest_cum_growth_signed'])
    dataset['x2_note'] = dataset['annual_operating_profit'] / dataset['firm_value']
    dataset['score_note_latest_cum'] = dataset['x1_note_latest_cum'] + dataset['x2_note']
    ranked = dataset[
        dataset['annual_net_income'].notna()
        & dataset['previous_annual_net_income'].notna()
        & dataset['equity'].notna()
        & dataset['annual_operating_profit'].notna()
        & dataset['firm_value'].notna()
        & dataset['latest_cum_growth_signed'].notna()
        & (dataset['equity'] > 0)
        & (dataset['firm_value'] > 0)
    ].copy()
    ranked = ranked.sort_values(['score_note_latest_cum', 'symbol'], ascending=[False, True]).reset_index(drop=True)
    ranked['rank_latest_cum'] = ranked.index + 1
    dataset = dataset.merge(ranked[['symbol', 'rank_latest_cum']], on='symbol', how='left')
    return dataset


def main() -> None:
    project_root = Path('/Users/kaanece/projects/TRex')
    settings = load_config(project_root / 'config.no_fees.yaml')
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    snapshots = storage.read_table('financial_snapshots')
    prices = storage.read_table('market_prices')
    prices['date'] = pd.to_datetime(prices['date']).dt.date
    membership = load_universe_membership(settings.universe.membership_file, settings.universe.symbol_aliases_file)

    rows = []
    for month, groups in MONTH_TARGETS.items():
        dataset = _build_month_dataset(snapshots, prices, membership, settings.universe.name, month)
        symbols = groups['expected'] + groups['outliers']
        subset = dataset[dataset['symbol'].isin(symbols)].copy()
        subset['group'] = subset['symbol'].map(lambda s: 'expected' if s in groups['expected'] else 'outlier')
        rows.extend(
            subset[[
                'buy_date','symbol','group','annual_period_end','annual_announcement_date','latest_period_end','latest_announcement_date',
                'annual_net_income','previous_annual_net_income','latest_cum_net_income','previous_same_quarter_cum_net_income',
                'equity','annual_operating_profit','firm_value','annual_growth_signed','latest_cum_growth_signed',
                'x1_note_latest_cum','x2_note','score_note_latest_cum','rank_latest_cum'
            ]].assign(month=month).to_dict(orient='records')
        )

    out_dir = project_root / 'outputs' / 'formula_research_reference'
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_dir / 'reference_outlier_comparison.csv', index=False)
    print(out_dir / 'reference_outlier_comparison.csv')


if __name__ == '__main__':
    main()

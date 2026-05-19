from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    BaseModel = object  # pragma: no cover


class _FallbackModel:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)

    @classmethod
    def model_validate(cls, values):
        return cls(**values)

    def model_dump(self, mode=None):
        return self.__dict__.copy()


class _Model(BaseModel if BaseModel is not object else _FallbackModel):
    pass


class ProjectConfig(_Model):
    name: str
    timezone: str = "Europe/Istanbul"


class DataConfig(_Model):
    storage: str = "duckdb"
    duckdb_path: Path
    price_symbol_suffix: str | None = ".IS"
    sec_user_agent: str | None = None
    price_preload_start: date | None = None
    financial_preload_start: date | None = None


class UniverseConfig(_Model):
    name: str
    source: str = "csv"
    symbols_file: Path
    membership_file: Path | None = None
    monthly_snapshot_file: Path | None = None
    symbol_aliases_file: Path | None = None
    mode: str = "reconstructed_historical"
    fallback_mode: str = "current_static"
    target_index: str = "XUSIN"
    target_group: str = "sector"
    reconstruction_required: bool = True


class PointInTimeConfig(_Model):
    cutoff_mode: str = "market_open"
    if_only_date_available: str = "previous_day_only"


class StrategyConfig(_Model):
    top_n: int = 5
    hold_buffer_rank: int | None = None
    regime_filter_mode: str | None = None
    regime_filter_top_n: int | None = None
    regime_filter_lookback_days: int = 200
    regime_filter_breadth_threshold: float = 0.5
    rebalance_frequency: str = "monthly"
    rebalance_day: str = "first_trading_day"
    rebalance_time: str = "market_open"
    market_open_time: str = "10:00"
    buy_rule: str = "first_trading_day_open"
    sell_rule: str = "last_trading_day_open"
    execution_mode: str = "ideal_open"
    weighting: str = "equal_weight"
    score_weight_cap: float | None = None
    if_less_than_top_n: str = "use_available"
    technical_confirmation_mode: str | None = None
    technical_confirmation_rank_threshold: int | None = None
    technical_confirmation_lookback_days: int = 60
    technical_confirmation_return_threshold: float = 0.0
    technical_confirmation_redistribute: bool = False
    x1_soft_penalty_mode: str | None = None
    x1_soft_penalty_share_threshold: float | None = None
    x1_soft_penalty_return_60d_threshold: float | None = None
    x1_soft_penalty_amount: float = 0.0


class ScoringConfig(_Model):
    formula: str = "x1_plus_x2"
    use_ttm: bool = True
    firm_value_mode: str = "market_cap"
    growth_mode: str = "normalized_percent_cap"
    x1_weight: float = 1.0
    x2_weight: float = 1.0
    earnings_weight: float = 1.0
    momentum_rank_weight: float = 0.0
    cheap_value_trap_penalty: float = 0.0
    cheap_value_trap_fv_to_equity_threshold: float | None = None
    x1_dominant_value_penalty_share_threshold: float | None = None
    x1_cap_quantile: float | None = None
    x2_cap_quantile: float | None = None


class CostsConfig(_Model):
    commission_rate: float = 0.001


class FiltersConfig(_Model):
    require_complete_financial_snapshot: bool = True
    require_positive_equity: bool = True
    require_positive_net_income_ttm: bool = True
    require_positive_previous_net_income_ttm: bool = True
    require_positive_operating_profit_ttm: bool = True
    require_positive_firm_value: bool = True
    require_shares_outstanding: bool = True
    min_market_cap: float | None = None
    max_net_income_to_equity: float | None = None
    x1_dominant_share_threshold: float | None = None
    recent_return_20d_threshold: float | None = None
    min_recent_return_20d: float | None = None
    min_growth_when_x1_dominant_share: float | None = None
    x1_dominant_growth_share_threshold: float | None = None
    min_avg_turnover_20d: float = 1_000_000


class BacktestRangeConfig(_Model):
    start_date: date
    end_date: date
    initial_capital: float


class BacktestConfig(_Model):
    project: ProjectConfig
    data: DataConfig
    universe: UniverseConfig
    point_in_time: PointInTimeConfig
    strategy: StrategyConfig
    scoring: ScoringConfig
    costs: CostsConfig
    filters: FiltersConfig
    backtest: BacktestRangeConfig

    @classmethod
    def model_validate(cls, values):
        if BaseModel is not object:  # pragma: no cover
            return super().model_validate(values)
        return cls(
            project=ProjectConfig.model_validate(values["project"]),
            data=DataConfig.model_validate(
                {
                    **values["data"],
                    "duckdb_path": Path(values["data"]["duckdb_path"]),
                    "price_preload_start": date.fromisoformat(values["data"]["price_preload_start"])
                    if isinstance(values["data"].get("price_preload_start"), str)
                    else values["data"].get("price_preload_start"),
                    "financial_preload_start": date.fromisoformat(values["data"]["financial_preload_start"])
                    if isinstance(values["data"].get("financial_preload_start"), str)
                    else values["data"].get("financial_preload_start"),
                }
            ),
            universe=UniverseConfig.model_validate(
                {
                    **values["universe"],
                    "symbols_file": Path(values["universe"]["symbols_file"]),
                    "membership_file": Path(values["universe"]["membership_file"])
                    if values["universe"].get("membership_file") is not None
                    else None,
                    "monthly_snapshot_file": Path(values["universe"]["monthly_snapshot_file"])
                    if values["universe"].get("monthly_snapshot_file") is not None
                    else None,
                    "symbol_aliases_file": Path(values["universe"]["symbol_aliases_file"])
                    if values["universe"].get("symbol_aliases_file") is not None
                    else None,
                }
            ),
            point_in_time=PointInTimeConfig.model_validate(values["point_in_time"]),
            strategy=StrategyConfig.model_validate(values["strategy"]),
            scoring=ScoringConfig.model_validate(values["scoring"]),
            costs=CostsConfig.model_validate(values["costs"]),
            filters=FiltersConfig.model_validate(values["filters"]),
            backtest=BacktestRangeConfig.model_validate(
                {
                    **values["backtest"],
                    "start_date": date.fromisoformat(values["backtest"]["start_date"])
                    if isinstance(values["backtest"]["start_date"], str)
                    else values["backtest"]["start_date"],
                    "end_date": date.fromisoformat(values["backtest"]["end_date"])
                    if isinstance(values["backtest"]["end_date"], str)
                    else values["backtest"]["end_date"],
                }
            ),
        )

    def model_dump(self, mode=None):
        if BaseModel is not object:  # pragma: no cover
            return super().model_dump(mode=mode)
        return {
            "project": self.project.model_dump(mode=mode),
            "data": self.data.model_dump(mode=mode),
            "universe": self.universe.model_dump(mode=mode),
            "point_in_time": self.point_in_time.model_dump(mode=mode),
            "strategy": self.strategy.model_dump(mode=mode),
            "scoring": self.scoring.model_dump(mode=mode),
            "costs": self.costs.model_dump(mode=mode),
            "filters": self.filters.model_dump(mode=mode),
            "backtest": self.backtest.model_dump(mode=mode),
        }


def load_config(path: str | Path) -> BacktestConfig:
    with Path(path).open("r", encoding="utf-8") as file:
        return BacktestConfig.model_validate(yaml.safe_load(file))

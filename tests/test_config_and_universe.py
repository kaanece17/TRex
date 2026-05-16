from datetime import date
from pathlib import Path

import pandas as pd

import bist_factor_backtest.config as config_module
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.universe import load_static_universe, load_universe_membership


class TestLoadConfig:
    def test_loadConfig_validYaml_returnsTypedConfig(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
project:
  name: test
  timezone: Europe/Istanbul
data:
  storage: duckdb
  duckdb_path: data/test.duckdb
universe:
  name: BIST_SANAYI
  source: csv
  symbols_file: data/universe/symbols.csv
  membership_file: data/universe/membership.csv
  symbol_aliases_file: data/universe/aliases.csv
  mode: historical
point_in_time:
  cutoff_mode: market_open
  if_only_date_available: previous_day_only
strategy:
  top_n: 5
  hold_buffer_rank: 7
  rebalance_frequency: monthly
  rebalance_day: first_trading_day
  rebalance_time: market_open
  market_open_time: "10:00"
  buy_rule: first_trading_day_open
  sell_rule: last_trading_day_open
  execution_mode: ideal_open
  weighting: equal_weight
  if_less_than_top_n: use_available
scoring:
  formula: x1_plus_x2
  use_ttm: true
  firm_value_mode: market_cap
costs:
  commission_rate: 0.001
filters:
  require_positive_equity: true
  require_positive_net_income_ttm: true
  require_positive_previous_net_income_ttm: true
  require_positive_operating_profit_ttm: true
  require_positive_firm_value: true
  require_shares_outstanding: true
  min_avg_turnover_20d: 1000000
backtest:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
  initial_capital: 100000
""",
            encoding="utf-8",
        )
        expected = Path("data/test.duckdb")

        result = load_config(config_file)

        assert result.data.duckdb_path == expected
        assert result.model_dump()["project"]["name"] == "test"
        assert result.universe.symbol_aliases_file == Path("data/universe/aliases.csv")
        assert result.strategy.hold_buffer_rank == 7

    def test_fallbackModel_methods_returnShallowObjectData(self):
        result = config_module._FallbackModel.model_validate({"alpha": 1, "beta": "two"})

        assert result.alpha == 1
        assert result.beta == "two"
        assert result.model_dump() == {"alpha": 1, "beta": "two"}

    def test_backtestConfig_modelValidate_withoutPydantic_usesFallbackBranch(self, monkeypatch):
        monkeypatch.setattr(config_module, "BaseModel", object)
        values = {
            "project": {"name": "test", "timezone": "Europe/Istanbul"},
            "data": {
                "storage": "duckdb",
                "duckdb_path": "data/test.duckdb",
                "price_preload_start": "2023-12-01",
                "financial_preload_start": "2023-01-01",
            },
            "universe": {
                "name": "BIST_SANAYI",
                "source": "csv",
                "symbols_file": "data/universe/symbols.csv",
                "membership_file": "data/universe/membership.csv",
                "monthly_snapshot_file": "data/universe/monthly.csv",
                "mode": "historical",
            },
            "point_in_time": {
                "cutoff_mode": "market_open",
                "if_only_date_available": "previous_day_only",
            },
            "strategy": {
                "top_n": 5,
                "hold_buffer_rank": 7,
                "rebalance_frequency": "monthly",
                "rebalance_day": "first_trading_day",
                "rebalance_time": "market_open",
                "market_open_time": "10:00",
                "buy_rule": "first_trading_day_open",
                "sell_rule": "last_trading_day_open",
                "execution_mode": "ideal_open",
                "weighting": "equal_weight",
                "if_less_than_top_n": "use_available",
            },
            "scoring": {
                "formula": "x1_plus_x2",
                "use_ttm": True,
                "firm_value_mode": "market_cap",
            },
            "costs": {"commission_rate": 0.001},
            "filters": {
                "require_complete_financial_snapshot": True,
                "require_positive_equity": True,
                "require_positive_net_income_ttm": True,
                "require_positive_previous_net_income_ttm": True,
                "require_positive_operating_profit_ttm": True,
                "require_positive_firm_value": True,
                "require_shares_outstanding": True,
                "min_avg_turnover_20d": 1_000_000,
            },
            "backtest": {
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "initial_capital": 100000,
            },
        }

        result = config_module.BacktestConfig.model_validate(values)

        assert result.data.duckdb_path == Path("data/test.duckdb")
        assert result.data.price_preload_start == date(2023, 12, 1)
        assert result.data.financial_preload_start == date(2023, 1, 1)
        assert result.universe.membership_file == Path("data/universe/membership.csv")
        assert result.universe.monthly_snapshot_file == Path("data/universe/monthly.csv")
        assert result.backtest.start_date == date(2024, 1, 1)
        assert result.model_dump()["project"]["name"] == "test"


class TestLoadUniverseFiles:
    def test_loadStaticUniverse_validCsv_returnsUppercaseSymbols(self, tmp_path):
        symbols_file = tmp_path / "symbols.csv"
        symbols_file.write_text("symbol\naaa\nBBB\n", encoding="utf-8")
        expected = ["AAA", "BBB"]

        result = load_static_universe(symbols_file)

        assert result == expected

    def test_loadStaticUniverse_aliasFile_mapsOldSymbolToCanonical(self, tmp_path):
        symbols_file = tmp_path / "symbols.csv"
        aliases_file = tmp_path / "aliases.csv"
        symbols_file.write_text("symbol\nold1\nNEW1\n", encoding="utf-8")
        aliases_file.write_text(
            "canonical_symbol,symbol,valid_from,valid_to,company_name,change_type,source_url\nNEW1,OLD1,2019-01-01,,Demo,rename,src\nNEW1,NEW1,2019-01-01,,Demo,rename,src\n",
            encoding="utf-8",
        )

        result = load_static_universe(symbols_file, aliases_file)

        assert result == ["NEW1"]

    def test_loadUniverseMembership_validCsv_returnsDateColumns(self, tmp_path):
        membership_file = tmp_path / "membership.csv"
        membership_file.write_text("symbol,universe_name,start_date,end_date\naaa,BIST_SANAYI,2020-01-01,\n", encoding="utf-8")
        expected = pd.Timestamp("2020-01-01").date()

        result = load_universe_membership(membership_file)

        assert result["symbol"].iloc[0] == "AAA"
        assert result["start_date"].iloc[0] == expected

    def test_loadUniverseMembership_aliasFile_mapsHistoricalSymbolToCanonical(self, tmp_path):
        membership_file = tmp_path / "membership.csv"
        aliases_file = tmp_path / "aliases.csv"
        membership_file.write_text(
            "symbol,universe_name,start_date,end_date\nold1,BIST_SANAYI,2020-01-01,2021-12-31\nnew1,BIST_SANAYI,2022-01-01,\n",
            encoding="utf-8",
        )
        aliases_file.write_text(
            "canonical_symbol,symbol,valid_from,valid_to,company_name,change_type,source_url\nNEW1,OLD1,2019-01-01,2021-12-31,Demo,rename,src\nNEW1,NEW1,2022-01-01,,Demo,rename,src\n",
            encoding="utf-8",
        )

        result = load_universe_membership(membership_file, aliases_file)

        assert result["symbol"].tolist() == ["NEW1", "NEW1"]

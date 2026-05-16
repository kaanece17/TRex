from datetime import date

import pandas as pd

from bist_factor_backtest.data.symbol_aliases import (
    apply_symbol_aliases,
    canonical_symbol_as_of,
    canonical_symbol_map,
    canonicalize_symbol_list,
    load_symbol_aliases,
)


class TestLoadSymbolAliases:
    def test_loadSymbolAliases_emptyFile_returnsExpectedColumns(self, tmp_path):
        aliases_file = tmp_path / "aliases.csv"
        aliases_file.write_text("canonical_symbol,symbol,valid_from,valid_to\n", encoding="utf-8")

        result = load_symbol_aliases(aliases_file)

        assert result.columns.tolist() == ["canonical_symbol", "symbol", "valid_from", "valid_to"]
        assert result.empty

    def test_loadSymbolAliases_validFile_normalizesDatesAndCase(self, tmp_path):
        aliases_file = tmp_path / "aliases.csv"
        aliases_file.write_text(
            "canonical_symbol,symbol,valid_from,valid_to\nnew1,old1,2020-01-01,2021-12-31\n",
            encoding="utf-8",
        )

        result = load_symbol_aliases(aliases_file)

        assert result.iloc[0].to_dict() == {
            "canonical_symbol": "NEW1",
            "symbol": "OLD1",
            "valid_from": date(2020, 1, 1),
            "valid_to": date(2021, 12, 31),
        }


class TestCanonicalSymbolHelpers:
    def test_canonicalSymbolMap_emptyAliases_returnsEmptyLookup(self):
        assert canonical_symbol_map(pd.DataFrame()) == {}

    def test_canonicalSymbolMap_validAliases_returnsLookup(self):
        aliases = pd.DataFrame(
            [
                {"canonical_symbol": "NEW1", "symbol": "OLD1"},
                {"canonical_symbol": "NEW1", "symbol": "NEW1"},
            ]
        )

        result = canonical_symbol_map(aliases)

        assert result == {"OLD1": "NEW1", "NEW1": "NEW1"}

    def test_applySymbolAliases_noSymbolColumn_returnsCopyUnchanged(self):
        data = pd.DataFrame([{"ticker": "OLD1"}])
        aliases = pd.DataFrame([{"canonical_symbol": "NEW1", "symbol": "OLD1"}])

        result = apply_symbol_aliases(data, aliases)

        assert result.to_dict("records") == [{"ticker": "OLD1"}]
        assert result is not data

    def test_applySymbolAliases_emptyAliases_returnsCopyUnchanged(self):
        data = pd.DataFrame([{"symbol": "OLD1"}])

        result = apply_symbol_aliases(data, pd.DataFrame())

        assert result.to_dict("records") == [{"symbol": "OLD1"}]
        assert result is not data

    def test_applySymbolAliases_validAliases_mapsToCanonical(self):
        data = pd.DataFrame([{"symbol": "old1"}, {"symbol": "keep"}])
        aliases = pd.DataFrame([{"canonical_symbol": "NEW1", "symbol": "OLD1"}])

        result = apply_symbol_aliases(data, aliases)

        assert result["symbol"].tolist() == ["NEW1", "KEEP"]

    def test_canonicalizeSymbolList_emptyAliases_returnsUppercase(self):
        result = canonicalize_symbol_list(["old1", "new1"], pd.DataFrame())

        assert result == ["OLD1", "NEW1"]

    def test_canonicalizeSymbolList_validAliases_deduplicatesCanonical(self):
        aliases = pd.DataFrame(
            [
                {"canonical_symbol": "NEW1", "symbol": "OLD1"},
                {"canonical_symbol": "NEW1", "symbol": "NEW1"},
            ]
        )

        result = canonicalize_symbol_list(["old1", "NEW1", "other"], aliases)

        assert result == ["NEW1", "OTHER"]

    def test_canonicalSymbolAsOf_emptyAliases_returnsUppercaseSymbol(self):
        assert canonical_symbol_as_of("old1", pd.DataFrame()) == "OLD1"

    def test_canonicalSymbolAsOf_missingSymbol_returnsUppercaseSymbol(self):
        aliases = pd.DataFrame([{"canonical_symbol": "NEW1", "symbol": "OLD1"}])

        assert canonical_symbol_as_of("other", aliases, date(2020, 1, 1)) == "OTHER"

    def test_canonicalSymbolAsOf_withoutDate_returnsFirstCanonicalMatch(self):
        aliases = pd.DataFrame([{"canonical_symbol": "NEW1", "symbol": "OLD1"}])

        assert canonical_symbol_as_of("old1", aliases) == "NEW1"

    def test_canonicalSymbolAsOf_withDate_returnsDatedCanonicalMatch(self):
        aliases = pd.DataFrame(
            [
                {
                    "canonical_symbol": "NEW1",
                    "symbol": "OLD1",
                    "valid_from": date(2020, 1, 1),
                    "valid_to": date(2021, 12, 31),
                }
            ]
        )

        result = canonical_symbol_as_of("old1", aliases, date(2020, 6, 1))

        assert result == "NEW1"

    def test_canonicalSymbolAsOf_noDatedMatch_returnsFirstCanonicalMatch(self):
        aliases = pd.DataFrame(
            [
                {
                    "canonical_symbol": "NEW1",
                    "symbol": "OLD1",
                    "valid_from": date(2020, 1, 1),
                    "valid_to": date(2021, 12, 31),
                }
            ]
        )

        result = canonical_symbol_as_of("old1", aliases, date(2025, 1, 1))

        assert result == "NEW1"

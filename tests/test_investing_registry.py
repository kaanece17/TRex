from __future__ import annotations

import pandas as pd

from bist_factor_backtest.data.investing_registry import (
    build_registry_urls,
    bootstrap_investing_registry,
    load_investing_registry,
    validate_investing_registry,
)


class TestInvestingRegistry:
    def test_loadInvestingRegistry_addsOptionalColumnsWithoutAliasFile(self, tmp_path):
        registry_file = tmp_path / "registry.csv"
        registry_file.write_text("symbol\naksa\n", encoding="utf-8")

        result = load_investing_registry(registry_file)

        assert result.loc[0, "symbol"] == "AKSA"
        assert result.loc[0, "investing_slug"] is None
        assert result.loc[0, "earnings_url"] is None
        assert result.loc[0, "is_active"] is None
        assert result.loc[0, "notes"] is None

    def test_loadInvestingRegistry_preservesBooleanIsActive(self, tmp_path):
        registry_file = tmp_path / "registry.csv"
        pd.DataFrame([{"symbol": "aksa", "is_active": True}]).to_csv(registry_file, index=False)

        result = load_investing_registry(registry_file)

        assert result.loc[0, "is_active"] == True

    def test_loadInvestingRegistry_normalizesAndCanonicalizes(self, tmp_path):
        registry_file = tmp_path / "registry.csv"
        registry_file.write_text(
            "symbol,investing_slug,earnings_url,is_active,notes\n"
            "eski, old-slug, ,yes, test \n",
            encoding="utf-8",
        )
        aliases_file = tmp_path / "aliases.csv"
        aliases_file.write_text(
            "canonical_symbol,symbol,valid_from,valid_to,company_name,change_type,source_url\n"
            "YENI,ESKI,2020-01-01,,Company,rename,https://example.com\n",
            encoding="utf-8",
        )

        result = load_investing_registry(registry_file, aliases_file)

        assert result.loc[0, "symbol"] == "YENI"
        assert result.loc[0, "investing_slug"] == "old-slug"
        assert result.loc[0, "earnings_url"] is None
        assert result.loc[0, "is_active"] == True
        assert result.loc[0, "notes"] == "test"

    def test_loadInvestingRegistry_aliasDuplicates_collapseIntoSingleCanonicalRow(self, tmp_path):
        registry_file = tmp_path / "registry.csv"
        registry_file.write_text(
            "symbol,investing_slug,earnings_url,is_active,notes\n"
            "yeni,new-slug,,true,current\n"
            "eski,,https://example.com/legacy,true,legacy\n",
            encoding="utf-8",
        )
        aliases_file = tmp_path / "aliases.csv"
        aliases_file.write_text(
            "canonical_symbol,symbol,valid_from,valid_to,company_name,change_type,source_url\n"
            "YENI,ESKI,2020-01-01,,Company,rename,https://example.com\n",
            encoding="utf-8",
        )

        result = load_investing_registry(registry_file, aliases_file)

        assert result["symbol"].tolist() == ["YENI"]
        assert result.loc[0, "investing_slug"] == "new-slug"
        assert result.loc[0, "earnings_url"] == "https://example.com/legacy"
        assert result.loc[0, "is_active"] == True
        assert result.loc[0, "notes"] == "current | legacy"

    def test_loadInvestingRegistry_missingColumn_raises(self, tmp_path):
        registry_file = tmp_path / "registry.csv"
        registry_file.write_text("investing_slug\nslug\n", encoding="utf-8")

        try:
            load_investing_registry(registry_file)
        except ValueError as error:
            assert "missing required column: symbol" in str(error)
        else:
            raise AssertionError("expected ValueError")

    def test_validateInvestingRegistry_detectsMissingAndDuplicates(self):
        registry = pd.DataFrame(
            [
                {"symbol": "AAA", "investing_slug": None, "earnings_url": None},
                {"symbol": "BBB", "investing_slug": "same", "earnings_url": None},
                {"symbol": "BBB", "investing_slug": "same", "earnings_url": None},
            ]
        )

        issues = validate_investing_registry(registry)

        assert "AAA: missing investing_slug_or_earnings_url" in issues
        assert "BBB: duplicate_symbol" in issues
        assert "same: duplicate_investing_slug" in issues

    def test_buildRegistryUrls_prefersExplicitUrlAndBuildsFromSlug(self):
        registry = pd.DataFrame(
            [
                {"symbol": "AAA", "investing_slug": "aaa-slug", "earnings_url": None},
                {"symbol": "BBB", "investing_slug": "bbb-slug", "earnings_url": "https://example.com/custom"},
            ]
        )

        result = build_registry_urls(registry)

        assert result.loc[0, "earnings_url"] == "https://tr.investing.com/equities/aaa-slug-earnings"
        assert result.loc[1, "earnings_url"] == "https://example.com/custom"

    def test_registryHelpers_coverEmptyAndFalseyCases(self):
        assert validate_investing_registry(pd.DataFrame()) == []

        registry = pd.DataFrame(
            [
                {"symbol": "AAA", "investing_slug": None, "earnings_url": None},
                {"symbol": "BBB", "investing_slug": None, "earnings_url": " "},
                {"symbol": "CCC", "investing_slug": None, "earnings_url": None, "is_active": False},
            ]
        )

        built = build_registry_urls(registry)

        assert pd.isna(built.loc[0, "earnings_url"])
        assert pd.isna(built.loc[1, "earnings_url"])
        assert pd.isna(built.loc[2, "earnings_url"])

    def test_bootstrapInvestingRegistry_buildsUniverseRowsAndPreservesExisting(self):
        existing = pd.DataFrame(
            [
                {"symbol": "BBB", "investing_slug": "bbb-slug", "earnings_url": None, "is_active": True, "notes": "kept"},
                {"symbol": "CCC", "investing_slug": "old", "earnings_url": "https://example.com/ccc", "is_active": False, "notes": None},
                {"symbol": "CCC", "investing_slug": "ignored", "earnings_url": None, "is_active": None, "notes": "dup"},
            ]
        )

        result = bootstrap_investing_registry(["ccc", "aaa", "bbb", "aaa"], existing)

        assert result["symbol"].tolist() == ["AAA", "BBB", "CCC"]
        assert pd.isna(result.loc[0, "investing_slug"])
        assert result.loc[1, "investing_slug"] == "bbb-slug"
        assert result.loc[1, "is_active"] == True
        assert result.loc[1, "notes"] == "kept"
        assert result.loc[2, "earnings_url"] == "https://example.com/ccc"

    def test_bootstrapInvestingRegistry_withoutExisting_returnsDefaultColumns(self):
        result = bootstrap_investing_registry(["bbb", "aaa"])

        assert result["symbol"].tolist() == ["AAA", "BBB"]
        assert result.columns.tolist() == ["symbol", "investing_slug", "earnings_url", "is_active", "notes"]

    def test_bootstrapInvestingRegistry_addsMissingOptionalColumnsFromExisting(self):
        existing = pd.DataFrame([{"symbol": "AAA"}])

        result = bootstrap_investing_registry(["AAA"], existing)

        assert result.loc[0, "symbol"] == "AAA"
        assert pd.isna(result.loc[0, "investing_slug"])
        assert pd.isna(result.loc[0, "earnings_url"])
        assert pd.isna(result.loc[0, "is_active"])
        assert pd.isna(result.loc[0, "notes"])

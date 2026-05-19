from datetime import date

import pandas as pd

from bist_factor_backtest.data.index_announcements import (
    extract_xusin_changes_from_kap_html,
    manual_2022_sector_restructure_changes,
    parse_bist_index_announcement_rows,
)
from bist_factor_backtest.data.universe import (
    build_current_static_membership,
    build_universe_monthly_snapshot,
    fetch_current_static_xusin_membership,
    parse_cnbce_bist_codes,
    reconstruct_membership_from_current,
)


class TestParseCnbceBistCodes:
    def test_parseCnbceBistCodes_hisseLinks_returnsSymbols(self):
        html = """
        <a href="/borsa/hisseler/acsel-aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as">ACSEL</a>
        <a href="/borsa/hisseler/froto-ford-otomotiv-sanayi-as">FROTO</a>
        """
        expected = ["ACSEL", "FROTO"]

        result = parse_cnbce_bist_codes(html)

        assert result == expected

    def test_parseCnbceBistCodes_nonHisseAndInvalidLinks_skipsInvalidLinks(self):
        html = """
        <a href="/borsa/endeksler/bist-sinai">XUSIN</a>
        <a href="/borsa/hisseler/acsel">ACSEL</a>
        <a href="/borsa/hisseler/a.b-invalid-name">BAD</a>
        """
        expected = []

        result = parse_cnbce_bist_codes(html)

        assert result == expected

    def test_fetchCurrentStaticXusinMembership_validResponse_returnsMembership(self, monkeypatch):
        class Response:
            text = '<a href="/borsa/hisseler/froto-ford-otomotiv-sanayi-as">FROTO</a>'

            def raise_for_status(self):
                return None

        monkeypatch.setattr("bist_factor_backtest.data.universe.requests.get", lambda url, timeout: Response())

        result = fetch_current_static_xusin_membership("https://example.test", date(2020, 1, 1))

        assert result["symbol"].tolist() == ["FROTO"]


class TestReconstructMembershipFromCurrent:
    def test_reconstructMembershipFromCurrent_reverseAddAndRemove_returnsHistoricalIntervals(self):
        current_symbols = ["AAA"]
        changes = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "action": "add",
                    "effective_date": "2021-01-01",
                    "source_type": "kap_announcement",
                    "source_url": "kap://add",
                    "confidence": "high",
                },
                {
                    "symbol": "BBB",
                    "action": "remove",
                    "effective_date": "2022-01-01",
                    "source_type": "kap_announcement",
                    "source_url": "kap://remove",
                    "confidence": "medium",
                },
            ]
        )

        result = reconstruct_membership_from_current(current_symbols, changes, date(2026, 1, 1), date(2020, 1, 1))

        aaa = result[result["symbol"] == "AAA"].iloc[0]
        bbb = result[result["symbol"] == "BBB"].iloc[0]
        assert aaa["start_date"] == date(2021, 1, 1)
        assert aaa["confidence"] == "high"
        assert bbb["start_date"] == date(2020, 1, 1)
        assert bbb["end_date"] == date(2021, 12, 31)

    def test_reconstructMembershipFromCurrent_addThenRemove_returnsClosedHistoricalInterval(self):
        current_symbols = []
        changes = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "action": "add",
                    "effective_date": "2021-01-01",
                    "source_type": "kap_announcement",
                    "source_url": "kap://add",
                    "confidence": "high",
                },
                {
                    "symbol": "AAA",
                    "action": "remove",
                    "effective_date": "2022-01-01",
                    "source_type": "kap_announcement",
                    "source_url": "kap://remove",
                    "confidence": "medium",
                },
            ]
        )

        result = reconstruct_membership_from_current(current_symbols, changes, date(2026, 1, 1), date(2020, 1, 1))

        expected = {
            "symbol": "AAA",
            "universe_name": "BIST_SANAYI",
            "start_date": date(2021, 1, 1),
            "end_date": date(2021, 12, 31),
            "source_type": "kap_announcement",
            "source_url": "kap://add",
            "confidence": "high",
        }
        assert result.to_dict("records") == [expected]

    def test_reconstructMembershipFromCurrent_emptyChanges_returnsManualSeedMembership(self):
        result = reconstruct_membership_from_current(["AAA"], pd.DataFrame(), date(2026, 1, 1), date(2020, 1, 1))

        assert result["symbol"].tolist() == ["AAA"]
        assert result["source_type"].tolist() == ["manual_seed"]

    def test_buildUniverseMonthlySnapshot_activeMembership_returnsMonthlyRowsWithQuality(self):
        membership = build_current_static_membership(
            ["AAA"],
            date(2020, 1, 1),
            "source",
            universe_name="US_INDUSTRIALS",
        )
        rebalance_dates = pd.DataFrame([{"month": "2020-01", "rebalance_date": date(2020, 1, 2)}])

        result = build_universe_monthly_snapshot(membership, rebalance_dates, "US_INDUSTRIALS")

        assert result["symbol"].tolist() == ["AAA"]
        assert result["source_quality"].tolist() == ["medium"]

    def test_buildUniverseMonthlySnapshot_lowAndHighConfidence_returnsExpectedQuality(self):
        membership = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "universe_name": "BIST_SANAYI",
                    "start_date": date(2020, 1, 1),
                    "end_date": None,
                    "source_type": "kap_announcement",
                    "source_url": "kap",
                    "confidence": "low",
                },
                {
                    "symbol": "BBB",
                    "universe_name": "BIST_SANAYI",
                    "start_date": date(2020, 2, 1),
                    "end_date": None,
                    "source_type": "kap_announcement",
                    "source_url": "kap",
                    "confidence": "high",
                },
            ]
        )
        rebalance_dates = pd.DataFrame(
            [
                {"month": "2020-01", "rebalance_date": date(2020, 1, 2)},
                {"month": "2020-02", "rebalance_date": date(2020, 2, 3)},
            ]
        )

        result = build_universe_monthly_snapshot(membership, rebalance_dates, "BIST_SANAYI")

        assert result[result["month"] == "2020-01"]["source_quality"].tolist() == ["low"]
        assert set(result[result["month"] == "2020-02"]["source_quality"].tolist()) == {"low"}

    def test_buildUniverseMonthlySnapshot_highConfidenceOnly_returnsHighQuality(self):
        membership = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "universe_name": "BIST_SANAYI",
                    "start_date": date(2020, 1, 1),
                    "end_date": None,
                    "source_type": "kap_announcement",
                    "source_url": "kap",
                    "confidence": "high",
                }
            ]
        )
        rebalance_dates = pd.DataFrame([{"month": "2020-01", "rebalance_date": date(2020, 1, 2)}])

        result = build_universe_monthly_snapshot(membership, rebalance_dates, "BIST_SANAYI")

        assert result["source_quality"].tolist() == ["high"]


class TestParseBistIndexAnnouncementRows:
    def test_parseBistIndexAnnouncementRows_sectorRows_returnsKapRowsAfterStartDate(self):
        html = """
        <table>
          <tr>
            <td>05.01.2020</td><td>Old sector</td><td>Tip</td><td>BIST Pay Endeksleri|Sektör</td><td>Sektör</td>
            <td><a href="https://www.kap.org.tr/tr/Bildirim/1">link</a></td>
          </tr>
          <tr>
            <td>05.01.2019</td><td>Too old</td><td>Tip</td><td>BIST Pay Endeksleri|Sektör</td><td>Sektör</td>
            <td><a href="https://www.kap.org.tr/tr/Bildirim/2">link</a></td>
          </tr>
          <tr>
            <td>06.01.2020</td><td>No sector</td><td>Tip</td><td>BIST Pay Endeksleri|Pazar</td><td>Pazar</td>
            <td><a href="https://www.kap.org.tr/tr/Bildirim/3">link</a></td>
          </tr>
        </table>
        """

        result = parse_bist_index_announcement_rows(html, date(2020, 1, 1))

        expected = [
            {
                "announcement_date": date(2020, 1, 5),
                "title": "Old sector",
                "url": "https://www.kap.org.tr/tr/Bildirim/1",
            }
        ]
        assert result.to_dict("records") == expected


class TestExtractXusinChangesFromKapHtml:
    def test_extractXusinChangesFromKapHtml_singleRelatedAdd_returnsHighConfidenceChange(self):
        html = """
        <table>
          <tr><td>İlgili Şirketler Related Companies</td><td>[ABC]</td></tr>
          <tr><td>ABC SANAYI</td><td>XUSIN</td><td></td><td>02/01/2020</td></tr>
        </table>
        """

        result = extract_xusin_changes_from_kap_html(html, "kap://1")

        expected = [
            {
                "symbol": "ABC",
                "action": "add",
                "effective_date": date(2020, 1, 2),
                "source_type": "kap_announcement",
                "source_url": "kap://1",
                "confidence": "high",
            }
        ]
        assert result.to_dict("records") == expected

    def test_extractXusinChangesFromKapHtml_ambiguousKnownNameRemove_returnsMappedMediumConfidenceChange(self):
        html = """
        <table>
          <tr><td>İlgili Şirketler Related Companies</td><td>[ATEKS, SILVR]</td></tr>
          <tr><td>AKIN TEKSTIL</td><td></td><td>XUSIN</td><td>20/03/2025</td></tr>
        </table>
        """

        result = extract_xusin_changes_from_kap_html(html, "kap://2")

        expected = [
            {
                "symbol": "ATEKS",
                "action": "remove",
                "effective_date": date(2025, 3, 20),
                "source_type": "kap_announcement",
                "source_url": "kap://2",
                "confidence": "medium",
            }
        ]
        assert result.to_dict("records") == expected

    def test_manual2022SectorRestructureChanges_always_returnsOfficialManualRemovals(self):
        result = manual_2022_sector_restructure_changes()

        expected = ["DOBUR", "HURGZ", "IHGZT"]
        assert result["symbol"].tolist() == expected
        assert result["effective_date"].tolist() == [date(2022, 6, 1), date(2022, 6, 1), date(2022, 6, 1)]

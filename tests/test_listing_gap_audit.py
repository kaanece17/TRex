from __future__ import annotations

from datetime import date

import pandas as pd

from bist_factor_backtest.data.listing_gap_audit import build_listing_gap_audit


def test_buildListingGapAudit_splitsKnownListingDateIntoPreAndPost():
    snapshots = pd.DataFrame(
        [
            {"symbol": "FADE", "period_end": "2019-03-01", "announcement_date": None},
            {"symbol": "FADE", "period_end": "2020-06-01", "announcement_date": None},
            {"symbol": "FADE", "period_end": "2020-09-01", "announcement_date": None},
            {"symbol": "FADE", "period_end": "2020-12-01", "announcement_date": "2021-02-19"},
        ]
    )
    listing_dates = pd.DataFrame(
        [
            {"symbol": "FADE", "listing_date": date(2020, 7, 30), "source": "x", "notes": "y"},
        ]
    )

    audit = build_listing_gap_audit(snapshots, listing_dates, audit_start_date=date(2019, 1, 1))

    assert audit.to_dict("records") == [
        {
            "symbol": "FADE",
            "listing_date": date(2020, 7, 30),
            "listing_source": "x",
            "listing_notes": "y",
            "first_statement_period": date(2019, 3, 1),
            "first_announcement_period": date(2020, 12, 1),
            "missing_periods_2019_plus": 3,
            "pre_listing_expected_gap_count": 2,
            "post_listing_fetch_gap_count": 1,
            "unknown_gap_count": 0,
            "first_missing_period": date(2019, 3, 1),
            "last_missing_period": date(2020, 9, 1),
            "listing_gap_class": "mixed_pre_listing_and_post_listing_gap",
        }
    ]


def test_buildListingGapAudit_infersFetchGapWhenPre2019AnnouncementsExist():
    snapshots = pd.DataFrame(
        [
            {"symbol": "IZFAS", "period_end": "2018-12-01", "announcement_date": "2019-03-10"},
            {"symbol": "IZFAS", "period_end": "2020-03-01", "announcement_date": None},
            {"symbol": "IZFAS", "period_end": "2020-06-01", "announcement_date": None},
        ]
    )

    audit = build_listing_gap_audit(snapshots, pd.DataFrame(), audit_start_date=date(2019, 1, 1))

    row = audit.iloc[0].to_dict()
    assert row["post_listing_fetch_gap_count"] == 2
    assert row["pre_listing_expected_gap_count"] == 0
    assert row["unknown_gap_count"] == 0
    assert row["listing_gap_class"] == "post_listing_fetch_gap_only"


def test_buildListingGapAudit_marksUnknownWhenNoListingOrPre2019Announcement():
    snapshots = pd.DataFrame(
        [
            {"symbol": "KLSYN", "period_end": "2019-12-01", "announcement_date": None},
            {"symbol": "KLSYN", "period_end": "2021-09-01", "announcement_date": "2021-11-15"},
        ]
    )

    audit = build_listing_gap_audit(snapshots, pd.DataFrame(), audit_start_date=date(2019, 1, 1))

    row = audit.iloc[0].to_dict()
    assert row["unknown_gap_count"] == 1
    assert row["listing_gap_class"] == "listing_date_unknown"


def test_buildListingGapAudit_collapsesDuplicatePeriodsWhenOneAnnouncementExists():
    snapshots = pd.DataFrame(
        [
            {"symbol": "RUZYE", "period_end": "2026-03-01", "announcement_date": None},
            {"symbol": "RUZYE", "period_end": "2026-03-01", "announcement_date": "2026-05-08"},
            {"symbol": "RUZYE", "period_end": "2025-12-01", "announcement_date": "2026-03-09"},
        ]
    )

    audit = build_listing_gap_audit(snapshots, pd.DataFrame(), audit_start_date=date(2019, 1, 1))

    assert audit.empty

from __future__ import annotations

from datetime import date

from bist_factor_backtest.data.mkk_esirket_announcements import (
    MkkEsirketAnnouncementsLoader,
    _announcement_date_from_metadata,
    _period_end_from_metadata,
)


def test_periodEndFromMetadata_mapsQuarterPeriods():
    assert _period_end_from_metadata({"Yıl": "2024", "Dönem": "1.Dönem"}) == date(2024, 3, 1)
    assert _period_end_from_metadata({"Yıl": "2024", "Dönem": "4.Dönem"}) == date(2024, 12, 1)


def test_announcementDateFromMetadata_parsesDifferentFormats():
    assert _announcement_date_from_metadata({"Yükleme Tarihi": "20221108193356"}) == date(2022, 11, 8)
    assert _announcement_date_from_metadata({"Yükleme Tarihi": "23/09/2024 19:04:24"}) == date(2024, 9, 23)


def test_fetchRecords_buildsDeduplicatedRecords(monkeypatch):
    loader = MkkEsirketAnnouncementsLoader()
    monkeypatch.setattr(
        loader,
        "_fetch_revision_ids",
        lambda tax_no, document_type_text: ["a", "b"],
    )
    monkeypatch.setattr(
        loader,
        "_fetch_revision_metadata",
        lambda revision_ids: [
            {
                "documentMetaDataValuePairs": [
                    {"title": "Yıl", "value": "2024"},
                    {"title": "Dönem", "value": "2.Dönem"},
                    {"title": "Yükleme Tarihi", "value": "23/09/2024 19:04:24"},
                ]
            },
            {
                "documentMetaDataValuePairs": [
                    {"title": "Yıl", "value": "2024"},
                    {"title": "Dönem", "value": "2.Dönem"},
                    {"title": "Yükleme Tarihi", "value": "23/09/2024 19:04:24"},
                ]
            },
        ],
    )

    records = loader.fetch_records("OZRDN")

    assert records == [
        {
            "symbol": "OZRDN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 23),
            "announcement_source_url": "https://e-sirket.mkk.com.tr/?page=company&company=13893",
        }
    ]

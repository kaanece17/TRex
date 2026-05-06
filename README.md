# BIST Monthly Factor Rotation Backtest

Point-in-time (PIT) aylık rotasyon backtest sistemi.  
Hedef evren: BIST sanayi hisseleri.  
Sistem, her ay ilk işlem günü açılışta skorlayıp alır; son işlem günü açılışta satar.

Bu proje araştırma/backtest amaçlıdır, yatırım tavsiyesi değildir.

## Ne yapar

Strateji akışı:
1. Ayın ilk işlem günü bulunur.
2. O an itibarıyla bilinen finansallar seçilir (`announcement_datetime <= market_open_datetime`).
3. Hisseler skorlanır, en yüksek `top_n` seçilir (varsayılan 5).
4. İlk işlem günü `open` fiyattan alım yapılır (eşit ağırlık).
5. Ayın son işlem günü `open` fiyattan satış yapılır.
6. Aylık sonuçlar, pozisyonlar ve kaynak finansallar raporlanır.

## Skor formülü

```text
market_cap = firm_value_price * shares_outstanding
firm_value = market_cap + total_debt - cash

net_income_growth = (net_income_ttm - previous_net_income_ttm) / previous_net_income_ttm
x1 = (net_income_ttm / equity) * (1 + net_income_growth)
x2 = operating_profit_ttm / firm_value
score = x1 + x2
```

`previous_net_income_ttm`: bir önceki çeyrek değil, önceki yıl aynı çeyrek TTM.

## PIT ve veri kuralları

- `backtest.start_date`: `2020-01-01`
- Fiyat preload başlangıcı: en az `2019-12-01`
- Finansal preload başlangıcı: en az `2018-01-01`
- `shares_outstanding` kaynağı: KAP finansal raporu (`ifrs-full_IssuedCapital / Ödenmiş Sermaye`)
- Yfinance shares snapshot için kullanılmaz.
- Date-only fallback: `announcement_date < first_trading_day`
- `reconstructed_historical` evren modu explicit üyelik dosyası ister; sessiz fallback yoktur.

## Kurulum

```bash
python3 -m pip install -e ".[dev]"
```

CLI komutlarını iki şekilde çalıştırabilirsin:

```bash
bist-backtest --help
```

veya:

```bash
PYTHONPATH=src python3 -m bist_factor_backtest.cli --help
```

## CLI komutları

### `init-data`
`data/universe` altında başlangıç template dosyalarını oluşturur.

### `load-current-xusin-universe --config config.yaml`
Güncel static XUSIN benzeri evreni yükler/yazar.

### `reconstruct-xusin-universe --config config.yaml`
BIST/KAP duyurularından historical üyelik rekonstrüksiyonu üretir ve `universe_membership` tablosuna yazar.

### `load-prices --config config.yaml`
Yfinance ile fiyatları çeker ve `market_prices` tablosuna yazar.

### `load-financials-kap --config config.yaml [opsiyonlar]`
KAP finansallarını çeker/upsert eder.
Önemli opsiyonlar:
- `--strict`
- `--max-retries`
- `--backoff-seconds`
- `--request-timeout-seconds`
- `--min-request-interval-seconds`
- `--rate-limit-sleep-seconds`
- `--preflight-checks`
- `--only-incomplete` (DB durumuna göre sadece incomplete/failed sembolleri koşturur)

### `load-financials-kap-incomplete --config config.yaml [opsiyonlar]`
`load-financials-kap --only-incomplete` kısa yoludur.

### `build-snapshots --config config.yaml`
`financial_statements` + `financial_statement_items` üzerinden normalize snapshot + TTM alanlarını üretir.

### `run --config config.yaml`
Aylık backtest çalıştırır; sonuçları DB’ye yazar (`backtest_monthly_results`, `backtest_selected_positions`).

### `export-report --config config.yaml --output reports/backtest_report.xlsx`
Excel raporu üretir.

## Önerilen çalışma sırası

```bash
PYTHONPATH=src python3 -m bist_factor_backtest.cli init-data
PYTHONPATH=src python3 -m bist_factor_backtest.cli reconstruct-xusin-universe --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli load-prices --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli load-financials-kap --config config.yaml
# tekrar denemeler için:
PYTHONPATH=src python3 -m bist_factor_backtest.cli load-financials-kap-incomplete --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli build-snapshots --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli run --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli export-report --config config.yaml --output reports/backtest_report.xlsx
```

## Dikkat edilmesi gerekenler

- KAP tarafında 429/500 veya parse uyumsuzluğu görülebilir; bu nedenle incomplete run tekrarı normaldir.
- `statement_load_status` tablosu sembol durumunu (`completed/incomplete/failed`) tutar.
- `load-financials-kap-incomplete` hız için önerilen günlük komuttur.
- Bazı semboller KAP şirket listesinde bulunamaz veya disclosure yapısı farklı olabilir.
- Universe kalitesi raporda açıkça not edilmelidir (`current_static` vs `reconstructed_historical`).

## Çıktılar

- DB: `data/bist_backtest.duckdb`
- Raporlar: `reports/*.xlsx`
- Önemli tablolar:
  - `financial_statements`
  - `financial_statement_items`
  - `financial_snapshots`
  - `market_prices`
  - `universe_membership`
  - `backtest_monthly_results`
  - `backtest_selected_positions`

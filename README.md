# BIST Monthly Factor Rotation Backtest

Point-in-time (PIT) aylik rotasyon backtest sistemi.
Hedef evren: BIST sanayi hisseleri.
Sistem, her ay ilk islem gunu acilista skorlayip alir; son islem gunu acilista satar.

Bu dokuman proje README'si olmanin yani sira calisan spesifikasyondur.
Amac, veri kaynaklari degisse bile backtest davranisinin degismeyecegi net kurallari tanimlamaktir.

Bu proje arastirma/backtest amaclidir, yatirim tavsiyesi degildir.

## Sistem Ozeti

Strateji akisi:
1. Ayin ilk ve son islem gunu bulunur.
2. Rebalance aninda bilinen finansallar secilir.
3. O tarihte aktif olan BIST sanayi evreni uygulanir.
4. Aday hisselere likidite, firma degeri ve skor hesaplari uygulanir.
5. Filtrelerden gecen hisseler arasindan en yuksek `top_n` secilir.
6. Ilk islem gunu `open` fiyattan alim, son islem gunu `open` fiyattan satis yapilir.
7. Aylik sonuclar, secilen pozisyonlar ve kullanilan finansal kaynaklar DB'ye yazilir.

## Temel Ilkeler

Bu projede en onemli kavramlar:
- point-in-time dogruluk
- doneme uygun finansal veri
- doneme uygun pay adedi (`shares_outstanding`)
- tarihsel evren uyeligi
- sembol degisikliklerinde tek sirket kimligi

Backtest motoru sembolleri sadece fiyat kodu olarak degil, sirket kimliginin zamani gelmis bir temsili olarak ele almalidir.

## Skor Formulu

```text
market_cap = firm_value_price * shares_outstanding
firm_value = market_cap + total_debt - cash

net_income_growth = (net_income_ttm - previous_net_income_ttm) / previous_net_income_ttm
x1 = (net_income_ttm / equity) * (1 + net_income_growth)
x2 = operating_profit_ttm / firm_value
score = x1 + x2
```

`previous_net_income_ttm`: onceki ceyrek degil, onceki yil ayni ceyrek TTM.

## Veri Spesifikasyonu

Backtest icin asagidaki alanlar gereklidir:
- `symbol`
- `period_end`
- `fiscal_year`
- `fiscal_period`
- `announcement_datetime` veya en azindan `announcement_date`
- `net_income`
- `equity`
- `operating_profit`
- `cash`
- `total_debt`
- `shares_outstanding`
- `source_statement_id`
- `source_url`

Fiyat verisi icin:
- `symbol`
- `date`
- `open`
- `high`
- `low`
- `close`
- `adjusted_close`
- `volume`

Evren verisi icin:
- `symbol`
- `universe_name`
- `start_date`
- `end_date`
- `source_type`
- `source_url`
- `confidence`

Sembol kimligi / rename destegi icin:
- `canonical_symbol`
- `symbol`
- `valid_from`
- `valid_to`
- `company_name`
- `change_type`
- `source_url`

## PIT Kurallari

PIT davranisi degistirilemez cekirdek kuraldir.

- Esas kural: `announcement_datetime <= market_open_datetime`
- Eger saat bilgisi yoksa fallback: `announcement_date < first_trading_day`
- Ayni gun aciklanan ama acilistansonra yayinlanan veri kullanilamaz
- `firm_value_price`, rebalance gununden onceki son mevcut fiyattan alinmalidir
- `shares_outstanding`, ilgili finansal doneme ait aciklanmis deger olmalidir
- Sonradan ogrenilen ya da bugunku bilgiler gecmise tasinamaz

## Shares Outstanding Kurali

`shares_outstanding` alaninin anlami:
- sirketin ilgili finansal donemde acikladigi odenmis sermaye / pay adedi temsilidir
- bugunku snapshot degeri kullanilamaz
- donemler arasi sermaye degisimleri PIT mantigi ile izlenmelidir

Bu proje icin kabul edilen ilke:
- `shares_outstanding` sirketin ilgili donemde acikladigi finansal rapordan veya ayni doneme bagli sirket finansal ekranindan gelmelidir
- genel amacli anlik piyasa sitelerinden gelen tek bir bugunku deger yeterli degildir

## Announcement Date Kurali

`announcement_date` olmazsa proje PIT dogrulugunu kaybeder.

Bu alan icin kabul edilen minimum standart:
- her finansal donem icin yayin tarihi bulunabilmeli
- bu tarih `period_end` ile eslestirilebilmeli
- veri kaynagi sembol bazli tarihsel liste sunmali

`announcement_datetime` varsa tercih edilir.
Yoksa `announcement_date` kullanilir.

## Sembol Degisikligi / Tek Sirket Kimligi

Bazi BIST sirketleri zaman icinde:
- ticker degistirebilir
- ticari unvan degistirebilir
- eski sembolle yayinlanmis finansallara sahip olabilir

Bu durumda backtest ayni sirketi iki farkli sirket gibi gormemelidir.

Bu nedenle proje bir alias / lineage katmani kullanir:
- `data/universe/bist_sanayi_symbol_aliases.csv`
- `universe.symbol_aliases_file`

Kurallar:
- eski ve yeni semboller tek bir `canonical_symbol` altinda toplanabilir
- fiyat verisi kendi donem semboluyle gelebilir
- finansallar kendi donem semboluyle gelebilir
- fakat evren ve secim asamasinda bunlar tek sirket olarak ele alinabilmelidir
- alias eslemesi tarih-duyarli olmalidir

Alias katmani birlesme/devralma mantigi degil, once ticker/name degisikliklerini cozmeyi hedefler.

## Evren Spesifikasyonu

Varsayilan hedef evren:
- BIST sanayi hisseleri

Modlar:
- `current_static`
- `reconstructed_historical`

Kurallar:
- `reconstructed_historical` mod explicit uyelik dosyasi ister
- sessiz fallback yoktur
- evren kalitesi raporda acikca belirtilmelidir

Universe reconstruction girdileri:
- mevcut sembol listesi
- BIST endeks duyurulari
- manuel duzeltme kayitlari
- sembol alias / rename kayitlari

## Tarih Araligi Kurallari

- `backtest.start_date`: en az `2020-01-01`
- fiyat preload baslangici: en az `2019-12-01`
- finansal preload baslangici: en az `2018-01-01`

Not:
- butun bugunku semboller icin 2019 verisi beklenmez
- 2019 sonrasi halka arz olan ya da gec listeye giren sirketler daha gec baslar
- bu nedenle coverage audit sembol bazli yapilmalidir

## Veri Kaynagi Stratejisi

Projede veri kaynagi bir implementasyon detayidir; spesifikasyon degil.
Fakat backtest davranisini korumak icin kaynaklarin saglamasi gereken seyler aciktir.

### Finansal degerler

Asagidaki alanlar tekil donemler bazinda cekilebilmelidir:
- `net_income`
- `equity`
- `operating_profit`
- `cash`
- `total_debt`
- `shares_outstanding`

### Yayin tarihi

Her `period_end` icin:
- `announcement_date`
- mumkunse `announcement_datetime`

### Kabul Edilen Kaynak Mantigi

Kaynaklar hibrit olabilir.
Ornek:
- finansal tablo degerleri bir merkezi kaynaktan
- `announcement_date` baska bir merkezi kaynaktan
- rename / alias bilgisi manuel ya da yari-otomatik bir tablodan

Onemli olan ayni donem icin alanlarin tutarli sekilde eslestirilmesidir.

## Onaylanan Hibrit Kaynak Modeli

Bu proje icin su operasyonel model kabul edilmistir:

### 1. Finansal tablo degerleri

Merkezi kaynak:
- Is Yatirim / `isyatirimhisse` veya dogrudan Is Yatirim finansal ekranlari

Bu kaynaktan alinmasi beklenen alanlar:
- `net_income`
- `equity`
- `operating_profit`
- `cash`
- `total_debt`
- doneme uygun `Odenmis Sermaye`

Bu modelde:
- `Odenmis Sermaye` -> `shares_outstanding` olarak normalize edilir
- bugunku anlik pay adedi degil, ilgili finansal donemin aciklanmis degeri kullanilir

### 2. Announcement date

Merkezi kaynak:
- Investing.com earnings sayfalari

Bu kaynaktan alinmasi beklenen alanlar:
- `Yayin Tarihi` -> `announcement_date`
- `Donem Sonu` -> `period_end` eslestirme anahtari

Bu proje acisindan kabul edilen eslestirme:
- Investing earnings satirindaki `Donem Sonu`
- finansal tablo kaynagindaki ilgili period

### 3. Sirket kimligi / rename

Kaynak:
- repo icindeki alias / lineage dosyasi
- gerekirse manuel destekli arastirma

Ana dosya:
- `data/universe/bist_sanayi_symbol_aliases.csv`

## Kesin Kabul Edilenler

Asagidakiler bu proje icin teknik olarak kabul edilmis varsayimlardir:
- finansal tablo degerleri tek merkezden Is Yatirim tarafindan alinabilir
- tarihsel `announcement_date` tek merkezden Investing earnings sayfalarindan alinabilir
- `shares_outstanding`, Is Yatirim'daki doneme bagli `Odenmis Sermaye` alanindan normalize edilebilir
- mevcut BIST sanayi evreni icin bu hibrit model uygulanabilir

## Kesin Iddia Edilmeyenler

Asagidakileri proje varsayimi olarak yazmiyoruz:
- bu kaynaklarin KAP kadar otoritatif oldugu
- tek bir bedava kaynagin tum alanlari eksiksiz sagladigi
- bugunku tum 248 sembolun 2019'dan itibaren esit coverage sundugu

Bu nedenle coverage audit zorunludur.

## Beklenen Coverage Davranisi

Yeni veri kaynagi veya loader kabul edilmeden once su auditler yapilmalidir:
- her sembol icin ilk mevcut `period_end`
- her sembol icin ilk mevcut `announcement_date`
- her sembol icin `shares_outstanding` coverage orani
- alias gerektiren semboller listesi
- 2019-01-01 sonrasinda hangi sembollerin coverage disi kaldigi

Coverage sonucunda semboller en az uc sinifa ayrilmalidir:
- `fully_covered`
- `partial_history`
- `needs_manual_mapping`

Ek zorunlu coverage kontrolleri:
- `announcement_date` eslesmeyen donemler
- `shares_outstanding` bulunamayan donemler
- alias ihtiyaci olan semboller
- 2019 oncesi veya 2019 sonrasi halka arz kaynakli dogal eksikler

## Loader Mimari Spesifikasyonu

Veri kaynagi gecisi yapilirken monolitik tek loader yerine ayrik sorumluluklar tercih edilmelidir.

### Hedef Mimari

Asagidaki mantik ayrimi hedeflenir:

1. statement-value loader
2. announcement-date loader
3. symbol-alias loader
4. snapshot builder
5. coverage audit araci

### Statement-value loader

Sorumlulugu:
- sembol bazli finansal tablo satirlarini cekmek
- `period_end` bazli normalize etmek
- gerekli kalemleri `financial_statement_items` formatina cevirmek
- ilgili donemin `Odenmis Sermaye` degerini `shares_outstanding` olarak yazmak

Beklenen ciktilar:
- `financial_statements`
- `financial_statement_items`

### Announcement-date loader

Sorumlulugu:
- Investing earnings sayfasindan tarihsel earnings tablosunu cekmek
- `period_end -> announcement_date` map'i uretmek
- statement-value loader sonucuyla merge edilmeye uygun normalize bir tablo vermek

Beklenen cikti:
- statement bazli `announcement_date`
- varsa ek olarak `announcement_datetime`

### Symbol-alias loader

Sorumlulugu:
- eski/yeni ticker zincirlerini tek `canonical_symbol` altinda toplamak
- tarih-duyarli alias kurallarini uygulamak
- backtest oncesi universe ve finansal veri tarafini ayni sirket kimligine baglamak

### Snapshot builder

Sorumlulugu:
- statement-level veri + item-level veri + announcement-date eslestirmesini birlestirmek
- `financial_snapshots` tablosunu uretmek
- TTM hesaplarini calistirmak

### Coverage audit araci

Sorumlulugu:
- 248 sembolun her biri icin coverage raporu cikarmak
- ilk mevcut `period_end`
- ilk mevcut `announcement_date`
- ilk mevcut `shares_outstanding`
- alias gereksinimi
- eslesmeyen donemler

Bu arac sonuc uretmeden veri kaynagi switch'i tamamlanmis sayilmaz.

## kap_loader.py Gecis Plani

Mevcut `kap_loader.py` mantigi bir anda silinmemelidir.

Asamali gecis:
1. yeni loader modulleri eklenir
2. eski KAP loader korunur
3. CLI'da yeni komutlar eklenir
4. coverage audit yapilir
5. yeni loader davranisi testlerle sabitlenir
6. varsayilan yol gerektiğinde yeni loadere cevrilir

Beklenen yeni moduller:
- `data/financials_isyatirim.py`
- `data/earnings_investing.py`
- `data/coverage_audit.py`

Gerekirse yardimci moduller:
- `data/statement_normalization.py`
- `data/period_matching.py`

## CLI Evrim Spesifikasyonu

Mevcut komutlar bozulmadan genisleme tercih edilir.

Onerilen yeni komutlar:
- `load-financials-isyatirim --config config.yaml`
- `load-announcement-dates-investing --config config.yaml`
- `audit-financial-coverage --config config.yaml`

Gecis su mantikla yapilabilir:
- `load-financials-isyatirim` sadece statement/value tarafini yukler
- `load-announcement-dates-investing` announcement tarafini yukler veya merge eder
- `build-snapshots` bu iki katmani tek PIT snapshot'a donusturur

## Eslestirme Kurallari

Statement-value loader ile announcement-date loader arasindaki merge kurali acik olmalidir.

Birincil anahtar mantigi:
- `canonical_symbol`
- `period_end`

Ikincil yardimci alanlar:
- `fiscal_year`
- `fiscal_period`

Merge kurallari:
- bire bir eslesme varsa dogrudan baglanir
- birden fazla aday varsa manual review gerekli sayilir
- announcement verisi olmayan donem PIT-gecersiz kabul edilir
- shares verisi olmayan donem filtreye giremez

## Retry ve Hata Yonetimi

Pipeline parcali calismalidir.

Gerekli ozellikler:
- statement-value retry
- announcement-date retry
- symbol bazli eksik coverage listesi
- donem bazli eksik merge listesi

Eksik veri durumlari:
- `missing_statement_values`
- `missing_announcement_date`
- `missing_shares_outstanding`
- `alias_unresolved`
- `period_match_failed`

Bu statuler DB veya audit ciktilarinda izlenebilir olmalidir.

## Test Spesifikasyonu

Yeni hibrit model icin zorunlu testler:
- Is Yatirim statement verisi `financial_statement_items` formatina dogru normalize ediliyor
- `Odenmis Sermaye` -> `shares_outstanding` dogru donusuyor
- Investing earnings `Donem Sonu` -> `announcement_date` map'i uretiyor
- statement + earnings merge'i `canonical_symbol` ve `period_end` ile dogru calisiyor
- alias'li sembollerde eski ve yeni ticker ayni sirket olarak ele aliniyor
- `announcement_date <= rebalance date/time` mantigi korunuyor
- `announcement_date` olmayan donemler secime girmiyor
- `shares_outstanding` olmayan donemler secime girmiyor
- coverage audit yeni halka arzlari `partial_history` olarak raporluyor

## Uygulama Sirasi

Bu migration icin onerilen sira:
1. Is Yatirim statement loader tasarla
2. Investing earnings loader tasarla
3. period matching kurallarini uygula
4. alias katmaniyla canonical symbol eslestirmesini uygula
5. coverage audit araci yaz
6. 248 sembolun auditini calistir
7. eksik symbol/date/pay adedi durumlarini dosyala
8. ancak bundan sonra varsayilan finansal loader degisikligini degerlendir

## Depolama

Varsayilan DB:
- `data/bist_backtest.duckdb`

Onemli tablolar:
- `financial_statements`
- `financial_statement_items`
- `financial_snapshots`
- `market_prices`
- `universe_membership`
- `statement_load_status`
- `backtest_monthly_results`
- `backtest_selected_positions`

Mevcut schema'ya ek olarak sembol alias / lineage verisi dosya tabanli tutulur:
- `data/universe/bist_sanayi_symbol_aliases.csv`

Ihtiyac halinde ileride DB tablosuna tasinabilir.

## CLI Komutlari

### `init-data`
`data/universe` altinda baslangic template dosyalarini olusturur.

### `load-current-xusin-universe --config config.yaml`
Guncel static XUSIN benzeri evreni yukler/yazar.

### `reconstruct-xusin-universe --config config.yaml`
BIST/KAP duyurularindan historical uyelik rekonstruksiyonu uretir ve `universe_membership` tablosuna yazar.

### `load-prices --config config.yaml`
Fiyat verilerini ceker ve `market_prices` tablosuna yazar.

### `load-financials-kap --config config.yaml [opsiyonlar]`
Mevcut implementasyonda KAP tabanli finansal yukleme komutudur.
Bu komut bugunku durumda calisir, ancak spesifikasyon veri kaynagini KAP ile sinirlamaz.

Onemli opsiyonlar:
- `--strict`
- `--max-retries`
- `--backoff-seconds`
- `--request-timeout-seconds`
- `--min-request-interval-seconds`
- `--rate-limit-sleep-seconds`
- `--preflight-checks`
- `--only-incomplete`

### `load-financials-kap-incomplete --config config.yaml [opsiyonlar]`
`load-financials-kap --only-incomplete` kisayoludur.

### `build-snapshots --config config.yaml`
`financial_statements` + `financial_statement_items` uzerinden normalize snapshot + TTM alanlarini uretir.

### `run --config config.yaml`
Aylik backtest calistirir; sonuclari DB'ye yazar.

### `export-report --config config.yaml --output reports/backtest_report.xlsx`
Excel raporu uretir.

## Onerilen Calisma Sirasi

```bash
PYTHONPATH=src python3 -m bist_factor_backtest.cli init-data
PYTHONPATH=src python3 -m bist_factor_backtest.cli reconstruct-xusin-universe --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli load-prices --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli load-financials-kap --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli build-snapshots --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli run --config config.yaml
PYTHONPATH=src python3 -m bist_factor_backtest.cli export-report --config config.yaml --output reports/backtest_report.xlsx
```

Not:
- `load-financials-kap` bugunku komut adidir
- ileride veri kaynagi degisse bile beklenen davranis bu spesifikasyondaki PIT kurallariyla ayni kalmalidir

## Gelistirme Kurallari

Bir degisiklik kabul edilmeden once su seyleri bozmamalidir:
- PIT secim mantigi
- `announcement_date` / `announcement_datetime` semantigi
- `shares_outstanding` donemselligi
- tarihsel universe uyeligi
- renamed symbols icin tek sirket davranisi

Ozellikle su durumlar test edilmelidir:
- ayni sirket eski ve yeni sembolle farkli donemlerde mevcut
- eski sembol finansali, yeni sembol fiyatiyla ayni sirket olarak esleniyor
- ayni gun ama acilistan sonra aciklanan veri disari atiliyor
- `announcement_datetime` yoksa `announcement_date < first_trading_day` fallback'i calisiyor
- 2019 coverage olmayan yeni halka arzlar backtesti bozmayip sadece eksik coverage olarak raporlaniyor

## Kurulum

```bash
python3 -m pip install -e ".[dev]"
```

CLI komutlarini iki sekilde calistirabilirsin:

```bash
bist-backtest --help
```

veya:

```bash
PYTHONPATH=src python3 -m bist_factor_backtest.cli --help
```

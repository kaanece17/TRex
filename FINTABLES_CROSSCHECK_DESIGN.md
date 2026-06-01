# Fintables Cross-Check Design For TR Refresh Job

## Goal

Ay sonu refresh akisinin resmi veri zincirini bozmadan ikinci bir kontrol katmani eklemek.

Bu katmanin amaci:

- `financial_statements` ve `financial_snapshots` tarafinda eksik ya da gec kalan donemleri bulmak
- announcement date / period coverage uyumsuzluklarini erken yakalamak
- gerekirse operatoru `manual review queue` ile yonlendirmek

Bu katmanin amaci degildir:

- Fintables'i resmi veri kaynagi yapmak
- Fintables verisini dogrudan `financial_statements` uzerine yazmak
- refresh job'u ucuncu taraf sayfa yapisi degisikligi yuzunden kirilgan hale getirmek

## Source Hierarchy

Primary source chain:

1. KAP / issuer IR / MKK / resmi aciklama zinciri
2. mevcut fallback registry ve manuel dogrulanmis override'lar

Secondary audit source:

1. Fintables `Son Bilancolar`
2. Gerekirse sirket bazli Fintables finansal tablo sayfasi

Operasyon karari:

- Fintables sadece `sanity check / mismatch detector` olarak calisir
- primary source tablolari uzerine otomatik write yapmaz

## Refresh Flow Placement

Mevcut `refresh_dashboard` akisi:

1. `load_prices`
2. `load_financials_isyatirim_live`
3. `refresh_isyatirim_load_status`
4. `load_financials_fallback_registry`
5. `load_announcement_dates_investing_live`
6. `load_announcement_dates_issuer_ir_fallback`
7. `load_announcement_dates_mkk_esirket_fallback`
8. `load_announcement_dates_fallback_registry`
9. `build_snapshots`
10. `build_dashboard`

Onerilen ekleme:

1. resmi yukleyiciler bittikten sonra
2. `build_snapshots` oncesinde
3. `run_fintables_crosscheck_audit`

Yani akista yer:

- `load_announcement_dates_fallback_registry`
- `run_fintables_crosscheck_audit`
- `build_snapshots`

Sebep:

- audit, resmi zincirin sonucunu gormeli
- ama snapshot ve dashboard build oncesi uyari uretebilmeli

## Audit Scope

Audit tum tarihceyi taramamalidir. Ay sonu operasyonu icin odak:

1. aktif TR profillerindeki universe sembolleri
2. son 4-6 ceyrek
3. announcement date'i bos olan ya da yeni doneme yakin statement'lar
4. `latest expected filings` listesi

Onerilen hedef set:

- `financial_statements`
- `symbol in active universe`
- `period_end >= current_date - 450 days`

Ek odak:

- `announcement_date is null`
- veya `announcement_date` var ama period/coverage supheli

## Two-Stage Audit Model

### Stage 1: Coverage / Date Audit

Kaynak:

- Fintables `Son Bilancolar`

Kontrol:

- sembol bu donem icin Fintables'ta var mi
- varsa `period_end` eslesiyor mu
- varsa publish/announcement date primary kaynaktaki tarihle uyusuyor mu

Bu stage hafif, hizli ve refresh job icin uygun.

### Stage 2: Headline Value Audit

Kaynak:

- Fintables sirket finansal tablo sayfasi

Sadece Stage 1'de suphe varsa calisir.

Kontrol:

- net income
- operating profit
- equity
- cash
- total debt

Ama sadece operator queue icin kullanilir.

## Comparison Keys

Eslesme anahtari:

- `symbol`
- `period_end`

Fintables tarafinda ceyrek donem parse edilirken normalize hedefi:

- `31.03.2026 -> 2026-03-31`
- `30.06.2026 -> 2026-06-30`
- `30.09.2026 -> 2026-09-30`
- `31.12.2026 -> 2026-12-31`

Bizim statement tarafi ile eslesme:

- `financial_statements.symbol`
- `financial_statements.period_end`

## Severity Levels

### High

- Fintables'ta donem var, primary chain'de yok
- Fintables'ta announcement date var, primary chain'de announcement date yok
- announcement date farki `> 1` gun

### Medium

- announcement date farki `= 1` gun
- headline value farki tolerans ustunde

### Low

- Fintables'ta donem gorunmuyor ama primary chain'de var
- sayfa parse edilemedi / data confidence dusuk

## Suggested Thresholds

Headline alanlari icin:

- `net_income`, `operating_profit`: goreli fark `> 2%`
- `equity`, `cash`, `total_debt`: goreli fark `> 1%`

Rounding / presentation farklari icin:

- sifira yakin degerlerde sadece goreli fark yeterli degil
- bu durumda mutlak fark esigi de olmali

Oneri:

- mutlak fark esigi `1_000_000 TL`

## Output Artifacts

Refresh job icinde gitmeyecek, sadece lokal/runtime artifact:

1. `reports/fintables_crosscheck_summary.csv`
2. `reports/fintables_crosscheck_queue.csv`
3. `reports/fintables_crosscheck_detail.csv`

Queue kolonlari:

- `symbol`
- `period_end`
- `severity`
- `issue_type`
- `primary_announcement_date`
- `fintables_announcement_date`
- `primary_source_url`
- `fintables_source_url`
- `primary_net_income`
- `fintables_net_income`
- `notes`

## Runtime Behavior

Default davranis:

- refresh job devam eder
- audit sadece rapor ve queue uretir

Opsiyonel:

- `--fail-on-high-severity`

Bu flag sadece manuel operasyon veya CI turu icin kullanilmali.
Varsayilan ay sonu cron isinde refresh job'u bloklamamali.

## Manual Review Rule

Queue'ya dusen satirlar icin aksiyon sirası:

1. KAP / issuer IR PDF ile elle dogrula
2. dogrulandiysa
   - `announcement_fallback_registry.csv` veya ilgili fallback kaynagi guncelle
3. snapshot/dashboard tekrar calistir

Kesin kural:

- Fintables goruldu diye registry'ye otomatik yazilmaz

## How To Learn Fintables Update Timing

Fintables'in resmi SLA'i olmadigi icin en dogru yontem gozlem tablosu tutmaktir.

Onerilen audit history tablosu:

- `secondary_audit_observations`

Kolonlar:

- `source` (`fintables`)
- `symbol`
- `period_end`
- `observed_at`
- `announcement_date_seen`
- `headline_hash`
- `source_url`

Bu sayede 2-3 ay sonra su sorulara veriyle cevap verilir:

- Fintables primary source'dan ortalama kac saat/gun sonra update oluyor?
- hangi sembollerde daha gec?
- hangi donemlerde tutarsizlik daha yuksek?

Bu, varsayim yerine olcum uretir.

## Minimal Implementation Plan

Phase 1:

1. `run_fintables_crosscheck_audit` komutu
2. son 450 gun statement coverage + announcement audit
3. CSV queue output
4. refresh job'a non-blocking entegrasyon

Phase 2:

1. headline value compare
2. audit history table
3. latency / reliability dashboard

## Recommendation

Uygulanacak ilk versiyon:

- sadece `coverage + announcement date` audit
- non-blocking
- queue output

Yapilmamasi gereken ilk versiyon:

- otomatik overwrite
- headline alanlari dogrulamadan registry update
- refresh cron'unu ucuncu taraf parse hatasinda fail etmek

## Final Position

Fintables bu problem icin yararli bir ikinci goz olabilir.

Ama dogru rol:

- `secondary audit source`

Yanlis rol:

- `primary ETL source`

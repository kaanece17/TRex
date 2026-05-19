# Month-Start Dashboard Runbook

Bu not, VPS'teki ay basi dashboard refresh job'u icin kisa kontrol listesi ve tipik sorun/aksiyon rehberidir.

## Beklenen Calisma Modeli

- Timer: `trex-dashboard-refresh-first-open.timer`
- Zaman: `07:00 Europe/Istanbul`
- Tetik penceresi: ayin `1-7` gunleri
- Tekrarsiz calisma: ayni ay icinde en fazla `1 kez`
- Kaynak mantigi:
  - yeni ay listesi: son kapanmis islem gunu fiyatlarina gore
  - gecmis performans metrikleri: `open-to-open` backtest mantigiyla

## Beklenen Sonuc

Job basariliysa:

- dashboard `metrics_through_month` onceki kapanmis ayi gostermeli
- `current_month` yeni ayi gostermeli
- `current_display_mode = current` olmali
- yeni ay listesi dolu olmali
- `repeat_count`, `avg_net_return`, `win_rate`, `confidence_level` kolonlari dolu olmali

## Ilk Kontrol Edilecek Yerler

### 1. Health

- URL: `http://89.167.82.38:18443/health`
- beklenen: `{"ok":true}`

### 2. Refresh Status

- dosya: `/opt/trex-dashboard/data/dashboard/refresh_status.json`
- bakilacak alanlar:
  - `status`
  - `message`
  - `current_step`
  - `log_file`
  - `started_at`
  - `finished_at`

Durum yorumlama:

- `success`: job tamamlandi
- `failed`: ilgili adimda hata var
- `skipped`: bu ay icin daha once kosmus ya da koruma mantigi geregi atlanmis
- `running`: halen calisiyor

### 3. Summary

- dosya: `/opt/trex-dashboard/data/dashboard/momentum_watchlist/summary.json`
- bakilacak alanlar:
  - `metrics_through_month`
  - `current_month`
  - `latest_selected_month`
  - `open_month_excluded_from_metrics`
  - `preview_month`
  - `current_display_mode`

Beklenen:

- `metrics_through_month` onceki kapanmis ay
- `current_month` yeni ay
- `preview_month = null`
- `current_display_mode = current`

### 4. Current List

- dosya: `/opt/trex-dashboard/data/dashboard/momentum_watchlist/selected_positions.json`
- yeni ay satirlarinda bak:
  - `symbol`
  - `repeat_count`
  - `avg_net_return`
  - `win_rate`
  - `confidence_level`
  - `financial_base_warning`
  - `used_period_label`
  - `used_announcement_date`

### 5. Uyarilar

- missing financials:
  - `/opt/trex-dashboard/data/dashboard/momentum_watchlist/current_month_alerts.json`
- stale annual base:
  - `/opt/trex-dashboard/data/dashboard/momentum_watchlist/current_month_stale_bases.json`

## Job Akisi

Ay basi job ozette su sirayla ilerler:

1. `refresh-dashboard`
2. `load-prices`
3. `load-financials-isyatirim-live`
4. `refresh-isyatirim-load-status`
5. `load-financials-fallback-registry`
6. `load-announcement-dates-investing-live`
7. `load-announcement-dates-issuer-ir-fallback`
8. `load-announcement-dates-mkk-esirket-fallback`
9. `build-snapshots`
10. `build-dashboard`

## Tipik Sorunlar ve Cozumler

### Problem: Health OK ama dashboard eski ayi gosteriyor

Kontrol:

- `refresh_status.json`
- `summary.json`
- log dosyasi

Muhtemel neden:

- job halen calisiyordur
- export tamamlanmadan dashboard okunmustur
- job fail edip eski artifact kalmistir

Cozum:

- once `refresh_status.json` icinde `success` bekle
- sonra `summary.json` alanlarini tekrar kontrol et
- fail varsa log dosyasina git

### Problem: Getiri aniden dusuk gorunuyor

Kontrol:

- `summary.json` icinde
  - `metrics_through_month`
  - `preview_month`
  - `current_display_mode`

Muhtemel neden:

- kapanmamis ay yanlislikla metriklere dahil edilmistir

Beklenen dogru durum:

- `metrics_through_month` kapanmis ayda kalmali
- `preview_month = null`
- `current_display_mode = current`

### Problem: Current listte `Tekrar / Ort. Getiri / Kazanma` bos

Kontrol:

- `selected_positions.json` icinde
  - `repeat_count`
  - `avg_net_return`
  - `win_rate`
  - `confidence_level`

Muhtemel neden:

- symbol confidence merge'i export tarafinda bozulmustur

Cozum:

- artifact'i yeniden build et
- gerekli ise local export ile VPS artifact karsilastir

### Problem: Financial veri eksik veya stale

Kontrol:

- `current_month_alerts.json`
- `current_month_stale_bases.json`
- dashboard satirlarinda:
  - `financial_base_warning`
  - `used_period_label`
  - `used_announcement_date`

Mevcut B plani:

1. `Iş Yatirim`
2. freshness status
3. fallback registry
   - `financialreports_filing`
   - `issuer_ir_pdf_text`

Cozum:

- eger sembol yeni ve fallback registry'de tanimsizsa:
  - ilgili sembol + period icin registry kaydi ekle

### Problem: Announcement date eksik

Mevcut B plani:

1. `Investing live`
2. `issuer IR fallback`
3. `MKK e-sirket fallback`

Cozum:

- ilgili sembol alert listesinde goruluyorsa log'u kontrol et
- gerekiyorsa issuer IR kaynagini registry/config tarafinda guclendir

### Problem: Job hic kosmamis gibi

Kontrol:

- `systemctl list-timers --all | grep trex-dashboard-refresh`
- `systemctl status trex-dashboard-refresh-first-open.timer`
- `systemctl status trex-dashboard-refresh-first-open.service`

Beklenen:

- timer `enabled`
- service gecmisinde en az bir tetik kaydi

### Problem: Ayni ay icinde tekrar calisiyor

Koruma:

- state dosyasi:
  - `/opt/trex-dashboard/data/dashboard/month_start_refresh_state.json`

Beklenen:

- ayni ay icin `last_completed_month` doluysa tekrar kosmamali

## Hizli Kontrol Komutlari

```bash
curl -fsS http://89.167.82.38:18443/health
```

```bash
ssh root@89.167.82.38 'cat /opt/trex-dashboard/data/dashboard/refresh_status.json'
```

```bash
ssh root@89.167.82.38 'python3 - <<\"PY\"
import json
from pathlib import Path
root = Path(\"/opt/trex-dashboard/data/dashboard/momentum_watchlist\")
summary = json.loads((root / \"summary.json\").read_text())
print(summary[\"metrics_through_month\"], summary[\"current_month\"], summary.get(\"preview_month\"), summary.get(\"current_display_mode\"))
PY'
```

```bash
ssh root@89.167.82.38 'tail -n 120 $(python3 - <<\"PY\"
import json
from pathlib import Path
payload = json.loads(Path(\"/opt/trex-dashboard/data/dashboard/refresh_status.json\").read_text())
print(payload[\"log_file\"])
PY
)'
```

## Not

Bu akista intraday open capture'a bagimli degiliz.

Yani:

- tatil gunu
- hafta sonu
- ayin ilk gunu piyasa acik degilse bile

job son kapanmis veriyi kullanarak guvenli sekilde dashboard'u guncelleyebilir.

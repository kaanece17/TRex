# US No Legacy Hardware + Top3 Report

Candidate:

```text
exclude: NTAP, HPE, HPQ, DELL
top_n: 3
position quality guard: broad semis/storage r60 < -10% cash veto
XLK risk-on: disabled
```

## Full-Period Comparison

| label             | top_n | universe_size | multiple | win_all | win_invested | avg_month | max_dd  | invested | cash |
| ----------------- | ----- | ------------- | -------- | ------- | ------------ | --------- | ------- | -------- | ---- |
| current_full_top5 | 5     | 73            | 10.6053  | 0.6234  | 0.6400       | 0.0353    | -0.3555 | 75       | 2    |
| full_top3         | 3     | 73            | 11.3409  | 0.5974  | 0.6301       | 0.0373    | -0.3493 | 73       | 4    |
| no_legacy_hw_top2 | 2     | 69            | 11.2801  | 0.6104  | 0.6528       | 0.0358    | -0.2122 | 72       | 5    |
| no_legacy_hw_top3 | 3     | 69            | 16.1425  | 0.6104  | 0.6528       | 0.0420    | -0.2837 | 72       | 5    |
| no_legacy_hw_top4 | 4     | 69            | 14.8609  | 0.6234  | 0.6575       | 0.0407    | -0.3116 | 73       | 4    |

## Candidate Period Breakdown

| period    | multiple | win_all | win_invested | avg_month | max_dd  | invested | cash | best_month | worst_month |
| --------- | -------- | ------- | ------------ | --------- | ------- | -------- | ---- | ---------- | ----------- |
| full      | 16.1425  | 0.6104  | 0.6528       | 0.0420    | -0.2837 | 72       | 5    | 2023-05    | 2022-08     |
| 2020-2022 | 1.7808   | 0.5000  | 0.5806       | 0.0195    | -0.2837 | 31       | 5    | 2020-11    | 2022-08     |
| 2023-2026 | 9.0646   | 0.7073  | 0.7073       | 0.0617    | -0.1989 | 41       | 0    | 2023-05    | 2023-08     |
| 2020-2021 | 2.4130   | 0.6250  | 0.6818       | 0.0407    | -0.0902 | 22       | 2    | 2020-11    | 2020-09     |
| 2022      | 0.7380   | 0.2500  | 0.3333       | -0.0229   | -0.2750 | 9        | 3    | 2022-10    | 2022-08     |
| 2023-2024 | 3.7190   | 0.7500  | 0.7500       | 0.0624    | -0.1989 | 24       | 0    | 2023-05    | 2023-08     |
| 2025-2026 | 2.4374   | 0.6471  | 0.6471       | 0.0607    | -0.1209 | 17       | 0    | 2025-09    | 2025-03     |

## Removed Symbol Baseline Contribution

         n   avg_ret       win   contrib  avg_weight
symbol
DELL     1 -0.126605  0.000000 -0.044312    0.350000
HPE      5 -0.021011  0.200000 -0.025591    0.179196
NTAP    13 -0.010510  0.384615  0.000397    0.218700

## Best Monthly Delta vs Baseline

| month   | baseline_return | candidate_return | delta  | baseline_symbols        | candidate_symbols |
| ------- | --------------- | ---------------- | ------ | ----------------------- | ----------------- |
| 2023-05 | 0.2890          | 0.3845           | 0.0955 | MSI,SMCI,NTAP,ROP,AAPL  | SMCI,ROP,MSI      |
| 2025-09 | 0.2649          | 0.3470           | 0.0821 | APP,LRCX,NVDA,MSI,ADBE  | APP,LRCX,NVDA     |
| 2024-11 | 0.3002          | 0.3640           | 0.0638 | TEL,APP,JBL,FTNT,NVDA   | TEL,APP,JBL       |
| 2021-11 | 0.0542          | 0.1088           | 0.0546 | HPE,FSLR,AAPL,AMD,AVGO  | AAPL,FSLR,AMD     |
| 2024-09 | 0.0908          | 0.1420           | 0.0512 | TEL,APP,FTNT,WDAY,NVDA  | TEL,APP,FTNT      |
| 2022-02 | -0.0443         | 0.0000           | 0.0443 | DELL                    |                   |
| 2021-02 | 0.1166          | 0.1566           | 0.0400 | TEL,AMAT,MU,MSFT,KLAC   | TEL,AMAT,MU       |
| 2020-11 | 0.2838          | 0.3213           | 0.0375 | LRCX,KLAC,AMAT,MCHP,TXN | LRCX,KLAC,AMAT    |

## Worst Monthly Delta vs Baseline

| month   | baseline_return | candidate_return | delta   | baseline_symbols       | candidate_symbols |
| ------- | --------------- | ---------------- | ------- | ---------------------- | ----------------- |
| 2026-01 | 0.0223          | -0.0266          | -0.0489 | APP,GLW,MSI,NVDA,MU    | APP,GLW,MSI       |
| 2022-08 | -0.1053         | -0.1457          | -0.0404 | STX,MCHP,FTNT,ON       | STX,MCHP,FTNT     |
| 2020-05 | 0.0887          | 0.0540           | -0.0347 | AMD,AAPL,CDW,KEYS,ROP  | AMD,AAPL,CDW      |
| 2021-12 | 0.0268          | -0.0076          | -0.0344 | AAPL,QCOM,AMD,CDW,AVGO | AAPL,QCOM,AMD     |
| 2026-04 | 0.3737          | 0.3399           | -0.0338 | FTNT,STX,CIEN,AMD,JBL  | FTNT,STX,CIEN     |
| 2025-05 | 0.0484          | 0.0186           | -0.0298 | NTAP,FTNT,IT,KLAC,APH  | FTNT,IT,KLAC      |
| 2023-08 | -0.1029         | -0.1287          | -0.0258 | FTNT,NTAP,SMCI,AVGO,ON | FTNT,SMCI,AVGO    |
| 2025-06 | 0.1050          | 0.0796           | -0.0254 | KLAC,NTAP,APP,LRCX,MU  | KLAC,APP,LRCX     |

## Readout

- Baseline full top5: `10.61x`, win invested `64.00%`, max DD `-35.55%`.
- Candidate no legacy hardware top3: `16.14x`, win invested `65.28%`, max DD `-28.37%`.
- The candidate clears the drawdown target but does not clear the 70% full-period invested win-rate target.
- Period behavior is asymmetric: 2023-2026 is above 70% win rate; 2020-2022, especially 2022, remains the blocker.
- Compared with no-storage, this is cleaner: it removes legacy hardware only and keeps storage/core semis when they are useful.

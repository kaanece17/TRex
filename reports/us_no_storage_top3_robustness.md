# No Storage + Top3 Robustness

Candidate: exclude `STX,WDC,SNDK,NTAP,HPE,HPQ,DELL`, use `top_n=3`, keep existing `r60<-10%` position quality guard.

## Candidate Period Breakdown

| period    | multiple | win_all | win_invested | avg_month | max_dd  | invested | cash |
| --------- | -------- | ------- | ------------ | --------- | ------- | -------- | ---- |
| full      | 17.2527  | 0.5974  | 0.6389       | 0.0430    | -0.3108 | 72       | 5    |
| 2020-2022 | 1.7542   | 0.4722  | 0.5484       | 0.0191    | -0.3108 | 31       | 5    |
| 2023-2026 | 9.8351   | 0.7073  | 0.7073       | 0.0640    | -0.1989 | 41       | 0    |
| 2020-2021 | 2.4704   | 0.5833  | 0.6364       | 0.0416    | -0.0902 | 22       | 2    |
| 2022      | 0.7101   | 0.2500  | 0.3333       | -0.0259   | -0.2826 | 9        | 3    |
| 2023-2024 | 3.7256   | 0.7500  | 0.7500       | 0.0625    | -0.1989 | 24       | 0    |
| 2025-2026 | 2.6399   | 0.6471  | 0.6471       | 0.0661    | -0.1213 | 17       | 0    |

## Full-Period Grid

| label                   | top_n | universe_size | multiple | win_invested | max_dd  | invested | cash | meets_dd30 | meets_win70 |
| ----------------------- | ----- | ------------- | -------- | ------------ | ------- | -------- | ---- | ---------- | ----------- |
| no_storage              | 2     | 66            | 12.6159  | 0.6528       | -0.2081 | 72       | 5    | True       | False       |
| no_storage_minus_dell   | 2     | 67            | 12.0569  | 0.6438       | -0.2081 | 73       | 4    | True       | False       |
| no_legacy_hw            | 2     | 69            | 11.2801  | 0.6528       | -0.2122 | 72       | 5    | True       | False       |
| no_storage_minus_ntap   | 2     | 67            | 9.2945   | 0.6528       | -0.2355 | 72       | 5    | True       | False       |
| no_storage_plus_on_nxpi | 2     | 64            | 11.9727  | 0.6389       | -0.2432 | 72       | 5    | True       | False       |
| full                    | 2     | 73            | 10.0783  | 0.6438       | -0.2807 | 73       | 4    | True       | False       |
| no_legacy_hw            | 3     | 69            | 16.1425  | 0.6528       | -0.2837 | 72       | 5    | True       | False       |
| no_storage              | 3     | 66            | 17.2527  | 0.6389       | -0.3108 | 72       | 5    | False      | False       |
| no_legacy_hw            | 5     | 69            | 13.3549  | 0.6486       | -0.3113 | 74       | 3    | False      | False       |
| no_legacy_hw            | 4     | 69            | 14.8609  | 0.6575       | -0.3116 | 73       | 4    | False      | False       |
| no_storage_minus_ntap   | 3     | 67            | 14.9422  | 0.6250       | -0.3157 | 72       | 5    | False      | False       |
| no_storage_plus_on_nxpi | 4     | 64            | 14.4402  | 0.6351       | -0.3326 | 74       | 3    | False      | False       |
| no_storage_plus_on_nxpi | 3     | 64            | 16.1862  | 0.6438       | -0.3350 | 73       | 4    | False      | False       |
| no_storage              | 4     | 66            | 13.2733  | 0.6486       | -0.3411 | 74       | 3    | False      | False       |
| no_storage_minus_dell   | 3     | 67            | 16.4785  | 0.6301       | -0.3413 | 73       | 4    | False      | False       |
| full                    | 4     | 73            | 11.9044  | 0.6533       | -0.3422 | 75       | 2    | False      | False       |
| no_storage_minus_ntap   | 4     | 67            | 11.6503  | 0.6486       | -0.3438 | 74       | 3    | False      | False       |
| no_storage              | 5     | 66            | 12.1965  | 0.6486       | -0.3463 | 74       | 3    | False      | False       |
| no_storage_minus_ntap   | 5     | 67            | 10.6855  | 0.6486       | -0.3469 | 74       | 3    | False      | False       |
| full                    | 3     | 73            | 11.3409  | 0.6301       | -0.3493 | 73       | 4    | False      | False       |
| full                    | 5     | 73            | 10.6053  | 0.6400       | -0.3555 | 75       | 2    | False      | False       |
| no_storage_core         | 3     | 70            | 12.9281  | 0.6216       | -0.3625 | 74       | 3    | False      | False       |
| no_storage_core         | 4     | 70            | 10.9317  | 0.6400       | -0.3657 | 75       | 2    | False      | False       |
| no_storage_plus_on_nxpi | 5     | 64            | 11.9983  | 0.6486       | -0.3677 | 74       | 3    | False      | False       |
| no_storage_minus_dell   | 4     | 67            | 13.2126  | 0.6400       | -0.3704 | 75       | 2    | False      | False       |
| no_storage_core         | 5     | 70            | 9.9163   | 0.6400       | -0.3706 | 75       | 2    | False      | False       |
| no_storage_core         | 2     | 70            | 9.1596   | 0.6216       | -0.3733 | 74       | 3    | False      | False       |
| no_storage_minus_dell   | 5     | 67            | 11.7838  | 0.6400       | -0.3753 | 75       | 2    | False      | False       |

## Excluded Symbols In Baseline

         n   avg_ret       win   contrib
symbol                                  
DELL     1 -0.126605  0.000000 -0.044312
HPE      5 -0.021011  0.200000 -0.025591
WDC      2 -0.062219  0.500000 -0.020514
NTAP    13 -0.010510  0.384615  0.000397
STX      7  0.050312  0.285714  0.049117

## Readout

- `no_storage + top3` improves multiple strongly and brings max drawdown close to the 30% target, but does not improve win rate to 70%.
- Category-level robustness is mixed: removing only storage core or only legacy hardware is weaker than the combined list.
- The win-rate target likely needs a separate month-level risk gate rather than only universe reduction.

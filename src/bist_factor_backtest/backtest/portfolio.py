from __future__ import annotations

import pandas as pd


def build_equal_weight_positions(selected: pd.DataFrame) -> pd.DataFrame:
    result = selected.copy()
    if result.empty:
        result["weight"] = pd.Series(dtype=float)
        return result
    result["weight"] = 1.0 / len(result)
    return result


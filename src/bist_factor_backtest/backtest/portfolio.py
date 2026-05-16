from __future__ import annotations

import pandas as pd


def build_positions(
    selected: pd.DataFrame,
    weighting: str = "equal_weight",
    score_weight_cap: float | None = None,
) -> pd.DataFrame:
    result = selected.copy()
    if result.empty:
        result["weight"] = pd.Series(dtype=float)
        return result

    if weighting == "equal_weight":
        result["weight"] = 1.0 / len(result)
        return result

    if weighting == "score_weight_capped":
        return _build_score_weight_capped_positions(result, score_weight_cap)

    raise ValueError(f"Unsupported weighting mode: {weighting}")


def _build_score_weight_capped_positions(selected: pd.DataFrame, score_weight_cap: float | None) -> pd.DataFrame:
    result = selected.copy()
    scores = pd.to_numeric(result["score"], errors="coerce").fillna(0.0)
    positive_scores = scores.clip(lower=0.0)
    if positive_scores.sum() <= 0:
        result["weight"] = 1.0 / len(result)
        return result

    weights = positive_scores / positive_scores.sum()
    if score_weight_cap is None or score_weight_cap <= 0 or score_weight_cap >= 1:
        result["weight"] = weights
        return result

    remaining_mask = pd.Series(True, index=result.index)
    final_weights = pd.Series(0.0, index=result.index)
    remaining_total = 1.0

    while remaining_mask.any():
        active_scores = positive_scores[remaining_mask]
        if active_scores.sum() <= 0:
            equal_share = remaining_total / remaining_mask.sum()
            final_weights.loc[remaining_mask] = equal_share
            break

        proposed = active_scores / active_scores.sum() * remaining_total
        capped = proposed >= score_weight_cap
        if not capped.any():
            final_weights.loc[remaining_mask] = proposed
            break

        capped_index = proposed[capped].index
        final_weights.loc[capped_index] = score_weight_cap
        remaining_total -= score_weight_cap * len(capped_index)
        remaining_mask.loc[capped_index] = False

        if remaining_total <= 0:
            break

    result["weight"] = final_weights
    return result

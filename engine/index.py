"""Gaps, flags, and the Overheating Index - CALCULATIONS.md Steps 6-8."""
from __future__ import annotations

import pandas as pd

from .config import MethodConfig


def gap(cycle: pd.Series) -> pd.Series:
    """Step 6: cyclical component -> ~percent deviation from trend."""
    return 100.0 * cycle


def flags(gap_df: pd.DataFrame, method: MethodConfig) -> pd.DataFrame:
    """Step 7: 1 where the one-sided gap breaches its method threshold, else 0.

    ``gap_df`` has one column per index component (named by component). Quarters where a
    gap is missing stay NaN (not 0), so the index is undefined there rather than falsely 0.
    """
    out: dict[str, pd.Series] = {}
    for name in method.index_components:
        g = gap_df[name]
        out[name] = (g > method.thresholds[name]).astype("float").mask(g.isna())
    return pd.DataFrame(out)


def overheating_index(flag_df: pd.DataFrame, method: MethodConfig) -> pd.Series:
    """Step 8: weighted sum of the one-sided flags (eq 8).

    Defined only where every index component has a flag (ragged-edge decision 2): a NaN in
    any component propagates to NaN in the sum, so no quarter is scored on partial data.
    """
    names = list(method.index_components)
    oi = sum(method.weights[n] * flag_df[n] for n in names)
    return oi.where(flag_df[names].notna().all(axis=1))

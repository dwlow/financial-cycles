"""Data preparation - CALCULATIONS.md Steps 1-3.

Read the pinned raw CSVs, align CPI to quarterly (Step 1), deflate nominal series to
real (Step 2), and take natural logs (Step 3).

Each series is kept over its own maximal sample (engine design decision 3): the returned
frame is the union of all quarterly indices, with NaN outside each series' own span -
downstream filtering drops per column, so no series is clipped to another's start.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import CountryConfig, SeriesSpec, RAW


def _read(spec: SeriesSpec) -> pd.Series:
    """Load positive observations as a date-indexed float Series.

    Every configured input is log-transformed downstream, so nonpositive source
    values (for example, zero placeholders in early equity-index history) are invalid.
    """
    df = pd.read_csv(RAW / spec.file, na_values=[".", ""])
    dates = pd.to_datetime(df["observation_date"])
    vals = pd.to_numeric(df[spec.column], errors="coerce")
    series = pd.Series(vals.to_numpy(), index=dates).dropna()
    return series[series > 0]


def _to_quarterly(s: pd.Series, freq: str) -> pd.Series:
    """Quarterly PeriodIndex. Monthly CPI -> mean of the quarter's 3 months (Step 1)."""
    q = pd.PeriodIndex(s.index, freq="Q")
    if freq == "M":
        return s.groupby(q).mean()
    return pd.Series(s.to_numpy(), index=q)


def prepare(country: CountryConfig) -> pd.DataFrame:
    """Real levels + log-levels for every configured series, quarterly.

    Columns: ``<name>`` (real level) and ``log_<name>`` for each series. The ``log_``
    columns are the e / g / cr / pr inputs to the CF filter (Step 4).
    """
    cpi_q = _to_quarterly(_read(country.cpi), country.cpi.freq)  # Step 1

    real: dict[str, pd.Series] = {}
    for name, spec in country.series.items():
        q = _to_quarterly(_read(spec), spec.freq)
        real[name] = q / cpi_q if spec.deflate else q            # Step 2 (aligns on quarter)
    real_df = pd.DataFrame(real).sort_index()

    log_df = np.log(real_df).add_prefix("log_")                  # Step 3
    out = real_df.join(log_df)
    out.attrs["country"] = country.name
    return out

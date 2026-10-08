"""Run the AM Overheating Index or an exploratory emerging-market index.

Wires the pipeline: config -> data prep (Steps 1-3) -> CF filter (Steps 4-5) ->
gaps (Step 6) -> scoring (Steps 7-8). Advanced markets use the paper's calibrated AM
method; emerging markets use a separate exploratory method.

    python -m engine.run          # run Canada with the AM method

``run()`` returns a tidy quarterly results frame; ``main()`` prints the latest reading.
"""
from __future__ import annotations

import pandas as pd

from . import filters, index
from .config import AM_METHOD, CANADA, EM_METHOD, CountryConfig, MethodConfig
from .data import prepare


def _gaps(country: CountryConfig, method: MethodConfig) -> pd.DataFrame:
    data = prepare(country)  # Steps 1-3
    # Steps 4-6: two-sided and one-sided percent gaps for every series. Only process
    # components this country actually supplies (a country may omit dashboard series, or
    # have a series dropped for lack of coverage); the index components are still required.
    all_components = list(method.index_components) + list(method.dashboard_components)
    components = [c for c in all_components if f"log_{c}" in data.columns]
    missing_core = [c for c in method.index_components if c not in components]
    if missing_core:
        raise ValueError(f"{country.name}: missing required index series {missing_core}")
    result: dict[str, pd.Series] = {}
    for name in components:
        series = data[f"log_{name}"].dropna()
        band = method.bands[name]
        c1 = filters.one_sided(series, band, method.cf_drift)
        # Display-only trim: the one-sided read is blind until the window covers the band's
        # longest cycle (p_u = band.high), so blank those early quarters to keep artifacts
        # from flagging. This lives in the presentation layer, not the filter (decision:
        # one-sided no-warmup - the trim is our display choice, not part of the method).
        c1.iloc[: band.high] = float("nan")
        result[f"gap_2s_{name}"] = index.gap(filters.two_sided(series, band, method.cf_drift))
        result[f"gap_1s_{name}"] = index.gap(c1)
    return pd.DataFrame(result).sort_index()


def _score(res: pd.DataFrame, method: MethodConfig) -> pd.DataFrame:
    """Add flags and the weighted index where all required gaps are available."""
    gap_1s = res[[f"gap_1s_{n}" for n in method.index_components]].copy()
    gap_1s.columns = list(method.index_components)
    flag_df = index.flags(gap_1s, method)
    for name in method.index_components:
        res[f"flag_{name}"] = flag_df[name]
    res["OI"] = index.overheating_index(flag_df, method)
    return res


def run_monitor(country: CountryConfig, method: MethodConfig = EM_METHOD) -> pd.DataFrame:
    """Return emerging-market gaps and the exploratory credit/equity/property index."""
    if country.market_group != "emerging":
        raise ValueError(f"{country.name}: run_monitor is only for emerging-market configs")
    res = _score(_gaps(country, method), method)
    res.attrs["country"] = country.name
    res.attrs["market_group"] = country.market_group
    return res


def run(country: CountryConfig = CANADA, method: MethodConfig = AM_METHOD) -> pd.DataFrame:
    if country.market_group != "advanced":
        raise ValueError(f"{country.name}: emerging markets must use run_monitor, not AM scoring")
    res = _score(_gaps(country, method), method)
    res.attrs["country"] = country.name
    res.attrs["market_group"] = country.market_group
    return res


def main() -> int:
    res = run()
    scored = res.dropna(subset=["OI"])
    print(f"AM Overheating Index - {res.attrs['country']}")
    print(f"quarters computed: {res.index[0]} .. {res.index[-1]}  (n={len(res)})")
    print(f"quarters with OI:  {scored.index[0]} .. {scored.index[-1]}  (n={len(scored)})")
    print("\nlatest scored quarter:")
    print(scored.iloc[-1].to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fetch & cache the raw series for the financial-cycle tracker.

Multi-country. Each country's series are pulled from a provider and normalized to a
CSV in data/raw/, and recorded in a manifest that pins the data vintage. The engine
reads those cached CSVs, so the one-sided real-time filter is reproducible against a fixed
vintage; re-fetch quarterly using --refresh.

Providers:
    fred     FRED API series/observations (api.stlouisfed.org), needs api key -> observation_date,<id>
    statcan  StatCan Web Data Service (WDS), by vector id             -> observation_date,value
    boc      Bank of Canada Valet API, by series code                 -> observation_date,value
    abs      ABS Data API (SDMX), by dataflow/key                     -> observation_date,value
    imf_ifs  IMF IFS via DBnomics                                     -> observation_date,value

Usage:
    python fetch_data.py                       # fetch series not already cached (all countries)
    python fetch_data.py --emerging            # fetch emerging-market series only
    python fetch_data.py --refresh             # re-fetch everything (quarterly update)
    python fetch_data.py --country Australia   # limit to one country (with/without --refresh)
    python fetch_data.py --list                # list configured series, don't fetch
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.config import (
    EM_FRED_SERIES, EM_MARKET_CODES, EM_NON_FRED_SERIES, EM_SOURCE_SERIES,
)

RAW = Path(__file__).resolve().parent / "data" / "raw"
MANIFEST = RAW / "manifest.json"
TIMEOUT = 40
PACE = 1.5           # seconds between live fetches — polite; avoids self-throttling on FRED
UA = "am-overheating/1.0"

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
STATCAN_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
BOC_URL = "https://www.bankofcanada.ca/valet/observations/{rid}/json"
ABS_URL = "https://data.api.abs.gov.au/rest/data/{rid}?detail=dataonly"  # version-less key -> latest dataflow
# Eurostat, no API key required — one source covers the whole EU/EEA bloc. rid = geo code.
#   eu_hicp: HICP all-items monthly index (prc_hicp_midx, unit I15 = 2015=100)  -> CPI deflator
#   eu_gdp:  real GDP, chain-linked volumes, SA/CA, quarterly (namq_10_gdp)     -> output series
EU_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
EU_HICP_URL = EU_BASE + "prc_hicp_midx?format=JSON&freq=M&unit=I15&coicop=CP00&geo={rid}"
EU_GDP_URL = EU_BASE + "namq_10_gdp?format=JSON&freq=Q&unit=CLV_I15&s_adj=SCA&na_item=B1GQ&geo={rid}"
# ONS (UK), open, no key. rid = the timeseries path; JSON is served by appending /data.
ONS_URL = "https://www.ons.gov.uk/{rid}/data"
# IMF IFS via DBnomics (open, no key). rid = DBnomics series code, e.g. 'M.JP.PCPI_IX'
# (monthly, ref-area, Consumer Price Index all-items). One uniform CPI source across countries;
# lags ~1 year (IMF release cadence). Reusable for non-EU markets without a national CPI API.
DBNOMICS_IFS_URL = "https://api.db.nomics.world/v22/series/IMF/IFS/{rid}?observations=1"


@dataclass(frozen=True)
class Src:
    """One raw series: where it lands, which provider serves it, its remote id, a blurb."""
    file: str        # output filename in data/raw
    provider: str    # one of FETCHERS' provider keys
    rid: str         # remote id / key ('CPI/1.10001.10.50.Q' for abs; str vector id for statcan)
    desc: str


# Per-country series registry. Canada keeps its legacy filenames so the existing cache and
# the published page stay valid; new countries use the '{ISO}__{label}.csv' convention.
COUNTRIES: dict[str, list[Src]] = {
    "Canada": [
        Src("real_gdp__NGDPRSAXDCCAQ.csv",                "fred",    "NGDPRSAXDCCAQ",     "Real GDP, Canada, SA, quarterly (index)"),
        Src("share_prices_nominal__SPASTT01CAQ661N.csv",  "fred",    "SPASTT01CAQ661N",   "Share prices, Canada, quarterly index (nominal)"),
        Src("cpi_quarterly__CANCPIALLQINMEI.csv",         "fred",    "CANCPIALLQINMEI",   "CPI all items, Canada, quarterly index"),
        Src("cpi_monthly__CANCPIALLMINMEI.csv",           "fred",    "CANCPIALLMINMEI",   "CPI all items, Canada, monthly index"),
        Src("total_credit_level__CRDQCAAPABIS.csv",       "fred",    "CRDQCAAPABIS",      "Total credit to private non-financial sector, Canada (level, break-adj.)"),
        Src("total_credit_pct_gdp__QCAPAM770A.csv",       "fred",    "QCAPAM770A",        "Total credit to private non-financial sector, % of GDP"),
        Src("bank_credit_pct_gdp__QCAPBM770A.csv",        "fred",    "QCAPBM770A",        "Bank credit to private non-financial sector, % of GDP"),
        Src("credit_to_gdp__QCACAM770A.csv",              "fred",    "QCACAM770A",        "Credit-to-GDP (BIS), Canada"),
        Src("real_residential_property__QCAR628BIS.csv",  "fred",    "QCAR628BIS",        "Real residential property prices, Canada, index"),
        Src("cpi_statcan__v41690973.csv",                 "statcan", "41690973",          "CPI all items, Canada, monthly, NSA, 2002=100 (StatCan v41690973)"),
        Src("boc_output_gap_mpr__INDINF_OUTGAPMPR_Q.csv", "boc",     "INDINF_OUTGAPMPR_Q","BoC output gap, Current MPR (%)"),
        Src("boc_output_gap_if__INDINF_OUTGAPI_Q.csv",    "boc",     "INDINF_OUTGAPI_Q",  "BoC output gap, Integrated Framework (%)"),
        Src("boc_output_gap_emvf__INDINF_OUTGAPM_Q.csv",  "boc",     "INDINF_OUTGAPM_Q",  "BoC output gap, Extended Multivariate Filter (%)"),
    ],
    "Australia": [
        Src("AU__real_gdp.csv",             "fred", "NGDPRSAXDCAUQ",         "Real GDP, Australia, SA, quarterly (index)"),
        Src("AU__share_prices_nominal.csv", "fred", "SPASTT01AUQ661N",       "Share prices, Australia, quarterly index (nominal)"),
        Src("AU__cpi.csv",                  "abs",  "CPI/1.10001.10.50.Q",   "All groups CPI, Australia, Index Numbers, Original, 8-capital wtd avg, Q (ABS)"),
    ],
    "United States": [
        Src("US__real_gdp.csv",             "fred", "NGDPRSAXDCUSQ",   "Real GDP, US, SA, quarterly (index)"),
        Src("US__share_prices_nominal.csv", "fred", "SPASTT01USQ661N", "Share prices, US, quarterly index (nominal)"),
        Src("US__cpi.csv",                  "fred", "CPIAUCSL",        "CPI-U all items, US, monthly, SA (BLS via FRED) — current, used as deflator"),
    ],
    "United Kingdom": [
        Src("GB__real_gdp.csv",             "fred", "NGDPRSAXDCGBQ",   "Real GDP, UK, SA, quarterly (index)"),
        Src("GB__share_prices_nominal.csv", "fred", "SPASTT01GBQ661N", "Share prices, UK, quarterly index (nominal)"),
        Src("GB__cpi.csv",                  "ons",  "economy/inflationandpriceindices/timeseries/d7bt/mm23",
            "CPI all-items index, UK, monthly (ONS D7BT / MM23) — current"),
    ],
    "Japan": [
        Src("JP__real_gdp.csv",             "fred",    "NGDPRSAXDCJPQ",   "Real GDP, Japan, SA, quarterly (index)"),
        Src("JP__share_prices_nominal.csv", "fred",    "SPASTT01JPQ661N", "Share prices, Japan, quarterly index (nominal)"),
        Src("JP__cpi.csv",                  "imf_ifs", "M.JP.PCPI_IX",    "CPI all-items index, Japan, monthly (IMF IFS via DBnomics) — lags ~1yr"),
    ],
    "Switzerland": [  # no FRED GDP series -> Eurostat (EFTA); CPI via IMF IFS
        Src("CH__real_gdp.csv",             "eu_gdp",  "CH",              "Real GDP (chain-linked vol., SA), Switzerland, quarterly (Eurostat)"),
        Src("CH__share_prices_nominal.csv", "fred",    "SPASTT01CHQ661N", "Share prices, Switzerland, quarterly index (nominal)"),
        Src("CH__cpi.csv",                  "imf_ifs", "M.CH.PCPI_IX",    "CPI all-items index, Switzerland, monthly (IMF IFS via DBnomics) — lags ~1yr"),
    ],
    "Korea": [
        Src("KR__real_gdp.csv",             "fred",    "NGDPRSAXDCKRQ",   "Real GDP, Korea, SA, quarterly (index)"),
        Src("KR__share_prices_nominal.csv", "fred",    "SPASTT01KRQ661N", "Share prices, Korea, quarterly index (nominal)"),
        Src("KR__cpi.csv",                  "imf_ifs", "M.KR.PCPI_IX",    "CPI all-items index, Korea, monthly (IMF IFS via DBnomics) — lags ~1yr"),
    ],
    "Israel": [  # no FRED GDP -> IMF IFS real GDP (quarterly)
        Src("IL__real_gdp.csv",             "imf_ifs", "Q.IL.NGDP_R_SA_XDC", "Real GDP SA, Israel, quarterly (IMF IFS via DBnomics)"),
        Src("IL__share_prices_nominal.csv", "fred",    "SPASTT01ILQ661N",    "Share prices, Israel, quarterly index (nominal)"),
        Src("IL__cpi.csv",                  "imf_ifs", "M.IL.PCPI_IX",       "CPI all-items index, Israel, monthly (IMF IFS via DBnomics) — lags ~1yr"),
    ],
    "New Zealand": [  # no FRED GDP, no monthly IMF CPI -> IMF IFS quarterly GDP + quarterly CPI
        Src("NZ__real_gdp.csv",             "imf_ifs", "Q.NZ.NGDP_R_SA_XDC", "Real GDP SA, New Zealand, quarterly (IMF IFS via DBnomics)"),
        Src("NZ__share_prices_nominal.csv", "fred",    "SPASTT01NZQ661N",    "Share prices, New Zealand, quarterly index (nominal)"),
        Src("NZ__cpi.csv",                  "imf_ifs", "Q.NZ.PCPI_IX",       "CPI all-items index, New Zealand, quarterly (IMF IFS via DBnomics) — lags ~1yr"),
    ],
    "Hong Kong": [  # no FRED/OECD coverage at all -> everything from IMF IFS. Equity is the
        # IFS share-price index (FPE_IX), a documented proxy for OECD SPASTT01 (both broad
        # national share-price indices); quarterly variant matches the period-average convention.
        # Equity history starts 1996 — shortest in the set.
        Src("HK__real_gdp.csv",             "imf_ifs", "Q.HK.NGDP_R_SA_XDC", "Real GDP SA, Hong Kong, quarterly (IMF IFS via DBnomics)"),
        Src("HK__share_prices_nominal.csv", "imf_ifs", "Q.HK.FPE_IX",        "Share prices, Hong Kong, quarterly index (nominal, IMF IFS FPE_IX — SPASTT01 proxy)"),
        Src("HK__cpi.csv",                  "imf_ifs", "M.HK.PCPI_IX",       "CPI all-items index, Hong Kong, monthly (IMF IFS via DBnomics) — lags ~1yr"),
    ],
}

# EU/EEA advanced-market bloc (paper's AM list only): equity from FRED, GDP + CPI from Eurostat
# (one open API, covers every member). (display name, FRED iso2, Eurostat geo). Greece's
# Eurostat geo is 'EL', not 'GR'. Cyprus & Malta are excluded — no FRED share-price series.
EU_AM = [
    ("Austria", "AT", "AT"), ("Belgium", "BE", "BE"), ("Czech Republic", "CZ", "CZ"),
    ("Denmark", "DK", "DK"), ("Estonia", "EE", "EE"), ("Finland", "FI", "FI"),
    ("France", "FR", "FR"), ("Germany", "DE", "DE"), ("Greece", "GR", "EL"),
    ("Ireland", "IE", "IE"), ("Italy", "IT", "IT"), ("Luxembourg", "LU", "LU"),
    ("Netherlands", "NL", "NL"), ("Portugal", "PT", "PT"), ("Slovak Republic", "SK", "SK"),
    ("Slovenia", "SI", "SI"), ("Spain", "ES", "ES"), ("Sweden", "SE", "SE"),
    ("Iceland", "IS", "IS"), ("Norway", "NO", "NO"),
]
for _name, _iso, _geo in EU_AM:
    COUNTRIES[_name] = [
        Src(f"{_iso}__real_gdp.csv",             "eu_gdp",  _geo,                 f"Real GDP (chain-linked vol., SA), {_name}, quarterly (Eurostat)"),
        Src(f"{_iso}__share_prices_nominal.csv", "fred",    f"SPASTT01{_iso}Q661N", f"Share prices, {_name}, quarterly index (nominal, FRED)"),
        Src(f"{_iso}__cpi.csv",                  "eu_hicp", _geo,                 f"HICP all-items, {_name}, monthly index (Eurostat)"),
    ]

# Emerging-market CPI uses the already-verified IMF IFS series; credit, equity, and
# property inputs use only country-specific FRED IDs confirmed to return observations.
_EM_FRED_FILES = {
    "credit": ("{iso}__fred_credit.csv",
               "BIS break-adjusted total credit to private non-financial sector, {name}"),
    "equity": ("{iso}__fred_equity.csv",
               "OECD quarterly share-price index, {name}"),
    "property": ("{iso}__fred_property.csv",
                 "BIS real residential property price index, {name}"),
}
_EM_CPI_SOURCE = ("M.{iso}.PCPI_IX", "{iso}__cpi.csv",
                  "CPI all-items, {name}, monthly (IMF IFS via DBnomics)")
for _name, _iso in EM_MARKET_CODES:
    COUNTRIES[_name] = []
    if "cpi" in EM_SOURCE_SERIES[_name]:
        _rid, _file, _desc = _EM_CPI_SOURCE
        COUNTRIES[_name].append(
            Src(_file.format(iso=_iso), "imf_ifs", _rid.format(iso=_iso),
                _desc.format(name=_name))
        )
    for _component, _rid in EM_FRED_SERIES.get(_name, {}).items():
        _file, _desc = _EM_FRED_FILES[_component]
        COUNTRIES[_name].append(
            Src(_file.format(iso=_iso), "fred_graph", _rid, _desc.format(name=_name))
        )
    if _name in EM_NON_FRED_SERIES and "equity" in EM_NON_FRED_SERIES[_name]:
        COUNTRIES[_name].append(
            Src(
                EM_NON_FRED_SERIES[_name]["equity"].file,
                "imf_ifs",
                f"Q.{_iso}.FPE_IX",
                f"Share prices, {_name}, quarterly (IMF IFS FPE_IX index)",
            )
        )


def _curl(extra: list[str], what: str) -> str:
    """Run curl with shared flags; return stdout or raise. No --fail, so HTTP-error bodies
    (e.g. a FRED API 400/429 JSON error) come back for the caller to parse and report.

    curl rather than urllib: this environment permits curl's egress but blocks Python's own
    sockets. --http1.1 because these hosts misbehave over HTTP/2 here — dropping it shows up
    as slow stalls and exit-28 timeouts, indistinguishable from FRED throttling.
    """
    cmd = ["curl", "-s", "--http1.1", "--retry", "2", "--retry-delay", "2",
           "-m", str(TIMEOUT), "-A", UA, *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:  # transport failure (timeout, DNS, connection) — no HTTP body
        raise RuntimeError(f"curl failed (exit {proc.returncode}) for {what}")
    return proc.stdout


def _fred_key() -> str:
    """FRED API key from (in order) FRED_API_KEY env var, project .env / .fred_api_key,
    or ~/.fred_api_key. Raises if none found."""
    k = os.environ.get("FRED_API_KEY")
    if k:
        return k.strip()
    root = Path(__file__).resolve().parent
    env = root / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    for f in (root / ".fred_api_key", Path.home() / ".fred_api_key"):
        if f.exists():
            return f.read_text().strip()
    raise RuntimeError("no FRED API key: set FRED_API_KEY, or add .env / .fred_api_key "
                       "(free key: https://fred.stlouisfed.org/docs/api/api_key.html)")


def fetch_fred(rid: str) -> str:
    """FRED series/observations API (JSON) -> observation_date,<id> CSV (fredgraph format,
    so engine configs keying on the series id still read it unchanged)."""
    url = f"{FRED_API_URL}?series_id={rid}&api_key={_fred_key()}&file_type=json"
    out = _curl([url], f"FRED {rid}")
    data = json.loads(out)
    if "observations" not in data:
        raise ValueError(f"FRED API error for {rid}: {data.get('error_message', out[:150])}")
    lines = [f"observation_date,{rid}"]
    lines += [f"{o['date']},{o['value']}" for o in data["observations"]]
    return "\n".join(lines) + "\n"


def fetch_fred_graph(rid: str) -> str:
    """Fetch a FRED public graph CSV, which does not require an API key."""
    url = f"{FRED_GRAPH_URL}?id={rid}"
    try:
        out = _curl(["-f", url], f"FRED graph {rid}")
    except RuntimeError as graph_error:
        try:
            _fred_key()
        except RuntimeError:
            raise RuntimeError(
                f"FRED public CSV request failed for {rid}; configure FRED_API_KEY "
                "to retry through the FRED observations API"
            ) from graph_error
        return fetch_fred(rid)
    rows = list(csv.reader(io.StringIO(out)))
    if not rows or rows[0] != ["observation_date", rid]:
        raise ValueError(f"FRED graph returned an unexpected CSV header for {rid}")
    if not any(len(row) > 1 and row[1] not in ("", ".") for row in rows[1:]):
        raise ValueError(f"FRED graph returned no observations for {rid}")
    return out


def fetch_statcan(rid: str) -> str:
    """StatCan WDS vector -> observation_date,value CSV."""
    body = json.dumps([{"vectorId": int(rid), "latestN": 1400}])
    out = _curl(["-X", "POST", "-H", "Content-Type: application/json", "-d", body, STATCAN_URL],
                f"StatCan v{rid}")
    data = json.loads(out)
    if not data or data[0].get("status") != "SUCCESS":
        raise ValueError(f"StatCan returned non-SUCCESS for v{rid}")
    lines = ["observation_date,value"]
    for p in data[0]["object"]["vectorDataPoint"]:
        if p.get("value") is not None:
            lines.append(f"{p['refPer']},{p['value']}")
    return "\n".join(lines) + "\n"


def fetch_boc(rid: str) -> str:
    """Bank of Canada Valet series -> observation_date,value CSV."""
    out = _curl([BOC_URL.format(rid=rid)], f"BoC {rid}")
    data = json.loads(out)
    obs = data.get("observations")
    if not obs:
        raise ValueError(f"BoC returned no observations for {rid}")
    lines = ["observation_date,value"]
    for o in obs:
        v = o.get(rid, {}).get("v", "")
        if v != "":
            lines.append(f"{o['d']},{v}")
    return "\n".join(lines) + "\n"


def _abs_date(tp: str) -> str:
    """ABS TIME_PERIOD -> observation_date. '2026-Q2' -> '2026-04-01'; passes 'YYYY-MM'/'YYYY' too."""
    if "-Q" in tp:
        y, q = tp.split("-Q")
        return f"{y}-{(int(q) - 1) * 3 + 1:02d}-01"
    if len(tp) == 7 and tp[4] == "-":       # YYYY-MM
        return f"{tp}-01"
    if len(tp) == 4:                         # YYYY
        return f"{tp}-01-01"
    return tp


def fetch_abs(rid: str) -> str:
    """ABS Data API (SDMX CSV) -> observation_date,value CSV, sorted by date."""
    import csv, io
    out = _curl(["-H", "Accept: application/vnd.sdmx.data+csv", ABS_URL.format(rid=rid)],
                f"ABS {rid}")
    rows = list(csv.DictReader(io.StringIO(out)))
    if not rows or "TIME_PERIOD" not in rows[0]:
        raise ValueError(f"unexpected ABS response for {rid}")
    recs = sorted(((_abs_date(r["TIME_PERIOD"]), r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE")),
                  key=lambda x: x[0])
    return "observation_date,value\n" + "\n".join(f"{d},{v}" for d, v in recs) + "\n"


def _eu_period(p: str) -> str:
    """Eurostat time period -> observation_date. '2026-Q2' -> '2026-04-01'; '2025-12' -> '2025-12-01'."""
    if "-Q" in p:
        y, q = p.split("-Q")
        return f"{y}-{(int(q) - 1) * 3 + 1:02d}-01"
    return f"{p}-01"  # 'YYYY-MM'


def _fetch_eurostat(url: str, what: str) -> str:
    """Eurostat JSON-stat for one geo -> observation_date,value CSV. The flat value map is
    keyed by index; the time dimension maps each period to that index (single-geo query, so
    the flat index is just the time order)."""
    out = _curl([url], what)
    d = json.loads(out)
    if "value" not in d or "dimension" not in d:
        raise ValueError(f"unexpected Eurostat response for {what}: {out[:150]}")
    tindex = d["dimension"]["time"]["category"]["index"]
    values = d["value"]
    recs = sorted((_eu_period(p), values[str(i)]) for p, i in tindex.items() if str(i) in values)
    if not recs:
        raise ValueError(f"Eurostat returned no values for {what}")
    return "observation_date,value\n" + "\n".join(f"{dte},{v}" for dte, v in recs) + "\n"


def fetch_eu_hicp(rid: str) -> str:
    return _fetch_eurostat(EU_HICP_URL.format(rid=rid), f"Eurostat HICP {rid}")


def fetch_eu_gdp(rid: str) -> str:
    return _fetch_eurostat(EU_GDP_URL.format(rid=rid), f"Eurostat GDP {rid}")


_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def fetch_ons(rid: str) -> str:
    """ONS (UK) timeseries JSON -> observation_date,value CSV from the monthly series."""
    out = _curl([ONS_URL.format(rid=rid)], f"ONS {rid}")
    d = json.loads(out)
    months = d.get("months") or []
    if not months:
        raise ValueError(f"ONS returned no monthly data for {rid}")
    recs = sorted((f"{int(r['year'])}-{_MONTHS[r['month']]:02d}-01", r["value"]) for r in months)
    return "observation_date,value\n" + "\n".join(f"{dte},{v}" for dte, v in recs) + "\n"


def fetch_imf_ifs(rid: str) -> str:
    """IMF IFS series via DBnomics -> observation_date,value CSV. Monthly periods 'YYYY-MM'."""
    out = _curl([DBNOMICS_IFS_URL.format(rid=rid)], f"IMF IFS {rid}")
    d = json.loads(out)
    docs = d.get("series", {}).get("docs", [])
    if not docs:
        raise ValueError(f"no IMF/IFS series for {rid}")
    s = docs[0]
    recs = [(_eu_period(p), v) for p, v in zip(s.get("period", []), s.get("value", []))
            if v is not None and v != "NA"]   # _eu_period handles 'YYYY-MM' and 'YYYY-Qn'
    if not recs:
        raise ValueError(f"IMF/IFS returned no values for {rid}")
    return "observation_date,value\n" + "\n".join(f"{dte},{v}" for dte, v in recs) + "\n"


FETCHERS = {"fred": fetch_fred, "fred_graph": fetch_fred_graph,
            "statcan": fetch_statcan, "boc": fetch_boc, "abs": fetch_abs,
            "eu_hicp": fetch_eu_hicp, "eu_gdp": fetch_eu_gdp, "ons": fetch_ons,
            "imf_ifs": fetch_imf_ifs}


def summarize(text: str) -> dict:
    """n_obs and the first/last date carrying a real value (value in the LAST column)."""
    rows = [ln.split(",") for ln in text.splitlines()[1:] if ln.strip()]
    valued = [(r[0], r[-1]) for r in rows if r[-1] not in (".", "")]
    return {"n_obs": len(valued),
            "first_date": valued[0][0] if valued else None,
            "last_date": valued[-1][0] if valued else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-fetch every series even if cached")
    selection = ap.add_mutually_exclusive_group()
    selection.add_argument("--country", help="limit to one country (e.g. Australia)")
    selection.add_argument("--emerging", action="store_true",
                           help="limit fetching to the configured emerging markets")
    ap.add_argument("--list", action="store_true", help="list configured series and exit")
    args = ap.parse_args()

    emerging_names = {name for name, _iso in EM_MARKET_CODES}
    countries = {k: v for k, v in COUNTRIES.items()
                 if (
                     args.country and k.lower() == args.country.lower()
                     or args.emerging and k in emerging_names
                     or not args.country and not args.emerging
                 )}
    if args.country and not countries:
        print(f"unknown country '{args.country}'; known: {', '.join(COUNTRIES)}", file=sys.stderr)
        return 2

    if args.list:
        for country, srcs in countries.items():
            print(f"\n{country}:")
            for s in srcs:
                print(f"  {s.provider:8s} {s.rid:22s} -> {s.file:42s} {s.desc}")
        return 0

    RAW.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Manifest holds a per-country vintage so refreshing one country never bumps another's
    # published data-vintage stamp. Migrate the old Canada-only flat format on first run.
    old = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    cm: dict = old.get("countries")
    if cm is None:
        cm = {}
        if "series" in old:  # legacy flat format -> all of it was Canada
            cm["Canada"] = {"vintage": old.get("pulled_at", now), "series": old["series"]}
    failures = []

    for country, srcs in countries.items():
        print(f"\n{country}:")
        any_fetched, series_info = False, {}
        for s in srcs:
            path = RAW / s.file
            if path.exists() and not args.refresh:
                text, action = path.read_text(), "cached"
            else:
                try:
                    text = FETCHERS[s.provider](s.rid)
                    path.write_text(text)
                    action, any_fetched = "fetched", True
                    time.sleep(PACE)
                except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as e:
                    print(f"  FAIL {s.provider:8s} {s.rid:22s} {e}", file=sys.stderr)
                    failures.append(f"{country}/{s.file}")
                    continue
            info = summarize(text)
            series_info[s.file] = {"provider": s.provider, "rid": s.rid, "description": s.desc, **info}
            print(f"  {action:8s} {s.provider:8s} {s.rid:22s} n={info['n_obs']:<5} "
                  f"{info['first_date']} .. {info['last_date']}")
        # Skip countries where nothing was obtained and nothing was cached before, so a
        # fully-failed fetch (e.g. FRED throttling) doesn't write an empty manifest entry.
        if not series_info and country not in cm:
            print("  (no data obtained — manifest entry not written)")
            continue
        # Vintage advances only if something was actually re-fetched this run.
        prior_vintage = cm.get(country, {}).get("vintage")
        vintage = now if any_fetched or not prior_vintage else prior_vintage
        cm[country] = {"vintage": vintage, "series": series_info or cm.get(country, {}).get("series", {})}
        print(f"  vintage: {vintage}")

    MANIFEST.write_text(json.dumps({"countries": cm}, indent=2))
    print(f"\nManifest written: {MANIFEST}")
    if failures:
        print(f"\n{len(failures)} series failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

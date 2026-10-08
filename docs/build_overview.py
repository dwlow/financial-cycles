"""Build the data behind the board page (GitHub Pages site in /docs).

Runs the engine for every advanced market and emerging-market monitor, writing docs/index_data.js —
`const DATA = {...}` — which index.html loads with a plain <script src> tag. Every
.html page in docs/ is hand-edited; this script is the only thing that writes here,
and index_data.js is the only file it writes.

    PYTHONPATH=/home/ethan13/financial-cycles python docs/build_overview.py

Reads:  data/raw/manifest.json          (per-country vintage)
Writes: docs/index_data.js              (the board's data payload)
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.config import (
    ALL_COUNTRIES, EM_COUNTRIES, EM_MARKET_CODES,
    EM_SOURCE_SERIES, RAW,
    AM_METHOD, EM_METHOD,
)
from engine.run import run, run_monitor

ROOT = Path(__file__).resolve().parents[1]
SITE = Path(__file__).resolve().parent  # the docs/ folder GitHub Pages serves
OUT_JS = SITE / "index_data.js"


def _series(res, col):
    """One-sided gap series as [{q, v}] over its defined span (rounded %)."""
    s = res[col].dropna()
    return [{"q": str(q), "v": round(float(v), 2)} for q, v in s.items()]


def _country(name, cfg, vintages):
    res = run(cfg)
    scored = res.dropna(subset=["OI"])
    last, q = scored.iloc[-1], str(scored.index[-1])
    oi_hist = [{"q": str(i), "oi": round(float(r["OI"]), 3),
                "fe": int(r["flag_equity"]), "fg": int(r["flag_gdp"])}
               for i, r in scored.iterrows()]
    return {
        "name": name,
        "vintage": vintages.get(name, ""),
        "latest": {"q": q, "oi": round(float(last["OI"]), 3),
                   "eq": round(float(last["gap_1s_equity"]), 2),
                   "gd": round(float(last["gap_1s_gdp"]), 2),
                   "fe": int(last["flag_equity"]), "fg": int(last["flag_gdp"])},
        "oi_hist": oi_hist,
        "equity": _series(res, "gap_1s_equity"),
        "gdp": _series(res, "gap_1s_gdp"),
    }


def _monitor_market(name, cfg, vintages):
    res = run_monitor(cfg)
    gaps = {
        component: _series(res, f"gap_1s_{component}")
        for component in EM_METHOD.index_components
    }
    scored = res.dropna(subset=["OI"])
    if any(not values for values in gaps.values()) or scored.empty:
        raise ValueError(f"{name}: emerging-market index has no common gap history")
    index_history = [
        {
            "q": str(q),
            "oi": round(float(row["OI"]), 3),
            **{
                f"flag_{component}": int(row[f"flag_{component}"])
                for component in EM_METHOD.index_components
            },
        }
        for q, row in scored.iterrows()
    ]
    latest = scored.iloc[-1]
    q = str(scored.index[-1])
    return {
        "name": name,
        "group": "emerging",
        "vintage": vintages.get(name, ""),
        "index_hist": index_history,
        "latest": {
            "q": q,
            "oi": round(float(latest["OI"]), 3),
            **{
                component: round(float(latest[f"gap_1s_{component}"]), 2)
                for component in EM_METHOD.index_components
            },
        },
        "availability": "scored",
        **gaps,
    }


def _unavailable_market(name):
    cfg = EM_COUNTRIES.get(name)
    missing = [
        component for component in EM_METHOD.index_components
        if cfg is None or component not in cfg.series
    ]
    if missing:
        reason = "FRED series unavailable for " + ", ".join(missing)
    elif "cpi" not in EM_SOURCE_SERIES[name]:
        reason = "IMF IFS CPI unavailable for deflating nominal series"
    else:
        uncached = []
        if not (RAW / cfg.cpi.file).is_file():
            uncached.append("CPI")
        uncached.extend(
            component for component in EM_METHOD.index_components
            if not (RAW / cfg.series[component].file).is_file()
        )
        reason = "Source data not downloaded locally for " + ", ".join(uncached)
    return {
        "name": name,
        "group": "emerging",
        "availability": "unavailable",
        "reason": reason,
    }


def build_payload() -> dict:
    manifest = json.load(open(ROOT / "data" / "raw" / "manifest.json"))
    vintages = {c: d.get("vintage", "")[:10] for c, d in manifest.get("countries", {}).items()}

    countries = [_country(n, c, vintages) for n, c in ALL_COUNTRIES.items()]
    countries.sort(key=lambda c: (-c["latest"]["oi"], c["name"]))  # hottest first
    emerging_all = [
        (_monitor_market(name, EM_COUNTRIES[name], vintages)
         if name in EM_COUNTRIES
         and "cpi" in EM_SOURCE_SERIES[name]
         and all(component in EM_COUNTRIES[name].series
                 for component in EM_METHOD.index_components)
         and all((RAW / EM_COUNTRIES[name].series[component].file).is_file()
                 for component in EM_METHOD.index_components)
         and (RAW / EM_COUNTRIES[name].cpi.file).is_file()
         else _unavailable_market(name))
        for name, _iso in EM_MARKET_CODES
    ]
    emerging_all.sort(key=lambda c: c["name"])
    emerging = [c for c in emerging_all if c["availability"] == "scored"]
    emerging_dropped = [c["name"] for c in emerging_all if c["availability"] != "scored"]

    # Laeven & Valencia (2020) systemic banking-crisis eras -> strip markers
    lv = json.load(open(ROOT / "data" / "reference" / "lv2020_crises.json"))
    for c in countries:
        c["crises"] = lv["crises"].get(c["name"], [])

    # click-a-quarter source links: provider + series id straight from the fetch registry
    import fetch_data
    file_src = {s.file: (s.provider, s.rid)
                for srcs in fetch_data.COUNTRIES.values() for s in srcs}
    # Wikipedia "YYYY in {name}" article naming (articles/differing names)
    wiki = {"United States": "the United States", "United Kingdom": "the United Kingdom",
            "Netherlands": "the Netherlands", "Czech Republic": "the Czech Republic",
            "Slovak Republic": "Slovakia", "Korea": "South Korea"}
    for group, registry in ((countries, ALL_COUNTRIES), (emerging, EM_COUNTRIES)):
        for c in group:
            if c["name"] not in registry:
                continue
            cfg = registry[c["name"]]
            links = {}
            link_components = (
                EM_METHOD.index_components if c.get("group") == "emerging"
                else ("equity", "gdp")
            )
            for key in link_components:
                spec = cfg.series.get(key)
                if spec and spec.file in file_src:
                    prov, rid = file_src[spec.file]
                    if prov in ("fred", "fred_graph", "imf_ifs"):
                        links[key] = {"p": prov, "rid": rid}
            c["links"] = links
            c["wiki"] = wiki.get(c["name"], c["name"])

    hot = sum(1 for c in countries if c["latest"]["oi"] > 0)
    return {
        "thresholds": AM_METHOD.thresholds,
        "weights": AM_METHOD.weights,
        "bands": {n: [AM_METHOD.bands[n].low, AM_METHOD.bands[n].high]
                  for n in AM_METHOD.index_components},
        "summary": {"n": len(countries), "hot": hot, "calm": len(countries) - hot,
                    "n_emerging": len(emerging_all),
                    "n_emerging_scored": len(emerging),
                    "n_emerging_unavailable": len(emerging_dropped)},
        "emerging_method": {
            "thresholds": EM_METHOD.thresholds,
            "weights": EM_METHOD.weights,
            "bands": {n: [EM_METHOD.bands[n].low, EM_METHOD.bands[n].high]
                      for n in EM_METHOD.index_components},
        },
        "dropped": ["Cyprus", "Malta", "Singapore", "Taiwan"],
        "countries": countries,
        "emerging_markets": emerging,
        "emerging_unavailable_markets": [
            market for market in emerging_all if market["availability"] != "scored"
        ],
        "emerging_dropped": emerging_dropped,
    }


def main() -> int:
    data = build_payload()
    OUT_JS.write_text("const DATA=" + json.dumps(data, separators=(",", ":")) + ";\n")
    print(f"wrote {OUT_JS}  ({OUT_JS.stat().st_size:,} bytes)")
    print(f"countries: {data['summary']['n']}  hot: {data['summary']['hot']}  "
          f"calm: {data['summary']['calm']}")
    print("hottest:", ", ".join(f"{c['name']}({c['latest']['oi']})" for c in data["countries"][:7]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

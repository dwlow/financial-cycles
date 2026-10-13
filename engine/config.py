"""Configuration for the AM Overheating Index engine.

Every run is driven by two configs (CALCULATIONS.md, "Extensibility / architecture"):

  MethodConfig  - the paper's shared method, identical across all Advanced Markets so
                  gaps stay comparable to the calibrated thresholds: AM frequency bands
                  (Table 2), thresholds & weights (Table 5), the CF drift setting, and
                  the Harding-Pagan censoring parameters. The emerging-market monitor
                  uses a separate credit/equity/property method and cycle bands.
  CountryConfig - which raw series feed the engine for one country. Swap this alone to
                  apply the engine to another AM. Canada is the first instance.

Values are sourced from Chen & Svirydzenka (2021), IMF WP/21/116:
  * bands      - Table 2 (AM sample)
  * AM thresholds and weights - Table 5's AM equity/GDP model
  * EM thresholds and weights - Table 5's credit/equity/property model
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

# Pinned raw data vintage (see data/raw/manifest.json).
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


@dataclass(frozen=True)
class Band:
    """CF pass-band in quarters: keep oscillations with period in [low, high]."""
    low: int    # p_l, minimum period  (statsmodels `low`)
    high: int   # p_u, maximum period  (statsmodels `high`)


@dataclass(frozen=True)
class SeriesSpec:
    """One raw input series and how to turn it real."""
    file: str        # filename in data/raw
    column: str      # value column in that CSV
    freq: str        # 'Q' quarterly, or 'M' monthly (CPI) -> aggregated to Q
    deflate: bool    # divide by quarterly CPI to get a real series? (Step 2)


@dataclass(frozen=True)
class MethodConfig:
    bands: dict[str, Band]
    thresholds: dict[str, float]           # % dev from trend; index components only
    weights: dict[str, float]              # published normalized OI weights (Table 5)
    index_components: tuple[str, ...]      # feed the Overheating Index
    dashboard_components: tuple[str, ...]  # context only, no calibrated threshold
    cf_drift: bool = True


@dataclass(frozen=True)
class CountryConfig:
    name: str
    cpi: SeriesSpec                # monthly CPI deflator (Step 1)
    series: dict[str, SeriesSpec]  # logical name -> spec
    market_group: Literal["advanced", "emerging"] = "advanced"
    # External published output-gap series for the Phase-3 GDP-gap cross-check (already in
    # percent, so deflate=False and no logging). Empty = no cross-check for this country.
    crosscheck_gaps: dict[str, SeriesSpec] = field(default_factory=dict)


# ---- The paper's Advanced-Market method (shared across all AMs) -------------
AM_METHOD = MethodConfig(
    bands={
        "equity":   Band(8, 22),   # Table 2 (AM)
        "gdp":      Band(3, 51),
        "credit":   Band(5, 50),   # dashboard
        "property": Band(5, 36),   # dashboard
    },
    thresholds={"equity": 6.7, "gdp": 1.3},    # Table 5 (AM)
    weights={"equity": 0.497, "gdp": 0.503},   # Table 5 (AM), normalized
    index_components=("equity", "gdp"),
    dashboard_components=("credit", "property"),
)

# Emerging-market exploratory index. It uses the credit/equity/property model from Table 5
# with the supplied emerging-market cycle-length limits. Its data inputs are not yet
# configured for any market, so the board must not publish scores until they are available.
EM_METHOD = replace(
    AM_METHOD,
    bands={
        "equity": Band(8, 18),
        "credit": Band(5, 43),
        "property": Band(4, 29),
    },
    thresholds={"credit": 2.9, "equity": 10.3, "property": 7.5},
    weights={"credit": 0.242, "equity": 0.373, "property": 0.385},
    index_components=("credit", "equity", "property"),
    dashboard_components=(),
)


# ---- Canada (first country instance) ---------------------------------------
CANADA = CountryConfig(
    name="Canada",
    cpi=SeriesSpec("cpi_statcan__v41690973.csv", "value", "M", deflate=False),
    series={
        "equity":   SeriesSpec("share_prices_nominal__SPASTT01CAQ661N.csv", "SPASTT01CAQ661N", "Q", deflate=True),
        "gdp":      SeriesSpec("real_gdp__NGDPRSAXDCCAQ.csv",               "NGDPRSAXDCCAQ",   "Q", deflate=False),
        "credit":   SeriesSpec("total_credit_level__CRDQCAAPABIS.csv",      "CRDQCAAPABIS",    "Q", deflate=True),
        "property": SeriesSpec("real_residential_property__QCAR628BIS.csv", "QCAR628BIS",      "Q", deflate=False),
    },
    crosscheck_gaps={
        "BoC Current MPR":          SeriesSpec("boc_output_gap_mpr__INDINF_OUTGAPMPR_Q.csv", "value", "Q", deflate=False),
        "BoC Integrated Framework": SeriesSpec("boc_output_gap_if__INDINF_OUTGAPI_Q.csv",    "value", "Q", deflate=False),
        "BoC Extended MV Filter":   SeriesSpec("boc_output_gap_emvf__INDINF_OUTGAPM_Q.csv",  "value", "Q", deflate=False),
    },
)


# ---- Australia (second country; core pilot) --------------------------------
# Equity & GDP from FRED (files load as-is: FRED CSVs already have observation_date +
# the series id as the value column). CPI from ABS (All groups CPI, Index Numbers,
# quarterly), normalized to observation_date,value in AU__cpi.csv. Credit/property
# (dashboard) and an output-gap cross-check can be added later.
AUSTRALIA = CountryConfig(
    name="Australia",
    cpi=SeriesSpec("AU__cpi.csv", "value", "Q", deflate=False),
    series={
        "equity": SeriesSpec("AU__share_prices_nominal.csv", "SPASTT01AUQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("AU__real_gdp.csv",             "NGDPRSAXDCAUQ",   "Q", deflate=False),
    },
)


# ---- United States (core pilot) --------------------------------------------
# All three from FRED. CPI = CPIAUCSL (BLS CPI-U, monthly, SA) — current, unlike the
# lagging OECD CPI; only its deviation-from-trend is used, so base year is irrelevant.
UNITED_STATES = CountryConfig(
    name="United States",
    cpi=SeriesSpec("US__cpi.csv", "CPIAUCSL", "M", deflate=False),
    series={
        "equity": SeriesSpec("US__share_prices_nominal.csv", "SPASTT01USQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("US__real_gdp.csv",             "NGDPRSAXDCUSQ",   "Q", deflate=False),
    },
)


# ---- United Kingdom (equity+GDP from FRED, CPI from ONS) --------------------
UNITED_KINGDOM = CountryConfig(
    name="United Kingdom",
    cpi=SeriesSpec("GB__cpi.csv", "value", "M", deflate=False),
    series={
        "equity": SeriesSpec("GB__share_prices_nominal.csv", "SPASTT01GBQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("GB__real_gdp.csv",             "NGDPRSAXDCGBQ",   "Q", deflate=False),
    },
)


# ---- Japan (equity+GDP from FRED, CPI from IMF IFS via DBnomics) ------------
# FRED's OECD Japan CPI is dead (stops 2022); IMF IFS is the no-key current-ish source
# (lags ~1yr). e-Stat would be bang-current but needs a registered appId — deferred.
JAPAN = CountryConfig(
    name="Japan",
    cpi=SeriesSpec("JP__cpi.csv", "value", "M", deflate=False),
    series={
        "equity": SeriesSpec("JP__share_prices_nominal.csv", "SPASTT01JPQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("JP__real_gdp.csv",             "NGDPRSAXDCJPQ",   "Q", deflate=False),
    },
)


# ---- Israel & New Zealand (equity FRED; GDP + CPI from IMF IFS) -------------
# No FRED GDP for either; IMF IFS quarterly real GDP fills in. NZ reports CPI quarterly
# (no monthly IMF series), so its CPI freq is 'Q' rather than 'M'.
ISRAEL = CountryConfig(
    name="Israel",
    cpi=SeriesSpec("IL__cpi.csv", "value", "M", deflate=False),
    series={
        "equity": SeriesSpec("IL__share_prices_nominal.csv", "SPASTT01ILQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("IL__real_gdp.csv",             "value",           "Q", deflate=False),
    },
)

NEW_ZEALAND = CountryConfig(
    name="New Zealand",
    cpi=SeriesSpec("NZ__cpi.csv", "value", "Q", deflate=False),
    series={
        "equity": SeriesSpec("NZ__share_prices_nominal.csv", "SPASTT01NZQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("NZ__real_gdp.csv",             "value",           "Q", deflate=False),
    },
)


# ---- Hong Kong (all three series from IMF IFS) ------------------------------
# No FRED/OECD coverage (non-OECD member). Equity = IFS share-price index (FPE_IX),
# a documented proxy for OECD SPASTT01 — both broad national share-price indices.
# Equity starts 1996 (shortest history in the set); IMF lag ~1yr like Japan/Korea/Israel.
HONG_KONG = CountryConfig(
    name="Hong Kong",
    cpi=SeriesSpec("HK__cpi.csv", "value", "M", deflate=False),
    series={
        "equity": SeriesSpec("HK__share_prices_nominal.csv", "value", "Q", deflate=True),
        "gdp":    SeriesSpec("HK__real_gdp.csv",             "value", "Q", deflate=False),
    },
)


# ---- Korea (equity+GDP from FRED, CPI from IMF IFS) ------------------------
KOREA = CountryConfig(
    name="Korea",
    cpi=SeriesSpec("KR__cpi.csv", "value", "M", deflate=False),
    series={
        "equity": SeriesSpec("KR__share_prices_nominal.csv", "SPASTT01KRQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("KR__real_gdp.csv",             "NGDPRSAXDCKRQ",   "Q", deflate=False),
    },
)


# ---- Switzerland (equity FRED, GDP Eurostat/EFTA, CPI IMF IFS) --------------
# No FRED GDP series for CH; Eurostat covers it as an EFTA member. CPI via IMF IFS.
SWITZERLAND = CountryConfig(
    name="Switzerland",
    cpi=SeriesSpec("CH__cpi.csv", "value", "M", deflate=False),
    series={
        "equity": SeriesSpec("CH__share_prices_nominal.csv", "SPASTT01CHQ661N", "Q", deflate=True),
        "gdp":    SeriesSpec("CH__real_gdp.csv",             "value",           "Q", deflate=False),
    },
)


# ---- EU/EEA advanced-market bloc --------------------------------------------
# Uniform recipe across the bloc: equity from FRED (SPASTT01{iso}), GDP + CPI from Eurostat,
# both normalized to observation_date,value. Cyprus & Malta are excluded (no FRED share-price
# series). File prefix = FRED iso2; the Eurostat geo (Greece = EL) lives in the fetch registry
# (fetch_data.py EU_AM), not here. (display name, FRED iso2 / file prefix).
_EU_AM = [
    ("Austria", "AT"), ("Belgium", "BE"), ("Czech Republic", "CZ"), ("Denmark", "DK"),
    ("Estonia", "EE"), ("Finland", "FI"), ("France", "FR"), ("Germany", "DE"),
    ("Greece", "GR"), ("Ireland", "IE"), ("Italy", "IT"), ("Luxembourg", "LU"),
    ("Netherlands", "NL"), ("Portugal", "PT"), ("Slovak Republic", "SK"), ("Slovenia", "SI"),
    ("Spain", "ES"), ("Sweden", "SE"), ("Iceland", "IS"), ("Norway", "NO"),
]


def _eu_config(name: str, iso: str) -> CountryConfig:
    return CountryConfig(
        name=name,
        cpi=SeriesSpec(f"{iso}__cpi.csv", "value", "M", deflate=False),
        series={
            "equity": SeriesSpec(f"{iso}__share_prices_nominal.csv", f"SPASTT01{iso}Q661N", "Q", deflate=True),
            "gdp":    SeriesSpec(f"{iso}__real_gdp.csv", "value", "Q", deflate=False),
        },
    )


EU_CONFIGS = {name: _eu_config(name, iso) for name, iso in _EU_AM}

# ---- Emerging-market monitor coverage --------------------------------------
# FRED mirrors BIS total-credit and real residential-property-price data, and OECD
# nominal share-price indices. Only country/component series confirmed to return
# observations are listed. CPI remains sourced from the already-configured IMF IFS inputs.
EM_MARKET_CODES = [
    ("Argentina", "AR"), ("Brazil", "BR"), ("Bulgaria", "BG"), ("China", "CN"),
    ("Colombia", "CO"), ("Croatia", "HR"), ("Hungary", "HU"), ("India", "IN"),
    ("Indonesia", "ID"), ("Lithuania", "LT"), ("Malaysia", "MY"), ("Mexico", "MX"),
    ("Philippines", "PH"), ("Poland", "PL"), ("Russia", "RU"), ("Serbia", "RS"),
    ("South Africa", "ZA"), ("Thailand", "TH"), ("Turkey", "TR"), ("Ukraine", "UA"),
    ("Uruguay", "UY"), ("Latvia", "LV"), ("Kazakhstan", "KZ"), ("Romania", "RO"),
    ("Vietnam", "VN"),
]

EM_SOURCE_SERIES = {
    "Argentina": ("equity", "gdp"), "Brazil": ("equity", "gdp", "cpi"),
    "Bulgaria": ("gdp", "cpi"), "China": ("equity", "cpi"),
    "Colombia": ("gdp", "cpi"), "Croatia": ("gdp", "cpi"),
    "Hungary": ("gdp", "cpi"), "India": ("equity", "gdp", "cpi"),
    "Indonesia": ("gdp", "cpi"), "Lithuania": ("gdp", "cpi"),
    "Malaysia": ("equity", "cpi"), "Mexico": ("equity", "gdp", "cpi"),
    "Philippines": ("equity", "gdp", "cpi"), "Poland": ("equity", "gdp", "cpi"),
    "Russia": ("equity", "cpi"), "Serbia": ("gdp", "cpi"),
    "South Africa": ("equity", "gdp", "cpi"), "Thailand": ("equity", "gdp", "cpi"),
    "Turkey": ("equity", "gdp", "cpi"), "Ukraine": ("gdp", "cpi"),
    "Uruguay": ("cpi",), "Latvia": ("gdp", "cpi"),
    "Kazakhstan": ("gdp", "cpi"), "Romania": ("gdp", "cpi"),
    "Vietnam": ("cpi",),
}

# Public FRED series IDs. Credit is BIS break-adjusted total credit to the private
# non-financial sector; R628 is the BIS real residential property price index.
# Equity is the OECD quarterly share-price index. Every listed ID was checked for
# non-missing observations through FRED's public graph CSV endpoint.
EM_FRED_SERIES = {
    "Argentina": {"credit": "CRDQARAPABIS"},
    "Brazil": {
        "credit": "CRDQBRAPABIS",
        "equity": "SPASTT01BRQ661N",
        "property": "QBRR628BIS",
    },
    "Bulgaria": {"property": "QBGR628BIS"},
    "China": {
        "credit": "CRDQCNAPABIS",
        "equity": "SPASTT01CNQ661N",
        "property": "QCNR628BIS",
    },
    "Colombia": {"property": "QCOR628BIS"},
    "Croatia": {"property": "QHRR628BIS"},
    "Hungary": {
        "credit": "CRDQHUAPABIS",
        "equity": "SPASTT01HUQ661N",
        "property": "QHUR628BIS",
    },
    "India": {
        "credit": "CRDQINAPABIS",
        "equity": "SPASTT01INQ661N",
        "property": "QINR628BIS",
    },
    "Indonesia": {
        "credit": "CRDQIDAPABIS",
        "equity": "SPASTT01IDQ661N",
        "property": "QIDR628BIS",
    },
    "Lithuania": {"property": "QLTR628BIS"},
    "Malaysia": {"credit": "CRDQMYAPABIS", "property": "QMYR628BIS"},
    "Mexico": {
        "credit": "CRDQMXAPABIS",
        "equity": "SPASTT01MXQ661N",
        "property": "QMXR628BIS",
    },
    "Philippines": {"property": "QPHR628BIS"},
    "Poland": {
        "credit": "CRDQPLAPABIS",
        "equity": "SPASTT01PLQ661N",
        "property": "QPLR628BIS",
    },
    "Russia": {
        "credit": "CRDQRUAPABIS",
        "equity": "SPASTT01RUQ661N",
        "property": "QRUR628BIS",
    },
    "Serbia": {"property": "QRSR628BIS"},
    "South Africa": {
        "credit": "CRDQZAAPABIS",
        "equity": "SPASTT01ZAQ661N",
        "property": "QZAR628BIS",
    },
    "Thailand": {"credit": "CRDQTHAPABIS", "property": "QTHR628BIS"},
    "Turkey": {
        "credit": "CRDQTRAPABIS",
        "equity": "SPASTT01TRQ661N",
        "property": "QTRR628BIS",
    },
    "Latvia": {"property": "QLVR628BIS"},
    "Romania": {"property": "QROR628BIS"},
}

EM_NON_FRED_SERIES = {
    "Malaysia": {
        "equity": SeriesSpec(
            "MY__share_prices_nominal.csv", "value", "Q", deflate=True,
        ),
    },
    "Thailand": {
        "equity": SeriesSpec(
            "TH__share_prices_nominal.csv", "value", "Q", deflate=True,
        ),
    },
}

EM_DATA_LIMITATIONS = {
    name: "Missing FRED series for " + ", ".join(
        component for component in EM_METHOD.index_components
        if component not in EM_FRED_SERIES.get(name, {})
        and component not in EM_NON_FRED_SERIES.get(name, {})
    )
    for name, _iso in EM_MARKET_CODES
    if any(
        component not in EM_FRED_SERIES.get(name, {})
        and component not in EM_NON_FRED_SERIES.get(name, {})
        for component in EM_METHOD.index_components
    )
}


def _em_config(name: str, iso: str) -> CountryConfig:
    series = {}
    file_names = {
        "credit": f"{iso}__fred_credit.csv",
        "equity": f"{iso}__fred_equity.csv",
        "property": f"{iso}__fred_property.csv",
    }
    for component, rid in EM_FRED_SERIES.get(name, {}).items():
        series[component] = SeriesSpec(
            file_names[component],
            rid,
            "Q",
            deflate=component in ("credit", "equity"),
        )
    series.update(EM_NON_FRED_SERIES.get(name, {}))
    return CountryConfig(
        name=name,
        cpi=SeriesSpec(f"{iso}__cpi.csv", "value", "M", deflate=False),
        series=series,
        market_group="emerging",
    )

EM_COUNTRIES = {name: _em_config(name, iso) for name, iso in EM_MARKET_CODES}

# Master registry of every configured country (used to run/build the whole set).
ALL_COUNTRIES: dict[str, CountryConfig] = {
    "Canada": CANADA, "Australia": AUSTRALIA, "United States": UNITED_STATES,
    "United Kingdom": UNITED_KINGDOM, "Japan": JAPAN, "Switzerland": SWITZERLAND,
    "Korea": KOREA, "Israel": ISRAEL, "New Zealand": NEW_ZEALAND, "Hong Kong": HONG_KONG,
    **EU_CONFIGS,
}

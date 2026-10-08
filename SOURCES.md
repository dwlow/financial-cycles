# Sources & Citations

Running list of every source used, for citation on the final website. Grouped by role.
Links marked (bot-403) return 403 to automated checks but resolve fine in a browser.

## Primary methodology

- **Chen, S. & Svirydzenka, K. (2021). "Financial Cycles – Early Warning Indicators of
  Banking Crises?" IMF Working Paper WP/21/116.**
  The method we replicate (Advanced-Market track). SSRN abstract 3970194.
  - https://ssrn.com/abstract=3970194  (bot-403)
  - Also published on imf.org (search "WP/21/116").
  - Local copy: `Financial Cycles – Early Warning - SSRN-id3970194.pdf`

## Methods the paper builds on (cited by us)

- **Christiano, L. J. & Fitzgerald, T. J. (2003). "The Band Pass Filter."
  International Economic Review 44(2), 435–465.**
  The band-pass filter we use. Free version: NBER Working Paper 7257 (1999).
  - https://www.nber.org/papers/w7257
  - PDF: https://www.nber.org/system/files/working_papers/w7257/w7257.pdf
  - Journal DOI: 10.1111/1468-2354.t01-1-00076 (paywalled)
- **Harding, D. & Pagan, A. (2002). "Dissecting the Cycle: A Methodological
  Investigation." Journal of Monetary Economics 49(2), 365–381.**
  Turning-point dating algorithm the paper uses to derive its Table 2 cycle-length bands.
  We consume those bands directly and do not run the dating step ourselves.
- **Claessens, S., Kose, M. A. & Terrones, M. E. — (2011a) "Financial Cycles: What? How?
  When?" IMF WP/11/76; (2011b/2012) "How Do Business and Financial Cycles Interact?"
  Journal of International Economics 87(1), 178–190.**
  The specific BBQ implementation of Harding–Pagan that Chen & Svirydzenka follow for cycle
  dating: run on the log-level, min phase 2 quarters, min complete cycle 5 quarters, with
  the 2-quarter min-phase waived when a one-quarter asset-price decline exceeds 20%. Cited
  for provenance of the Table 2 bands; not implemented here.
  - IMF WP/11/76: https://www.imf.org/external/pubs/ft/wp/2011/wp1176.pdf  (bot-403)
  - JIE 2012 (author copy, readable): https://www.marcoterrones.com/uploads/1/7/6/9/17698985/ckt_2012_how_do_business_and_financial_cycles_interact_jie.pdf
- **Kaminsky, G., Lizondo, S. & Reinhart, C. (1998). "Leading Indicators of Currency
  Crises." IMF Staff Papers 45(1).**
  Signal-extraction threshold approach behind the paper's EWS loss function (eq. 4).
- **Laeven, L. & Valencia, F. (2018). "Systemic Banking Crises Revisited."
  IMF Working Paper 18/206.**
  Crisis database the thresholds were calibrated on; basis for the "Canada has no
  systemic banking crisis" framing.

## Software implementation

- **statsmodels `cffilter` (Christiano–Fitzgerald filter), version 0.14.6.**
  Exact code we run for the band-pass filter (incl. the drift adjustment, which the IMF
  paper does not specify — it is an implementation detail from here / CF 2003).
  - Docs: https://www.statsmodels.org/stable/generated/statsmodels.tsa.filters.cf_filter.cffilter.html
  - Source (pinned): https://github.com/statsmodels/statsmodels/blob/v0.14.6/statsmodels/tsa/filters/cf_filter.py
- Python stack pinned in `requirements.txt` (numpy, pandas, scipy, statsmodels).

## Data — series used

`python fetch_data.py --list` prints every configured series for every country (provider,
remote id, output file, description). That registry is the source of truth; the tables below
record only what it cannot: **who actually produces the data** behind an aggregator id, and
the access quirks of each provider.

Data vintage is pinned per country in `data/raw/manifest.json`.

**FRED is an aggregator** — cite the underlying producer:

| FRED id pattern | Underlying producer |
|-----------------|---------------------|
| `SPASTT01*` (share prices) | OECD Main Economic Indicators |
| `NGDPRSAXDC*` (real GDP) | OECD / IMF |
| `*BIS`, `Q**M770A` (credit, property) | Bank for International Settlements |
| `CANCPIALL*` (CPI, cross-check only) | OECD |
| `CPIAUCSL` (US CPI) | US Bureau of Labor Statistics |

**Statistics Canada** — the CPI deflator actually used for Canada:

- CPI, all-items, monthly, 2002=100 — **vector v41690973**, table **18-10-0004-01**.
  - https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401
  - FRED's Canadian CPI is a rebased copy of this same StatCan data, so we use StatCan
    wholesale rather than splicing. The FRED `cpi_*` series are cached as a cross-check only.

**Bank of Canada** — official quarterly output gap (Phase-3 cross-check of our filtered GDP
gap; validation only), via the Valet API:

| Role | BoC series (Valet code) |
|------|-------------------------|
| Output gap — Current MPR | INDINF_OUTGAPMPR_Q |
| Output gap — Integrated Framework | INDINF_OUTGAPI_Q |
| Output gap — Extended Multivariate Filter | INDINF_OUTGAPM_Q |

## Data providers & access notes

Equity and real GDP come from FRED where available; CPI comes from a **national or current
source**, because FRED's OECD CPI lags a year or more. Adapters live in `fetch_data.py`.

| Provider | Serves | Access notes |
|----------|--------|--------------|
| **FRED API** (`api.stlouisfed.org`) | equity, GDP, some CPI | Must use the API with a free key — **not** the `fredgraph.csv` chart endpoint, which WAF-blocks datacenter IPs. Key in gitignored `.fred_api_key`. Throttles bursts; a throttled request hangs until timeout. |
| **Eurostat** (`prc_hicp_midx`, `namq_10_gdp`) | EU/EEA GDP + CPI | Open, no key. One source covers the whole bloc (incl. Switzerland GDP as EFTA). |
| **ONS** (UK) | UK CPI | Open; `www.ons.gov.uk/…/data`. The old `api.ons.gov.uk` is dead. Current. |
| **ABS** (Australia) | AU CPI | Open SDMX. Use the version-less key so it resolves to the latest dataflow. Current. |
| **StatCan** / **Bank of Canada** | CA CPI / output-gap cross-check | Canada only. |
| **IMF IFS** (via DBnomics) | CPI and GDP for non-EU markets; all three series for Hong Kong | Open, no key; uniform across countries; **lags ~1 year**. Hong Kong equity is `FPE_IX`, a documented proxy for OECD `SPASTT01`. |

### Emerging-market monitor series

The emerging-market board lists Argentina, Brazil, Bulgaria, China, Colombia, Croatia,
Hungary, India, Indonesia, Lithuania, Malaysia, Mexico, Philippines, Poland, Russia,
Serbia, South Africa, Thailand, Turkey, Ukraine, Uruguay, Latvia, Kazakhstan, Romania,
and Vietnam. FRED currently provides the full credit/equity/property input set for 10:
Brazil, China, Hungary, India, Indonesia, Mexico, Poland, Russia, South Africa, and Turkey.
Malaysia's and Thailand's credit and property inputs are on FRED; their equity inputs use
the previously verified IMF IFS quarterly `FPE_IX` series. Credit is BIS break-adjusted total credit to the private non-financial sector
(for example, `CRDQBRAPABIS`); equity is the OECD quarterly share-price index (for example,
`SPASTT01BRQ661N`); property is the BIS real residential property price index (for example,
`QBRR628BIS`). CPI for deflating credit and equity uses the existing IMF IFS monthly
`PCPI_IX` series via DBnomics. FRED series identifiers and data vintages are recorded in
`data/raw/manifest.json`; the public graph CSV endpoint is used for FRED downloads, so no
FRED API key is needed for these series. Other markets are excluded when one or more
required series are unavailable; no replacement identifiers are inferred.

## Data providers (for attribution)

- Federal Reserve Bank of St. Louis (FRED) — data aggregator.
- OECD Main Economic Indicators — share prices, GDP.
- Bank for International Settlements (BIS) — credit and property prices.
- Statistics Canada — Consumer Price Index.
- Bank of Canada — official output-gap estimates (GDP-gap cross-check).

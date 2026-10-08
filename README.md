# financial-cycles

Where do rich countries sit in their financial cycle right now — and is any of them
running hot enough to look like the run-up to a banking crisis?

This is a live-data replication of Chen & Svirydzenka (2021), *"Financial Cycles – Early
Warning Indicators of Banking Crises?"* (IMF WP/21/116), across 30 advanced markets, with
an exploratory credit/equity/property index configured for 25 emerging markets.

**→ [See the board](https://ets1199.github.io/financial-cycles/)**

## What it does

The paper found that two measures warn about banking crises better than anything else:
how far **equity prices** and **economic output** sit above their long-run trend. It
calibrated a "too hot" line for each against 40 years of real crises.

This repo pulls both series for 30 countries from public statistical APIs, measures the
gap from trend the same way the paper does, and scores each country 0, ½, or 1 by how
many lines it crosses.

It is **not a crisis forecast.** The thresholds were calibrated on *other* countries'
crises, so a flag means "this looks like conditions that have preceded trouble
elsewhere" — not "a crisis is coming here."

The emerging-market index uses the Table 5 credit, equity, and property thresholds
(2.9%, 10.3%, 7.5%) and normalized weights (0.242, 0.373, 0.385), with cycle bands of
5–43, 8–18, and 4–29 quarters, respectively. Complete inputs are configured for 12 of the
25 requested markets. Credit and real residential property prices are BIS series mirrored
by FRED; equity is the OECD quarterly share-price index except Malaysia and Thailand,
which use the verified IMF IFS quarterly share-price index. Other markets remain listed
but unscored where one or more required series are unavailable.

## Running it

```bash
python fetch_data.py --emerging      # fetch configured emerging-market inputs only
python fetch_data.py --refresh    # pull every series into data/raw/ (quarterly)
python -m engine.run              # compute gaps and the index
python docs/build_overview.py     # regenerate the site's data file
```

`fetch_data.py --list` prints every configured series. FRED needs a free API key in
`.fred_api_key` or `$FRED_API_KEY` ([get one](https://fred.stlouisfed.org/docs/api/api_key.html)).

## Where things are

| | |
|---|---|
| [CALCULATIONS.md](CALCULATIONS.md) | Every quantity we compute, step by step |
| [SOURCES.md](SOURCES.md) | Citations, data providers, and what's sourced from where |
| [decisions/](decisions/) | Why the method is the way it is — one file per decision |
| [docs/](docs/) | The published site (GitHub Pages, served from this folder) |
| Issues | Backlog and planned work |

Data vintage is pinned per country in `data/raw/manifest.json`; cite the `pulled_at`
date with any result.

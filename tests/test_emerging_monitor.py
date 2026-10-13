import unittest
from unittest.mock import patch

import pandas as pd

from engine.config import (
    EM_COUNTRIES, EM_DATA_LIMITATIONS, EM_FRED_SERIES, EM_MARKET_CODES, EM_METHOD,
)
from engine.data import _read
from engine.config import SeriesSpec
from engine.run import run, run_monitor
from fetch_data import COUNTRIES, fetch_fred_graph


class EmergingMonitorTests(unittest.TestCase):
    def test_market_registry_covers_requested_countries_and_marks_incomplete_series(self):
        self.assertEqual(len(EM_MARKET_CODES), 25)
        self.assertEqual(len({name for name, _ in EM_MARKET_CODES}), 25)
        self.assertEqual(len(EM_COUNTRIES), 25)
        self.assertTrue(all(name in COUNTRIES for name, _ in EM_MARKET_CODES))
        self.assertEqual(len(EM_DATA_LIMITATIONS), 13)
        self.assertEqual(
            sum(all(key in cfg.series for key in EM_METHOD.index_components)
                for cfg in EM_COUNTRIES.values()),
            12,
        )

    def test_em_method_uses_credit_equity_property_thresholds_weights_and_bands(self):
        self.assertEqual(
            EM_METHOD.thresholds,
            {"credit": 2.9, "equity": 10.3, "property": 7.5},
        )
        self.assertEqual(
            EM_METHOD.weights,
            {"credit": 0.242, "equity": 0.373, "property": 0.385},
        )
        self.assertEqual(EM_METHOD.index_components, ("credit", "equity", "property"))
        self.assertEqual(EM_METHOD.dashboard_components, ())
        self.assertEqual(
            {name: (band.low, band.high) for name, band in EM_METHOD.bands.items()},
            {
                "equity": (8, 18),
                "credit": (5, 43),
                "property": (4, 29),
            },
        )

    def test_monitor_uses_em_bands_and_scores_credit_equity_and_property(self):
        periods = pd.period_range("1990Q1", periods=100, freq="Q")
        data = pd.DataFrame(
            {
                "log_credit": range(100),
                "log_equity": range(100),
                "log_property": range(100),
            },
            index=periods,
        )
        bands = []

        def one_sided(series, band, _drift):
            bands.append(band)
            return series * 0.01

        with patch("engine.run.prepare", return_value=data), \
             patch("engine.run.filters.one_sided", side_effect=one_sided), \
             patch("engine.run.filters.two_sided", side_effect=lambda s, *_: s * 0.002):
            result = run_monitor(EM_COUNTRIES["Brazil"])

        self.assertEqual(
            bands,
            [EM_METHOD.bands[name] for name in EM_METHOD.index_components],
        )
        self.assertEqual(
            [(band.low, band.high) for band in bands],
            [(5, 43), (8, 18), (4, 29)],
        )
        self.assertEqual(result.attrs["market_group"], "emerging")
        self.assertEqual(result.attrs["country"], "Brazil")
        self.assertEqual(result.loc[periods[-1], "flag_equity"], 1)
        self.assertEqual(result.loc[periods[-1], "flag_credit"], 1)
        self.assertEqual(result.loc[periods[-1], "flag_property"], 1)
        self.assertEqual(result.loc[periods[-1], "OI"], 1.0)
        self.assertEqual(
            [name for name in result if name.startswith("flag_")],
            ["flag_credit", "flag_equity", "flag_property"],
        )

    def test_monitor_rejects_missing_em_index_series(self):
        short_data = pd.DataFrame(
            {"log_equity": [1.0]},
            index=pd.period_range("2020Q1", periods=1, freq="Q"),
        )
        with patch(
            "engine.run.prepare",
            return_value=short_data,
        ):
            with self.assertRaisesRegex(ValueError, "missing required index series"):
                run_monitor(EM_COUNTRIES["Brazil"])

    def test_emerging_market_cannot_use_advanced_market_scoring(self):
        with self.assertRaisesRegex(ValueError, "must use run_monitor"):
            run(EM_COUNTRIES["Brazil"])

    def test_public_fred_graph_csv_fetch_requires_no_api_key_and_validates_series(self):
        with patch("fetch_data._curl", return_value=(
            "observation_date,QBRR628BIS\n2024-01-01,100.0\n"
        )) as curl:
            csv_data = fetch_fred_graph("QBRR628BIS")
        self.assertIn("2024-01-01,100.0", csv_data)
        self.assertIn("QBRR628BIS", curl.call_args.args[0][1])

        with patch("fetch_data._curl", return_value="error\n"):
            with self.assertRaisesRegex(ValueError, "unexpected CSV header"):
                fetch_fred_graph("MISSING")

    def test_fred_graph_falls_back_to_observations_api_when_key_is_configured(self):
        with patch("fetch_data._curl", side_effect=RuntimeError("HTTP 403")), \
             patch("fetch_data._fred_key", return_value="configured"), \
             patch("fetch_data.fetch_fred", return_value="observation_date,SERIES\n"):
            self.assertEqual(
                fetch_fred_graph("SERIES"),
                "observation_date,SERIES\n",
            )

    def test_input_reader_drops_nonpositive_values_before_log_transform(self):
        source = pd.DataFrame({
            "observation_date": ["2000-01-01", "2000-04-01", "2000-07-01", "2000-10-01"],
            "value": [0, 2.0, -1.0, 4.0],
        })
        with patch("engine.data.pd.read_csv", return_value=source):
            values = _read(SeriesSpec("unused.csv", "value", "Q", deflate=False))
        self.assertEqual(values.tolist(), [2.0, 4.0])


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.runsignup import RunSignupConnector


class RunSignupCountryTest(unittest.TestCase):
    def test_country_code_sent(self):
        captured = []

        def fake_http_get(_url, params):
            captured.append(params)
            return {"races": []}

        connector = RunSignupConnector(
            country_code="CA", start_date="2026-06-07", end_date="2026-09-05",
            http_get=fake_http_get, request_delay=0,
        )
        connector.fetch()
        self.assertEqual(captured[0]["country_code"], "CA")

    def test_regions_override_states(self):
        connector = RunSignupConnector(country_code="CA", regions=["ON", "QC"])
        self.assertEqual(connector.regions, ["ON", "QC"])

    def test_default_country_is_us(self):
        connector = RunSignupConnector(state="CA")
        self.assertEqual(connector.country_code, "US")
        self.assertEqual(connector.regions, ["CA"])  # compat: state -> regions


if __name__ == "__main__":
    unittest.main()

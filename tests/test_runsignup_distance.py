import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.runsignup import RunSignupConnector, _classify, _parse_distance


class RunSignupDistanceTest(unittest.TestCase):
    def test_kilometers(self):
        self.assertEqual(_parse_distance("5K"), 5)
        self.assertEqual(_parse_distance("10 km"), 10)

    def test_miles(self):
        self.assertEqual(_parse_distance("1M"), 1.609)
        self.assertEqual(_parse_distance("13.1M"), 21.082)
        self.assertEqual(_parse_distance("100 Miles"), 160.934)

    def test_meters(self):
        self.assertEqual(_parse_distance("200m"), 0.2)
        self.assertEqual(_parse_distance("400 meters"), 0.4)

    def test_yards(self):
        self.assertEqual(_parse_distance("100 yards"), 0.091)

    def test_named_distances(self):
        self.assertEqual(_parse_distance("Half Marathon"), 21.098)
        self.assertEqual(_parse_distance("Marathon"), 42.195)

    def test_unknown_distance(self):
        self.assertIsNone(_parse_distance(""))
        self.assertIsNone(_parse_distance(None))
        self.assertIsNone(_parse_distance("Kids Dash"))

    def test_api_request_asks_for_kilometers(self):
        captured = []

        def fake_http_get(_url, params):
            captured.append(params)
            return {"races": []}

        connector = RunSignupConnector(
            state="CA",
            start_date="2026-06-05",
            end_date="2026-09-03",
            http_get=fake_http_get,
            request_delay=0,
        )

        list(connector._paginate("CA"))

        self.assertEqual(captured[0]["distance_units"], "K")


class RunSignupTypeTest(unittest.TestCase):
    def test_road_running_types_are_route(self):
        self.assertEqual(_classify("running_race", "City 10K", "10K"), "route")
        self.assertEqual(_classify("running_only", "Downtown Run", "5K"), "route")

    def test_trail_event_types_are_trail(self):
        self.assertEqual(_classify("trail_race", "Forest Race", "10K"), "trail")
        self.assertEqual(_classify("open_course_trail", "Open Trail", "Half"), "trail")
        self.assertEqual(_classify("ultra", "Mountain Ultra", "50K"), "trail")

    def test_road_type_with_trail_name_is_trail_fallback(self):
        self.assertEqual(_classify("running_race", "Canyon Trail Run", "20K"), "trail")

    def test_non_running_types_are_other(self):
        self.assertEqual(_classify("walking_only", "Community Walk", "5K"), "other")
        self.assertEqual(_classify("triathlon", "Tri Race", "Sprint"), "other")
        self.assertEqual(_classify("bike_race", "Bike Race", "20K"), "other")


if __name__ == "__main__":
    unittest.main()

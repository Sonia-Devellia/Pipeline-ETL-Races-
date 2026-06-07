import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.athlinks import (
    AthlinksConnector, _classify, _distance_km, _race_date, _iso_to_us,
)


_FAKE_RACE = {
    "raceID": 555,
    "raceName": "Alpine Trail Festival",
    "city": "Chamonix",
    "country": "FR",
    "raceCatName": "Running",
    "startDate": "2026-07-15T08:00:00",
    "courses": [
        {"courseID": 1, "courseName": "21 km", "distanceInMeters": 21097},
        {"courseID": 2, "courseName": "Kids 800m", "distanceInMeters": 800},
    ],
}


class AthlinksHelpersTest(unittest.TestCase):
    def test_distance_meters(self):
        self.assertEqual(_distance_km({"distanceInMeters": 10000}), 10.0)

    def test_distance_miles(self):
        self.assertEqual(_distance_km({"distance": "10", "distanceUnit": "mi"}), 16.093)

    def test_race_date_iso(self):
        self.assertEqual(_race_date({"startDate": "2026-07-15T08:00:00"}), "2026-07-15")

    def test_race_date_epoch_ms(self):
        # 2026-07-15 00:00:00 UTC en millisecondes
        self.assertEqual(_race_date({"startEpoch": 1784073600000}), "2026-07-15")

    def test_iso_to_us(self):
        self.assertEqual(_iso_to_us("2026-07-15"), "07/15/26")

    def test_classify(self):
        self.assertEqual(_classify("Running", "City 10K", "10 km"), "route")
        self.assertEqual(_classify("Running", "Alpine Trail", "21 km"), "trail")
        self.assertEqual(_classify("Triathlon", "Ironman", "Half"), "other")


class AthlinksFetchTest(unittest.TestCase):
    def test_fetch_maps_courses_and_filters(self):
        calls = {"n": 0}

        def fake_http_get(url, params):
            calls["n"] += 1
            return [_FAKE_RACE] if calls["n"] == 1 else []

        connector = AthlinksConnector(
            country="FR", start_date="2026-06-07", end_date="2026-09-05",
            results_per_page=1, request_delay=0,
            http_get=fake_http_get,
            min_distance_km=5, keep_types={"route", "trail"},
        )
        races = connector.fetch()

        # Le 21 km est gardé (trail) ; le 800 m est filtré (< 5 km).
        self.assertEqual(len(races), 1)
        r = races[0]
        self.assertEqual(r.source, "athlinks")
        self.assertEqual(r.external_id, "555:1")
        self.assertEqual(r.pays, "FR")
        self.assertEqual(r.ville, "Chamonix")
        self.assertEqual(r.date, "2026-07-15")
        self.assertEqual(r.distance_km, 21.097)
        self.assertEqual(r.type, "trail")

    def test_params_include_country_and_dates(self):
        captured = []

        def fake_http_get(url, params):
            captured.append(params)
            return []

        AthlinksConnector(
            country="US", start_date="2026-06-07", end_date="2026-09-05",
            http_get=fake_http_get, request_delay=0,
        ).fetch()
        self.assertEqual(captured[0]["Country"], "US")
        self.assertEqual(captured[0]["StartDate"], "06/07/26")
        self.assertEqual(captured[0]["EndDate"], "09/05/26")

    def test_payload_object_with_results_key(self):
        def fake_http_get(url, params):
            if params["PageNumber"] == 1:
                return {"results": [_FAKE_RACE]}
            return {"results": []}

        races = AthlinksConnector(
            results_per_page=1, request_delay=0, http_get=fake_http_get,
        ).fetch()
        self.assertEqual(len(races), 2)  # 2 courses, aucun filtre


if __name__ == "__main__":
    unittest.main()

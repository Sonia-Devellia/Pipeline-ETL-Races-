import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.raceroster import RaceRosterConnector, _classify, _distance_km


# Une page d'événements factice imitant la réponse GET /v1/events.
_FAKE_EVENT = {
    "eventId": "abc123",
    "name": "London Trail Series",
    "city": "London",
    "country": {"code": "CA", "name": "Canada"},
    "startDate": "2026-07-01T09:00:00+00:00",
    "subEvents": {"data": [
        {"subEventId": 1, "name": "10 km",
         "subEventDistance": {"type": "running", "inMeters": "10000"}},
        {"subEventId": 2, "name": "Swim",
         "subEventDistance": {"type": "swimming", "inMeters": "1500"}},
    ]},
}


class RaceRosterDistanceTest(unittest.TestCase):
    def test_in_meters_is_used(self):
        sub = {"subEventDistance": {"inMeters": "21097"}}
        self.assertEqual(_distance_km(sub), 21.097)

    def test_fallback_miles(self):
        sub = {"distance": "10", "distanceType": "mi"}
        self.assertEqual(_distance_km(sub), 16.093)

    def test_empty(self):
        self.assertIsNone(_distance_km({}))


class RaceRosterTypeTest(unittest.TestCase):
    def test_running_is_route(self):
        self.assertEqual(_classify("running", "City 10K", "10 km"), "route")

    def test_running_with_trail_name_is_trail(self):
        self.assertEqual(_classify("running", "Mountain Trail", "21 km"), "trail")

    def test_non_running_is_other(self):
        self.assertEqual(_classify("swimming", "Open Water", "1500 m"), "other")
        self.assertEqual(_classify("cycling", "Gran Fondo", "100 km"), "other")


class RaceRosterFetchTest(unittest.TestCase):
    def test_fetch_maps_subevents_and_filters(self):
        calls = {"events": 0}

        def fake_token():
            return "fake-token"

        def fake_http_get(url, params, token):
            # 1re page : l'événement ; pages suivantes : vide (fin).
            calls["events"] += 1
            return {"data": [_FAKE_EVENT]} if calls["events"] == 1 else {"data": []}

        connector = RaceRosterConnector(
            start_date="2026-06-07", end_date="2026-09-05",
            results_per_page=1, request_delay=0,
            token_get=fake_token, http_get=fake_http_get,
            min_distance_km=5, keep_types={"route", "trail"},
        )
        races = connector.fetch()

        # Le 10 km running est gardé ; la natation (other) est filtrée.
        self.assertEqual(len(races), 1)
        r = races[0]
        self.assertEqual(r.source, "raceroster")
        self.assertEqual(r.external_id, "abc123:1")
        self.assertEqual(r.pays, "CA")
        self.assertEqual(r.ville, "London")
        self.assertEqual(r.date, "2026-07-01")
        self.assertEqual(r.distance_km, 10.0)
        self.assertEqual(r.type, "trail")   # "Trail" dans le nom de l'event
        self.assertEqual(r.devise, "CAD")

    def test_date_filters_passed_to_api(self):
        captured = []

        def fake_http_get(url, params, token):
            captured.append(params)
            return {"data": []}

        connector = RaceRosterConnector(
            start_date="2026-06-07", end_date="2026-09-05",
            token_get=lambda: "t", http_get=fake_http_get, request_delay=0,
        )
        connector.fetch()
        self.assertEqual(captured[0]["eventDateFrom"], "2026-06-07T00:00:00Z")
        self.assertEqual(captured[0]["eventDateTo"], "2026-09-05T23:59:59Z")


if __name__ == "__main__":
    unittest.main()

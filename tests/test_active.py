import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.active import ActiveConnector, _classify, _distances


# Extrait simplifié d'une réponse réelle de l'API ACTIVE v2.
_FAKE_ASSET = {
    "assetGuid": "7e6cb77e",
    "assetName": "RunForTheHungry",
    "activityStartDate": "2026-07-15T07:00:00",
    "registrationUrlAdr": "https://www.active.com/register?EVENT_ID=1",
    "place": {"cityName": "Toronto", "countryCode": "", "countryName": "Canada"},
    "assetTopics": [
        {"topic": {"topicName": "Running", "topicTaxonomy": "Endurance/Running"}}
    ],
    "assetAttributes": [
        {"attribute": {"attributeValue": "5K", "attributeType": "Distance (running)"}},
        {"attribute": {"attributeValue": "10K", "attributeType": "Distance (running)"}},
        {"attribute": {"attributeValue": "Beginner", "attributeType": "Skill level"}},
    ],
    "assetTags": [
        {"tag": {"tagName": "10K", "tagDescription": "Distance (running)"}},  # doublon
    ],
}


class ActiveHelpersTest(unittest.TestCase):
    def test_distances_dedup(self):
        d = dict(_distances(_FAKE_ASSET))
        self.assertEqual(d, {"5K": 5.0, "10K": 10.0})

    def test_classify_running(self):
        self.assertEqual(_classify(_FAKE_ASSET, "City 10K"), "route")

    def test_classify_trail(self):
        self.assertEqual(_classify(_FAKE_ASSET, "Mountain Trail Run"), "trail")

    def test_classify_other(self):
        cycling = {"assetTopics": [
            {"topic": {"topicName": "Cycling", "topicTaxonomy": "Endurance/Cycling"}}]}
        self.assertEqual(_classify(cycling, "Gran Fondo"), "other")


class ActiveFetchTest(unittest.TestCase):
    def test_fetch_one_row_per_distance_and_country_fallback(self):
        calls = {"n": 0}

        def fake_http_get(url, params):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"total_results": 1, "results": [_FAKE_ASSET]}
            return {"total_results": 1, "results": []}

        races = ActiveConnector(
            country="CA", start_date="2026-06-07", end_date="2026-09-05",
            results_per_page=50, request_delay=0, http_get=fake_http_get,
            min_distance_km=5, keep_types={"route", "trail"},
        ).fetch()

        # 5K et 10K → deux lignes ; tous >= 5 km, type route.
        self.assertEqual(len(races), 2)
        ids = sorted(r.external_id for r in races)
        self.assertEqual(ids, ["7e6cb77e:10K", "7e6cb77e:5K"])
        r = races[0]
        self.assertEqual(r.source, "active")
        self.assertEqual(r.ville, "Toronto")
        self.assertEqual(r.pays, "CA")          # fallback (countryCode vide)
        self.assertEqual(r.date, "2026-07-15")
        self.assertTrue(r.nom.startswith("RunForTheHungry – "))
        self.assertEqual(r.url, "https://www.active.com/register?EVENT_ID=1")

    def test_unknown_distance_is_kept(self):
        # Asset course à pied SANS distance (comme l'ultra de Nice).
        asset = {
            "assetGuid": "nodist",
            "assetName": "Ultra-Trail Sans Distance",
            "activityStartDate": "2026-07-03T07:00:00",
            "place": {"cityName": "Nice", "countryCode": "FRA"},
            "assetTopics": [
                {"topic": {"topicName": "Running", "topicTaxonomy": "Endurance/Running"}}],
        }

        def fake_http_get(url, params):
            return ({"total_results": 1, "results": [asset]}
                    if params["current_page"] == 1 else {"results": []})

        races = ActiveConnector(
            results_per_page=50, request_delay=0, http_get=fake_http_get,
            min_distance_km=5, keep_types={"route", "trail"},
        ).fetch()
        self.assertEqual(len(races), 1)
        self.assertIsNone(races[0].distance_km)
        self.assertEqual(races[0].type, "trail")

    def test_params_country_and_date_range(self):
        captured = []

        def fake_http_get(url, params):
            captured.append(params)
            return {"total_results": 0, "results": []}

        ActiveConnector(
            country="AU", start_date="2026-06-07", end_date="2026-09-05",
            http_get=fake_http_get, request_delay=0,
        ).fetch()
        # Le code "AU" est converti en nom complet attendu par ACTIVE.
        self.assertEqual(captured[0]["country"], "Australia")
        self.assertEqual(captured[0]["start_date"], "2026-06-07..2026-09-05")
        self.assertEqual(captured[0]["topic"], "Running")

    def test_country_code_is_converted_to_name(self):
        from connectors.active import _country_name
        self.assertEqual(_country_name("CA"), "Canada")
        self.assertEqual(_country_name("Canada"), "Canada")
        self.assertEqual(_country_name("FR"), "France")


if __name__ == "__main__":
    unittest.main()

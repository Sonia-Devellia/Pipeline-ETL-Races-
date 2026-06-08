"""
Connecteur Race Roster — API REST OAuth2 (US + Canada).

⚠️ IMPORTANT — portée de cette API :
L'endpoint GET /v1/events de Race Roster est *authentifié* (OAuth2) et renvoie
uniquement les événements auxquels le compte connecté a accès (statut LIVE/PRIVATE
et date future). Ce n'est donc PAS un catalogue mondial public comme RunSignup :
il est pensé pour qu'un organisateur / chronométreur gère SES événements, ou via
un partenariat de données avec Race Roster.

Identifiants à créer ici : https://raceroster.com/dashboard/account/api-settings
Renseigner ensuite dans .env :
    RACEROSTER_CLIENT_ID, RACEROSTER_CLIENT_SECRET,
    RACEROSTER_USERNAME, RACEROSTER_PASSWORD
"""

import json
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional

from connectors.base import Connector
from core.model import Race

TOKEN_URL = "https://raceroster.com/api/oauth/authorize"
EVENTS_URL = "https://raceroster.com/api/v1/events"

# Devise par défaut selon le pays (l'endpoint /events ne renvoie pas la devise).
_COUNTRY_CURRENCY = {
    "US": "USD", "CA": "CAD", "AU": "AUD", "GB": "GBP", "MX": "MXN",
    "NL": "EUR", "NO": "NOK", "DK": "DKK", "SE": "SEK",
}

_TRAIL_KW = ("trail", "ultra", "sky", "mountain", "montagne", "sentier")

TokenGet = Callable[[], str]
HttpGet = Callable[[str, dict, str], dict]


# ── HTTP en direct (remplaçables pour les tests) ──────────────────────────

def live_token_factory(client_id, client_secret, username, password) -> TokenGet:
    def _get_token() -> str:
        body = urllib.parse.urlencode({
            "grant_type": "access_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
        }).encode("utf-8")
        req = urllib.request.Request(
            TOKEN_URL, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": "kotcha-races-poc/0.1"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data = payload.get("data", payload)
        if isinstance(data, list):
            data = data[0]
        return data["access_token"]

    return _get_token


def live_http_get(url: str, params: dict, token: str) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"Authorization": f"Bearer {token}",
                 "User-Agent": "kotcha-races-poc/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Connecteur ────────────────────────────────────────────────────────────

class RaceRosterConnector(Connector):
    source = "raceroster"

    def __init__(self, client_id=None, client_secret=None,
                 username=None, password=None,
                 start_date=None, end_date=None,
                 results_per_page=50, request_delay=0.5,
                 token_get: Optional[TokenGet] = None,
                 http_get: HttpGet = live_http_get,
                 min_distance_km=None, keep_types=None):
        self.start_date = start_date
        self.end_date = end_date
        self.rpp = results_per_page
        self.delay = request_delay
        self.http_get = http_get
        self.token_get = token_get or live_token_factory(
            client_id, client_secret, username, password)
        self.min_km = min_distance_km
        self.keep_types = keep_types

    def fetch(self) -> list[Race]:
        token = self.token_get()
        races, seen = [], set()
        for raw in self._paginate(token):
            for race in self._to_models(raw):
                if race.external_id in seen:
                    continue
                if self.min_km and (race.distance_km is None
                                    or race.distance_km < self.min_km):
                    continue
                if self.keep_types and race.type not in self.keep_types:
                    continue
                seen.add(race.external_id)
                races.append(race)
        return races

    # ── Pagination (offset / limit) ──

    def _paginate(self, token):
        offset = 0
        while True:
            params = {"offset": offset, "limit": self.rpp,
                      "sort": "startDate", "order": "asc"}
            if self.start_date:
                params["eventDateFrom"] = f"{self.start_date}T00:00:00Z"
            if self.end_date:
                params["eventDateTo"] = f"{self.end_date}T23:59:59Z"

            batch = (self.http_get(EVENTS_URL, params, token) or {}).get("data", []) or []
            if not batch:
                break
            for event in batch:
                yield event
            if len(batch) < self.rpp:
                break
            offset += self.rpp
            time.sleep(self.delay)

    # ── Traduction vers Race (format pivot) ──

    def _to_models(self, event: dict) -> list[Race]:
        country = (event.get("country") or {}).get("code")
        city = event.get("city")
        event_name = event.get("name") or ""
        event_url = event.get("url")
        event_date = (event.get("startDate") or "")[:10] or None
        devise = _COUNTRY_CURRENCY.get((country or "").upper())

        out = []
        for sub in (event.get("subEvents") or {}).get("data") or []:
            sid = sub.get("subEventId")
            if sid is None:
                continue
            sub_dist = sub.get("subEventDistance") or {}
            sub_name = sub.get("name") or ""
            nom = (event_name if not sub_name or sub_name == event_name
                   else f"{event_name} – {sub_name}")
            out.append(Race(
                source=self.source,
                external_id=f"{event.get('eventId')}:{sid}",
                date=event_date,
                pays=country,
                ville=city,
                distance_km=_distance_km(sub),
                type=_classify(sub_dist.get("type"), event_name, sub_name),
                prix=None,                # non fourni par /v1/events
                devise=devise,
                nom=nom or None,
                url=event_url,
            ))
        return out


# ── Helpers de normalisation ────────────────────────────────────────────

def _distance_km(sub: dict) -> Optional[float]:
    """Privilégie inMeters (fiable), sinon distance + distanceType."""
    sub_dist = sub.get("subEventDistance") or {}
    meters = sub_dist.get("inMeters")
    if meters:
        try:
            return round(float(meters) / 1000, 3)
        except (TypeError, ValueError):
            pass

    val = sub.get("distance")
    unit = (sub.get("distanceType") or "").lower()
    if not val:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if unit in {"km", "k"}:
        return num
    if unit in {"mi", "mile", "miles"}:
        return round(num * 1.609344, 3)
    if unit in {"m", "meter", "meters"}:
        return round(num / 1000, 3)
    return num


def _classify(sport_type: Optional[str], *names: str) -> str:
    """Seul le 'running' devient route/trail ; le reste est 'other'."""
    if (sport_type or "").lower() != "running":
        return "other"
    blob = " ".join(n.lower() for n in names if n)
    if any(kw in blob for kw in _TRAIL_KW):
        return "trail"
    return "route"

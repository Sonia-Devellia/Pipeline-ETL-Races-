"""
Connecteur RunSignup — API REST publique (sans clé).

Récupère les courses depuis https://runsignup.com/rest/races,
gère la pagination, le rate limiting et normalise les données
vers le format pivot Race.
"""

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable, Optional

from connectors.base import Connector
from core.model import Race

API_URL = "https://api.runsignup.com/rest/races"
MILES_TO_KM = 1.609344
YARDS_TO_KM = 0.0009144

# event_type RunSignup utiles pour notre pivot route/trail.
_ROAD_RUNNING_TYPES = {"running_race", "running_only"}
_TRAIL_RUNNING_TYPES = {"trail_race", "open_course_trail", "ultra"}

# 50 États US + DC.
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
]

# 10 provinces + 3 territoires canadiens.
# L'API RunSignup requiert country_code=CA + state=<province> pour filtrer
# correctement : sans province, elle renvoie des résultats hors Canada.
CA_PROVINCES = [
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU",
    "ON", "PE", "QC", "SK", "YT",
]

HttpGet = Callable[[str, dict], dict]


# ── HTTP ────────────────────────────────────────────────────────────────

def live_http_get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "kotcha-races-poc/0.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cache_http_get_factory(cache_dir: str) -> HttpGet:
    """Lit les pages depuis des fichiers JSON locaux au lieu du réseau."""
    import os

    def _get(url: str, params: dict) -> dict:
        page = params.get("page", 1)
        path = os.path.join(cache_dir, f"page_{page}.json")
        if not os.path.exists(path):
            return {"races": []}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    return _get


# ── Connecteur ──────────────────────────────────────────────────────────

class RunSignupConnector(Connector):
    source = "runsignup"

    def __init__(self, state=None, states=None, country_code="US",
                 regions=None, start_date=None, end_date=None,
                 results_per_page=50, request_delay=0.5,
                 http_get=live_http_get, min_distance_km=None,
                 keep_types=None):
        self.country_code = country_code
        # "regions" = subdivisions (états US, provinces CA…).
        # Compat ascendante : on accepte encore states= / state=.
        if regions is not None:
            self.regions = list(regions) if regions else [None]
        elif states:
            self.regions = list(states)
        elif state:
            self.regions = [state]
        else:
            self.regions = [None]
        self.states = self.regions  # alias rétro-compat
        self.start_date = start_date
        self.end_date = end_date
        self.rpp = results_per_page
        self.delay = request_delay
        self.http_get = http_get
        self.min_km = min_distance_km
        self.keep_types = keep_types

    def fetch(self) -> list[Race]:
        races, seen = [], set()
        for i, region in enumerate(self.regions):
            if i > 0:
                time.sleep(self.delay)
            for raw in self._paginate(region):
                for race in self._to_models(raw):
                    if race.external_id in seen:
                        continue
                    if (self.min_km and race.distance_km is not None
                            and race.distance_km < self.min_km):
                        continue  # on garde les distances inconnues (None)
                    if self.keep_types and race.type not in self.keep_types:
                        continue
                    seen.add(race.external_id)
                    races.append(race)
        return races

    # ── Pagination ──

    def _paginate(self, region=None):
        page = 1
        while True:
            params = {"format": "json", "events": "T", "distance_units": "K",
                      "results_per_page": self.rpp, "page": page}
            if self.country_code:
                params["country_code"] = self.country_code
            if region:
                params["state"] = region
            if self.start_date:
                params["start_date"] = self.start_date
            if self.end_date:
                params["end_date"] = self.end_date

            batch = self.http_get(API_URL, params).get("races", []) or []
            if not batch:
                break
            for item in batch:
                yield item.get("race", item)
            if len(batch) < self.rpp:
                break
            page += 1
            time.sleep(self.delay)

    # ── Traduction vers Race (format pivot) ──

    def _to_models(self, race: dict) -> list[Race]:
        addr = race.get("address") or {}
        name = race.get("name") or ""
        url = race.get("url")
        race_date = _date_us_to_iso(race.get("next_date"))

        out = []
        for ev in race.get("events") or []:
            eid = ev.get("event_id")
            if eid is None:
                continue
            ev_name = ev.get("name") or ""
            nom = name if not ev_name or ev_name == name else f"{name} – {ev_name}"
            out.append(Race(
                source=self.source,
                external_id=str(eid),
                date=_datetime_us_to_iso(ev.get("start_time")) or race_date,
                pays=addr.get("country_code"),
                ville=addr.get("city"),
                distance_km=_parse_distance(ev.get("distance")),
                type=_classify(ev.get("event_type"), name, ev_name),
                prix=_parse_fee(ev.get("registration_periods")),
                devise="USD",
                nom=nom or None,
                url=url,
            ))
        return out


# ── Helpers de normalisation ────────────────────────────────────────────

def _date_us_to_iso(val: Optional[str]) -> Optional[str]:
    """'MM/DD/YYYY' → 'YYYY-MM-DD'."""
    if not val:
        return None
    try:
        return datetime.strptime(val.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def _datetime_us_to_iso(val: Optional[str]) -> Optional[str]:
    """'M/D/YYYY HH:MM' → 'YYYY-MM-DD'."""
    if not val:
        return None
    try:
        return datetime.strptime(val.strip(), "%m/%d/%Y %H:%M").date().isoformat()
    except ValueError:
        return None


def _parse_distance(val: Optional[str]) -> Optional[float]:
    """Convertit les distances RunSignup en km.

    Exemples : '5K' -> 5, '1M' -> 1.609, '100 Miles' -> 160.934,
    '200m' -> 0.2, 'Half Marathon' -> 21.098.
    """
    if not val:
        return None
    raw = val.strip()
    s = raw.lower()

    if "half marathon" in s:
        return 21.098
    if "marathon" in s:
        return 42.195

    m = re.search(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?", raw)
    if not m:
        return None
    num = float(m.group(1))
    unit_raw = m.group(2) or ""
    unit = unit_raw.lower()

    if unit in {"k", "km", "kms", "kilometer", "kilometers", "kilometre", "kilometres"}:
        return num
    if unit in {"mi", "mile", "miles"}:
        return round(num * MILES_TO_KM, 3)
    if unit in {"meter", "meters", "metre", "metres"}:
        return round(num / 1000, 3)
    if unit in {"y", "yd", "yds", "yard", "yards"}:
        return round(num * YARDS_TO_KM, 3)
    if unit == "m":
        # RunSignup peut fournir "1M" pour miles, tandis que "200m" désigne
        # généralement des mètres. Les distances >= 100 sont traitées en mètres.
        if num >= 100:
            return round(num / 1000, 3)
        return round(num * MILES_TO_KM, 3)

    return num


def _classify(event_type: Optional[str], race_name: str, event_name: str) -> str:
    """Déduit 'route' | 'trail' | 'other' depuis event_type, avec secours par nom."""
    et = (event_type or "").lower()
    if et in _TRAIL_RUNNING_TYPES:
        return "trail"
    if et not in _ROAD_RUNNING_TYPES:
        return "other"

    blob = f"{race_name} {event_name}".lower()
    if "trail" in blob or "ultra" in blob:
        return "trail"
    return "route"


def _parse_fee(periods: Optional[list]) -> Optional[float]:
    """Retourne le prix du palier actif, sinon le tarif de base."""
    if not periods:
        return None

    def money(txt):
        if not txt:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)", txt.replace(",", ""))
        return float(m.group(1)) if m else None

    def dt(txt):
        if not txt:
            return None
        try:
            return datetime.strptime(txt.strip(), "%m/%d/%Y %H:%M")
        except ValueError:
            return None

    now = datetime.now()
    for p in periods:
        opens, closes = dt(p.get("registration_opens")), dt(p.get("registration_closes"))
        if opens and closes and opens <= now <= closes:
            fee = money(p.get("race_fee"))
            if fee is not None:
                return fee

    return money(periods[0].get("race_fee"))

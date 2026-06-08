"""
Connecteur Athlinks — API REST (couverture internationale).

⚠️ Clé d'accès requise : inscription sur https://athlinks.3scale.net/signup
La clé est passée en paramètre de requête (par défaut "apikey" ; certains comptes
3scale utilisent "user_key" — réglable via auth_param).

Endpoint utilisé : races/search
  races/search/?term={term}&Country={c}&StartDate=mm/dd/yy&EndDate=mm/dd/yy
                &PageNumber={n}&PageSize={n}&SortBy=date

⚠️ Forme JSON à valider : Athlinks documente le *modèle* (un Race contient un ou
plusieurs Courses) mais pas le détail des champs. Le mapping ci-dessous est
défensif (essaie plusieurs noms de champs). Une fois une vraie clé en main,
il suffira d'ajuster `_to_models` / les helpers — le reste du connecteur ne bouge pas.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable, Optional

from connectors.base import Connector
from core.model import Race

SEARCH_URL = "https://api.athlinks.com/races/search"

_TRAIL_KW = ("trail", "ultra", "sky", "mountain", "montagne", "sentier")

HttpGet = Callable[[str, dict], dict]


# ── HTTP en direct (remplaçable pour les tests) ──────────────────────────

def live_http_get_factory(api_key: str, auth_param: str = "apikey") -> HttpGet:
    def _get(url: str, params: dict) -> dict:
        q = dict(params)
        q[auth_param] = api_key
        q["format"] = "json"
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(q)}",
            headers={"User-Agent": "kotcha-races-poc/0.1",
                     "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return _get


# ── Connecteur ────────────────────────────────────────────────────────────

class AthlinksConnector(Connector):
    source = "athlinks"

    def __init__(self, api_key=None, auth_param="apikey",
                 term="", country=None, start_date=None, end_date=None,
                 results_per_page=25, request_delay=0.5,
                 http_get: Optional[HttpGet] = None,
                 min_distance_km=None, keep_types=None):
        self.term = term
        self.country = country
        self.start_date = start_date
        self.end_date = end_date
        self.rpp = results_per_page
        self.delay = request_delay
        self.http_get = http_get or live_http_get_factory(api_key, auth_param)
        self.min_km = min_distance_km
        self.keep_types = keep_types

    def fetch(self) -> list[Race]:
        races, seen = [], set()
        for raw in self._paginate():
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

    # ── Pagination (PageNumber / PageSize) ──

    def _paginate(self):
        page = 1
        while True:
            params = {"term": self.term, "PageNumber": page,
                      "PageSize": self.rpp, "SortBy": "date"}
            if self.country:
                params["Country"] = self.country
            if self.start_date:
                params["StartDate"] = _iso_to_us(self.start_date)
            if self.end_date:
                params["EndDate"] = _iso_to_us(self.end_date)

            batch = _extract_races(self.http_get(SEARCH_URL, params))
            if not batch:
                break
            for item in batch:
                yield item
            if len(batch) < self.rpp:
                break
            page += 1
            time.sleep(self.delay)

    # ── Traduction vers Race (format pivot) ──

    def _to_models(self, race: dict) -> list[Race]:
        rid = _first(race, "raceID", "RaceID", "raceId", "id")
        if rid is None:
            return []
        name = _first(race, "raceName", "RaceName", "name", default="") or ""
        url = _first(race, "url", "raceUrl", "eventUrl", "logoUrl")
        date = _race_date(race)
        country = _first(race, "country", "countryID", "Country", "countryCode")
        city = _first(race, "city", "City")
        cat = _first(race, "raceCatName", "category", "raceCategory", default="") or ""

        courses = (_first(race, "courses", "Courses") or [])
        if not courses:
            # Pas de course détaillée : on émet quand même la course "mère".
            return [Race(
                source=self.source, external_id=str(rid), date=date,
                pays=_country_code(country), ville=city,
                distance_km=None,
                type=_classify(cat, name),
                prix=None, devise=None,
                nom=name or None, url=url,
            )]

        out = []
        for c in courses:
            cid = _first(c, "courseID", "CourseID", "courseId", "id")
            cname = _first(c, "courseName", "name", default="") or ""
            nom = name if not cname or cname == name else f"{name} – {cname}"
            out.append(Race(
                source=self.source,
                external_id=f"{rid}:{cid}" if cid is not None else str(rid),
                date=_race_date(c) or date,
                pays=_country_code(country),
                ville=city,
                distance_km=_distance_km(c),
                type=_classify(cat, name, cname),
                prix=None,
                devise=None,
                nom=nom or None,
                url=url,
            ))
        return out


# ── Helpers ───────────────────────────────────────────────────────────────

def _first(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def _extract_races(payload) -> list:
    """Le payload peut être une liste, ou un objet avec results/races/data."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "races", "Races", "data", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return val
    return []


def _iso_to_us(val: str) -> str:
    """'YYYY-MM-DD' → 'mm/dd/yy' (format attendu par Athlinks)."""
    try:
        return datetime.strptime(val, "%Y-%m-%d").strftime("%m/%d/%y")
    except (TypeError, ValueError):
        return val


def _race_date(d: dict) -> Optional[str]:
    """Renvoie une date ISO YYYY-MM-DD depuis divers formats Athlinks."""
    epoch = _first(d, "startEpoch", "raceDate", "dateEpoch", "startTime")
    if isinstance(epoch, (int, float)):
        ms = epoch / 1000 if epoch > 1e11 else epoch
        try:
            return datetime.utcfromtimestamp(ms).date().isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    txt = _first(d, "startDate", "date", "raceDate")
    if isinstance(txt, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(txt[:19], fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _distance_km(course: dict) -> Optional[float]:
    """Distance d'une course → km. Athlinks fournit souvent des mètres."""
    meters = _first(course, "distanceInMeters", "distance_m", "meters")
    if meters is not None:
        try:
            return round(float(meters) / 1000, 3)
        except (TypeError, ValueError):
            pass
    val = _first(course, "distance", "courseDistance")
    unit = (_first(course, "distanceUnit", "unit", default="") or "").lower()
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if unit in {"mi", "mile", "miles"}:
        return round(num * 1.609344, 3)
    if unit in {"m", "meter", "meters"}:
        return round(num / 1000, 3)
    if unit in {"km", "k", "", "kilometer", "kilometers"}:
        # Sans unité, on suppose des mètres si la valeur est grande.
        if not unit and num >= 1000:
            return round(num / 1000, 3)
        return num
    return num


def _country_code(country) -> Optional[str]:
    """Garde un code court si possible (ex. 'US'), sinon None."""
    if isinstance(country, str) and country:
        return country.upper()[:8]
    return None


def _classify(category: str, *names: str) -> str:
    """Course à pied → route/trail ; le reste → other."""
    cat = (category or "").lower()
    blob = " ".join(n.lower() for n in names if n)
    is_run = ("run" in cat or "marathon" in cat) or not cat
    # Si une catégorie non-running est explicite, on exclut.
    if cat and any(x in cat for x in ("tri", "bike", "cycl", "swim", "duathlon")):
        return "other"
    if not is_run:
        return "other"
    if any(kw in blob for kw in _TRAIL_KW):
        return "trail"
    return "route"

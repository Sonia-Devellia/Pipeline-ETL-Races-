"""
Connecteur ACTIVE Network — Activity Search API v2.

API ouverte, en lecture seule, SANS OAuth. Clé gratuite sur simple inscription :
https://developer.active.com/member/register  (quota : 500 000 appels/jour)

Endpoint : http://api.amp.active.com/v2/search?{params}&api_key={key}
Couverture : très forte US/Canada, correcte Australie, faible France/Europe.

Le format pivot ne distinguant pas les sous-distances, on émet une ligne Race
par distance trouvée sur l'événement (ex. un 5K et un 10K = deux lignes).
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from connectors.base import Connector
from connectors.runsignup import _parse_distance  # réutilise "5K"/"Marathon"→km
from core.model import Race

SEARCH_URL = "http://api.amp.active.com/v2/search"

_TRAIL_KW = ("trail", "ultra", "sky", "mountain", "montagne", "sentier")

# ACTIVE filtre par NOM de pays, pas par code. On convertit les codes courants
# pour pouvoir écrire indifféremment "CA" ou "Canada".
_COUNTRY_NAMES = {
    "US": "United States", "USA": "United States",
    "CA": "Canada", "AU": "Australia", "NZ": "New Zealand",
    "FR": "France", "GB": "United Kingdom", "UK": "United Kingdom",
    "DE": "Germany", "ES": "Spain", "IT": "Italy", "BE": "Belgium",
    "CH": "Switzerland", "NL": "Netherlands", "IE": "Ireland",
    "PT": "Portugal", "AT": "Austria", "SE": "Sweden", "NO": "Norway",
}

# ACTIVE renvoie des codes ISO 3 lettres (ex. "CAN") — on normalise en ISO 2.
_ISO3_TO_ISO2 = {
    "CAN": "CA", "USA": "US", "AUS": "AU", "NZL": "NZ", "GBR": "GB",
    "FRA": "FR", "DEU": "DE", "ESP": "ES", "ITA": "IT", "BEL": "BE",
    "CHE": "CH", "NLD": "NL", "IRL": "IE", "PRT": "PT", "AUT": "AT",
    "SWE": "SE", "NOR": "NO",
}


def _country_name(value):
    """Convertit un code pays en nom complet attendu par ACTIVE ('CA' → 'Canada')."""
    if not value:
        return None
    key = str(value).strip().upper()
    return _COUNTRY_NAMES.get(key, value)

HttpGet = Callable[[str, dict], dict]


# ── HTTP en direct (remplaçable pour les tests) ──────────────────────────

def live_http_get_factory(api_key: str) -> HttpGet:
    def _get(url: str, params: dict) -> dict:
        q = dict(params)
        q["api_key"] = api_key
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(q)}",
            headers={
                # UA navigateur : certaines passerelles bloquent les UA "script".
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0 Safari/537.36"),
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Remonte le message du serveur (Mashery) pour diagnostic.
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            raise RuntimeError(
                f"ACTIVE HTTP {exc.code} {exc.reason} — {body}"
            ) from None

    return _get


# ── Connecteur ────────────────────────────────────────────────────────────

class ActiveConnector(Connector):
    source = "active"

    def __init__(self, api_key=None, country=None, query="", topic="Running",
                 start_date=None, end_date=None,
                 results_per_page=50, request_delay=0.5,
                 http_get: Optional[HttpGet] = None,
                 min_distance_km=None, keep_types=None):
        self.country = _country_name(country)            # nom complet pour l'API
        # Code court conservé pour remplir "pays" si l'asset n'a pas de countryCode.
        self.country_fallback = (str(country).strip().upper()[:8] if country else None)
        self.query = query
        self.topic = topic
        self.start_date = start_date
        self.end_date = end_date
        self.rpp = results_per_page
        self.delay = request_delay
        self.http_get = http_get or live_http_get_factory(api_key)
        self.min_km = min_distance_km
        self.keep_types = keep_types

    def fetch(self) -> list[Race]:
        races, seen = [], set()
        for raw in self._paginate():
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

    # ── Pagination (current_page / per_page) ──

    def _paginate(self):
        page = 1
        while True:
            params = {"category": "event", "per_page": self.rpp,
                      "current_page": page, "sort": "date_asc",
                      "exclude_children": "true"}
            if self.topic:
                params["topic"] = self.topic
            if self.query:
                params["query"] = self.query
            if self.country:
                params["country"] = self.country
            if self.start_date or self.end_date:
                params["start_date"] = f"{self.start_date or ''}..{self.end_date or ''}"

            payload = self.http_get(SEARCH_URL, params) or {}
            batch = payload.get("results") or []
            if not batch:
                break
            for item in batch:
                yield item
            total = int(payload.get("total_results") or 0)
            if len(batch) < self.rpp or page * self.rpp >= total:
                break
            page += 1
            time.sleep(self.delay)

    # ── Traduction vers Race (format pivot) ──

    def _to_models(self, asset: dict) -> list[Race]:
        guid = asset.get("assetGuid")
        if not guid:
            return []
        name = asset.get("assetName") or ""
        date = (asset.get("activityStartDate") or "")[:10] or None
        url = (asset.get("registrationUrlAdr") or asset.get("homePageUrlAdr")
               or asset.get("urlAdr"))
        devise = asset.get("currencyCd") or None

        place = asset.get("place") or {}
        ville = place.get("cityName") or None
        pays = (place.get("countryCode") or self.country_fallback or None)
        if pays:
            pays = str(pays).strip().upper()
            pays = _ISO3_TO_ISO2.get(pays, pays)

        rtype = _classify(asset, name)
        distances = _distances(asset)

        if not distances:
            return [Race(
                source=self.source, external_id=str(guid), date=date,
                pays=pays, ville=ville, distance_km=None, type=rtype,
                prix=None, devise=devise, nom=name or None, url=url,
            )]

        out = []
        for label, km in distances:
            out.append(Race(
                source=self.source,
                external_id=f"{guid}:{label}",
                date=date, pays=pays, ville=ville,
                distance_km=km, type=rtype,
                prix=None, devise=devise,
                nom=f"{name} – {label}" if name else None,
                url=url,
            ))
        return out


# ── Helpers ───────────────────────────────────────────────────────────────

def _distances(asset: dict) -> list[tuple]:
    """Extrait les distances depuis assetAttributes et assetTags.

    Retourne une liste de (label, km) dédupliquée, ex. [("5K", 5.0)].
    """
    labels = []
    for a in asset.get("assetAttributes") or []:
        attr = a.get("attribute") or {}
        if "distance" in (attr.get("attributeType") or "").lower():
            val = attr.get("attributeValue")
            if val:
                labels.append(val)
    for t in asset.get("assetTags") or []:
        tag = t.get("tag") or {}
        if "distance" in (tag.get("tagDescription") or "").lower():
            val = tag.get("tagName")
            if val:
                labels.append(val)

    out, seen = [], set()
    for label in labels:
        key = label.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        km = _parse_distance(label)
        out.append((label, km))
    return out


def _classify(asset: dict, name: str) -> str:
    """route/trail si course à pied ; sinon other."""
    taxonomies = " ".join(
        (t.get("topic") or {}).get("topicTaxonomy", "")
        for t in asset.get("assetTopics") or []
    ).lower()
    topic_names = " ".join(
        (t.get("topic") or {}).get("topicName", "")
        for t in asset.get("assetTopics") or []
    ).lower()

    is_run = "running" in taxonomies or "running" in topic_names
    if not is_run:
        # Pas d'info de topic exploitable : on suppose course à pied
        # (le connecteur interroge déjà topic=Running par défaut).
        if taxonomies or topic_names:
            return "other"

    blob = f"{name} {taxonomies}".lower()
    if any(kw in blob for kw in _TRAIL_KW):
        return "trail"
    return "route"

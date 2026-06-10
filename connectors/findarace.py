"""
Connecteur findarace.com — scraping du calendrier de courses UK.

⚠️ Pas d'API : on lit le site HTML. Règles respectées :
  - on ne visite QUE des URLs autorisées par robots.txt
    (/running-events/pN pour les listes, /events/... pour le détail) ;
  - délai poli entre requêtes + User-Agent identifiable ;
  - usage étudiant / non commercial. Vérifier les CGU :
    https://findarace.com/terms-and-conditions

⚠️ Parsing best-effort : findarace expose des champs étiquetés stables
(Date / Location / Price / Distances) mais le HTML peut évoluer. À valider
avec scripts/preview_findarace.py et ajuster les helpers si besoin.
"""

import html as _html
import re
import time
import urllib.request
from datetime import datetime
from typing import Callable, Optional

from connectors.base import Connector
from connectors.runsignup import _parse_distance  # "10km"/"Half Marathon"→km
from core.model import Race

BASE = "https://findarace.com"
LIST_PATH = "/running-events"           # liste paginée : /running-events/pN

_TRAIL_KW = ("trail", "ultra", "fell", "mountain", "sky", "mud", "off-road", "off road")

HttpGet = Callable[[str], str]


# ── HTTP en direct (remplaçable pour les tests) ──────────────────────────

def live_http_get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "kotcha-races-student-project/0.1 (+contact via findarace support)",
                 "Accept": "text/html"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


# ── Connecteur ────────────────────────────────────────────────────────────

class FindaraceConnector(Connector):
    source = "findarace"

    def __init__(self, max_pages=5, request_delay=1.5,
                 http_get: HttpGet = live_http_get,
                 min_distance_km=None, keep_types=None):
        self.max_pages = max_pages
        self.delay = request_delay
        self.http_get = http_get
        self.min_km = min_distance_km
        self.keep_types = keep_types

    def fetch(self) -> list[Race]:
        slugs = self._collect_slugs()
        races, seen = [], set()
        for i, slug in enumerate(slugs):
            if i > 0:
                time.sleep(self.delay)
            try:
                page = self.http_get(f"{BASE}/events/{slug}")
            except Exception:
                continue
            for race in self._to_models(page, f"{BASE}/events/{slug}"):
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

    # ── Collecte des slugs depuis les pages de liste ──

    def _collect_slugs(self) -> list:
        slugs, ordered = set(), []
        for page in range(1, self.max_pages + 1):
            url = f"{BASE}{LIST_PATH}" if page == 1 else f"{BASE}{LIST_PATH}/p{page}"
            try:
                html_text = self.http_get(url)
            except Exception:
                break
            found = _event_slugs(html_text)
            new = [s for s in found if s not in slugs]
            if not new:
                break
            for s in new:
                slugs.add(s)
                ordered.append(s)
            if page < self.max_pages:
                time.sleep(self.delay)
        return ordered

    # ── Traduction d'une page d'événement vers Race ──

    def _to_models(self, page: str, url: str) -> list[Race]:
        nom = _meta(page, "og:title") or _tag_text(page, "title") or ""
        nom = re.split(r"\s*\|\s*", nom)[0].strip()
        nom = re.sub(r"\s+(?:19|20)\d{2}$", "", nom).strip() or None  # retire l'année finale

        text = _strip(page)
        date = _parse_uk_date(_label(text, "Date",
                                     stop=("Time", "Location", "Price", "Races", "Distances")))
        location = _label(text, "Location", stop=("Price", "Races", "Distances", "Time"))
        ville = location.split(",")[0].strip() if location else None
        prix = _parse_price(_label(text, "Price", stop=("Races", "Distances")))
        dist_txt = _label(text, "Distances", stop=("Last chance", "Race day",
                                                    "Popular", "Booked", "Book", "Share"))
        rtype = _classify(nom or "", dist_txt or "")

        distances = _split_distances(dist_txt)
        slug = url.rsplit("/events/", 1)[-1]

        if not distances:
            return [Race(source=self.source, external_id=slug, date=date,
                         pays="GB", ville=ville, distance_km=None, type=rtype,
                         prix=prix, devise="GBP" if prix is not None else None,
                         nom=nom, url=url)]

        out = []
        for label in distances:
            km = _parse_distance(label)
            out.append(Race(
                source=self.source,
                external_id=f"{slug}:{label.lower()}",
                date=date, pays="GB", ville=ville,
                distance_km=km, type=rtype,
                prix=prix, devise="GBP" if prix is not None else None,
                nom=f"{nom} – {label}" if nom else None,
                url=url,
            ))
        return out


# ── Helpers ───────────────────────────────────────────────────────────────

def _event_slugs(html_text: str) -> list:
    """Tous les slugs /events/<slug> d'une page de liste, dans l'ordre."""
    out, seen = [], set()
    for m in re.finditer(r'href="(?:https://findarace\.com)?/events/([A-Za-z0-9\-/]+?)"', html_text):
        slug = m.group(1).strip("/")
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _meta(html_text: str, prop: str) -> Optional[str]:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        html_text, re.IGNORECASE)
    return _html.unescape(m.group(1)).strip() if m else None


def _tag_text(html_text: str, tag: str) -> Optional[str]:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html_text, re.IGNORECASE | re.DOTALL)
    return _html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None


def _strip(html_text: str) -> str:
    """HTML → texte visible, espaces normalisés."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _label(text: str, label: str, stop=()) -> Optional[str]:
    """Valeur après une étiquette ('Location' → 'Sandringham, Norfolk')."""
    stop_pat = "|".join(re.escape(s) for s in stop) or r"\Z"
    m = re.search(rf"\b{re.escape(label)}\s+(.+?)\s*(?:{stop_pat}|\Z)", text)
    return m.group(1).strip() if m else None


_MONTHS = ("January February March April May June July August "
           "September October November December").split()


def _parse_uk_date(value: Optional[str]) -> Optional[str]:
    """'Fri 12th June 2026' (ou '12 June 2026') → '2026-06-12'."""
    if not value:
        return None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", value)
    if not m:
        return None
    day, month, year = int(m.group(1)), m.group(2).capitalize(), int(m.group(3))
    if month not in _MONTHS:
        return None
    try:
        return datetime(year, _MONTHS.index(month) + 1, day).date().isoformat()
    except ValueError:
        return None


def _parse_price(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = re.search(r"([\d]+(?:\.\d+)?)", value.replace(",", ""))
    return float(m.group(1)) if m else None


def _split_distances(value: Optional[str]) -> list:
    if not value:
        return []
    parts = re.split(r",|&|/|\band\b", value)
    out, seen = [], set()
    for p in parts:
        p = p.strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def _classify(*texts: str) -> str:
    blob = " ".join(texts).lower()
    if any(kw in blob for kw in _TRAIL_KW):
        return "trail"
    return "route"

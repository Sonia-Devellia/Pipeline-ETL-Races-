"""
Connecteur findarace.com — courses UK (pas d'API, lecture du site HTML).

Règles respectées :
  - on récupère la liste des événements via le SITEMAP officiel
    (https://findarace.com/sitemap-events-current.xml), prévu pour les robots,
    ce qui évite le bruit des menus de navigation ;
  - pages /events/... autorisées par robots.txt ;
  - délai poli entre requêtes + User-Agent identifiable ;
  - usage étudiant / non commercial. CGU : https://findarace.com/terms-and-conditions

⚠️ Parsing best-effort : on borne l'extraction au bloc d'info de l'événement
(Date / Location / Price / Distances). À valider via scripts/preview_findarace.py.
"""

import gzip
import html as _html
import re
import time
import urllib.request
from datetime import datetime
from typing import Callable, Optional

from connectors.base import Connector
from connectors.runsignup import _parse_distance
from core.model import Race

BASE = "https://findarace.com"
SITEMAP_URL = f"{BASE}/sitemap-events-current.xml"

_TRAIL_KW = ("trail", "ultra", "fell", "mountain", "sky", "mud", "off-road", "off road")
# Multisports / non course à pied → exclus (type "other").
_OTHER_KW = ("triathlon", "duathlon", "aquathlon", "aquabike", "swimrun",
             "sportive", "cycling", "swim", "bike", "ride ")
# Pages qui ne sont pas des courses.
_SKIP_NAME_KW = ("additional payment", "payment form", "gift voucher", "voucher",
                 "membership", "deposit", "donation", "entry transfer",
                 "virtual challenge", "virtual run", "virtual race", "fun challenge",
                 "collectibles")
# Distances de triathlon — exclues d'une base de course à pied.
_SKIP_DISTANCE = {"super sprint", "sprint", "olympic", "standard", "middle distance",
                  "iron distance", "70.3", "140.6", "aquabike"}

HttpGet = Callable[[str], str]


# ── HTTP en direct (remplaçable pour les tests) ──────────────────────────

def live_http_get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "kotcha-races-student-project/0.1",
                 "Accept": "text/html,application/xml"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":          # sitemap gzippé
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


# ── Connecteur ────────────────────────────────────────────────────────────

class FindaraceConnector(Connector):
    source = "findarace"

    def __init__(self, max_events=80, request_delay=1.5,
                 http_get: HttpGet = live_http_get,
                 min_distance_km=None, keep_types=None):
        self.max_events = max_events
        self.delay = request_delay
        self.http_get = http_get
        self.min_km = min_distance_km
        self.keep_types = keep_types

    def fetch(self) -> list[Race]:
        slugs = self._collect_slugs()[: self.max_events]
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
                    continue
                if self.keep_types and race.type not in self.keep_types:
                    continue
                seen.add(race.external_id)
                races.append(race)
        return races

    # ── Slugs depuis le sitemap (propre, sans menus) ──

    def _collect_slugs(self) -> list:
        try:
            xml = self.http_get(SITEMAP_URL)
        except Exception:
            return []
        slugs = _event_slugs_from_sitemap(xml)
        if slugs:
            return slugs
        # Sitemap d'index : on suit un niveau de sous-sitemaps "events".
        out, seen = [], set()
        for sub in re.findall(r"<loc>\s*([^<\s]+\.xml[^<\s]*)\s*</loc>", xml):
            if "event" not in sub.lower():
                continue
            try:
                for s in _event_slugs_from_sitemap(self.http_get(sub)):
                    if s not in seen:
                        seen.add(s)
                        out.append(s)
            except Exception:
                continue
        return out

    # ── Traduction d'une page d'événement vers Race ──

    def _to_models(self, page: str, url: str) -> list[Race]:
        nom = _meta(page, "og:title") or _tag_text(page, "title") or ""
        nom = re.split(r"\s*\|\s*", nom)[0].strip()
        nom = re.sub(r"\s+(?:19|20)\d{2}$", "", nom).strip() or None

        # Pages parasites (paiements, défis virtuels, bons cadeaux…) → ignorées.
        if nom and any(k in nom.lower() for k in _SKIP_NAME_KW):
            return []

        text = _strip(page)
        scope = _info_block(text)                    # borne au bloc d'info
        date = _parse_uk_date(scope)
        location = _label(scope, "Location", stop=("Price", "Races", "Distances", "Time"))
        ville = location.split(",")[0].strip() if location else None

        # Événements virtuels : pas de vraie course localisée → ignorés.
        if location and "virtual" in location.lower():
            return []
        prix = _parse_price(_label(scope, "Price", stop=("Races", "Distances", "UK Athletics")))
        dist_txt = _label(scope, "Distances", stop=(
            "Last chance", "Race day", "Popular", "Booked", "Book", "Share",
            "Event", "Read", "Top rated", "This is", "Sold out", "Last few",
            "New ", "Quick Book", "Add to", "See "))
        rtype = _classify(nom or "", dist_txt or "")
        slug = url.rsplit("/events/", 1)[-1]

        distances = [d for d in _split_distances(dist_txt)
                     if d.lower() not in _SKIP_DISTANCE]
        if not distances:
            return [Race(source=self.source, external_id=slug, date=date,
                         pays="GB", ville=ville, distance_km=None, type=rtype,
                         prix=prix, devise="GBP" if prix is not None else None,
                         nom=nom, url=url)]

        out = []
        for label in distances:
            out.append(Race(
                source=self.source,
                external_id=f"{slug}:{label.lower()}",
                date=date, pays="GB", ville=ville,
                distance_km=_parse_distance(label), type=rtype,
                prix=prix, devise="GBP" if prix is not None else None,
                nom=f"{nom} – {label}" if nom else None,
                url=url,
            ))
        return out


# ── Helpers ───────────────────────────────────────────────────────────────

def _event_slugs_from_sitemap(xml: str) -> list:
    out, seen = [], set()
    for m in re.finditer(r"/events/([A-Za-z0-9\-/]+?)\s*</loc>", xml):
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
    # 1) supprime les blocs de code/templates
    t = re.sub(r"<(script|style|template|noscript)[^>]*>.*?</\1>", " ",
               html_text, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.DOTALL)
    # 2) supprime les balises en tolérant les > présents DANS des attributs
    #    entre guillemets (sinon le JS Alpine type x-data="{ a > b }" fuite).
    t = re.sub(r"""<(?:[^>"']|"[^"]*"|'[^']*')*>""", " ", t)
    t = _html.unescape(t)
    # 3) filet de sécurité : résidus d'expressions { ... } éventuelles
    t = re.sub(r"\{[^{}]*\}", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _info_block(text: str) -> str:
    """Isole le bloc d'info de l'événement : de 'Date <jj mois aaaa>' jusqu'à
    un marqueur de fin. Évite les menus de navigation (qui n'ont pas ce motif)."""
    m = re.search(
        r"Date\s+\w+\s+\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4}.*?"
        r"(?:Event summary|Read more|Share this event|Course Details|Book Now|\Z)",
        text, re.DOTALL)
    return m.group(0) if m else text


def _label(text: str, label: str, stop=()) -> Optional[str]:
    stop_pat = "|".join(re.escape(s) for s in stop) or r"\Z"
    m = re.search(rf"\b{re.escape(label)}\s+(.+?)\s*(?:{stop_pat}|\Z)", text)
    return m.group(1).strip() if m else None


_MONTHS = ("January February March April May June July August "
           "September October November December").split()


def _parse_uk_date(value: Optional[str]) -> Optional[str]:
    """'Fri 12th June 2026' ou '12 June 2026' → '2026-06-12'."""
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
    if any(kw in blob for kw in _OTHER_KW):
        return "other"
    if any(kw in blob for kw in _TRAIL_KW):
        return "trail"
    return "route"

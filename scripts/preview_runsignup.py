"""
Aperçu rapide du connecteur RunSignup pour le Canada (sans écrire en base).

Usage :
    python3 scripts/preview_runsignup.py              # CA, toutes provinces
    python3 scripts/preview_runsignup.py CA ON,QC     # CA, provinces ON et QC
    python3 scripts/preview_runsignup.py CA ON,QC 20  # idem, 20 résultats max
    python3 scripts/preview_runsignup.py US CA         # US, état CA, 10 résultats

Lit RUNSIGNUP_COUNTRY / RUNSIGNUP_REGIONS depuis .env si présents.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.runsignup import RunSignupConnector, CA_PROVINCES  # noqa: E402


def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = [p.strip() for p in line.split("=", 1)]
            if key and key not in os.environ:
                os.environ[key] = value.strip("\"'")


def main():
    load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))

    args = [a for a in sys.argv[1:] if not a.startswith("#")]
    country = (args[0] if args else os.environ.get("RUNSIGNUP_COUNTRY", "CA")).upper()

    regions = None
    if len(args) > 1:
        regions = [r.strip() for r in args[1].split(",") if r.strip()]
    elif os.environ.get("RUNSIGNUP_REGIONS"):
        regions = [r.strip() for r in os.environ["RUNSIGNUP_REGIONS"].split(",")]
    elif country == "CA":
        # L'API RunSignup ignore country_code sans région — on balaye toutes les provinces.
        regions = CA_PROVINCES

    limit = 10
    if len(args) > 2:
        try:
            limit = int(args[2])
        except ValueError:
            pass

    today = date.today()
    start = today.isoformat()
    end = (today + timedelta(days=90)).isoformat()

    region_kw = {"regions": regions} if regions else {}

    connector = RunSignupConnector(
        country_code=country,
        start_date=start,
        end_date=end,
        results_per_page=50,
        request_delay=0.3,
        min_distance_km=None,
        keep_types=None,
        **region_kw,
    )

    regions_label = ",".join(regions) if regions else "toutes provinces/régions"
    print(f"RunSignup — pays={country}, régions={regions_label}, fenêtre 90 jours…")

    try:
        races = connector.fetch()
    except Exception as exc:
        raise SystemExit(f"Échec de l'appel RunSignup : {exc}")

    by_type = {}
    for r in races:
        by_type[r.type] = by_type.get(r.type, 0) + 1
    filtered = [r for r in races
                if r.type in ("route", "trail")
                and (r.distance_km is None or r.distance_km >= 5)]

    print(f"API : {len(races)} lignes au total (par type : {by_type or '∅'})")
    print(f"Dont {len(filtered)} route/trail ≥ 5 km. Aperçu :\n")

    sample = filtered or races
    for r in sample[:limit]:
        dist = f"{r.distance_km} km" if r.distance_km else "?"
        prix = f" | {r.prix} {r.devise}" if r.prix else ""
        print(f"  • [{r.type}] {r.date or '—'} | {r.ville or '—'} ({r.pays or '—'}) "
              f"| {dist}{prix} | {r.nom or '—'}")
        if r.url:
            print(f"      {r.url}")


if __name__ == "__main__":
    main()

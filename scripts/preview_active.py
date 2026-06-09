"""
Aperçu rapide du connecteur ACTIVE (sans écrire en base).

Usage :
    python3 scripts/preview_active.py          # pays = ACTIVE_COUNTRY (.env) ou CA
    python3 scripts/preview_active.py AU 8      # pays AU, 8 résultats max

Lit ACTIVE_API_KEY (et ACTIVE_COUNTRY) depuis le fichier .env à la racine.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.active import ActiveConnector  # noqa: E402


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

    api_key = os.environ.get("ACTIVE_API_KEY")
    if not api_key:
        raise SystemExit("ACTIVE_API_KEY manquant dans .env")

    # On ignore tout argument qui commence par '#' (commentaire collé depuis le shell).
    args = [a for a in sys.argv[1:] if not a.startswith("#")]
    country = args[0] if args else os.environ.get("ACTIVE_COUNTRY", "CA")
    limit = 10
    if len(args) > 1:
        try:
            limit = int(args[1])
        except ValueError:
            pass

    today = date.today()
    # On récupère SANS filtre pour diagnostiquer, puis on filtre en mémoire.
    connector = ActiveConnector(
        api_key=api_key,
        country=country,
        start_date=today.isoformat(),
        end_date=(today + timedelta(days=90)).isoformat(),
        results_per_page=50,
        request_delay=0.3,
        min_distance_km=None,
        keep_types=None,
    )

    print(f"ACTIVE — pays={country}, fenêtre 90 jours…")
    try:
        races = connector.fetch()
    except Exception as exc:
        raise SystemExit(f"Échec de l'appel ACTIVE : {exc}")

    # Répartition par type pour comprendre ce que renvoie l'API.
    by_type = {}
    for r in races:
        by_type[r.type] = by_type.get(r.type, 0) + 1
    filtered = [r for r in races
                if r.type in ("route", "trail")
                and (r.distance_km is None or r.distance_km >= 5)]

    print(f"API : {len(races)} lignes au total "
          f"(par type : {by_type or '∅'})")
    print(f"Dont {len(filtered)} route/trail ≥ 5 km. Aperçu :\n")

    sample = filtered or races  # si rien ne passe le filtre, on montre le brut
    for r in sample[:limit]:
        dist = f"{r.distance_km} km" if r.distance_km else "?"
        print(f"  • [{r.type}] {r.date or '—'} | {r.ville or '—'} ({r.pays or '—'}) "
              f"| {dist} | {r.nom or '—'}")
        if r.url:
            print(f"      {r.url}")


if __name__ == "__main__":
    main()

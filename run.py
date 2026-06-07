"""
Orchestrateur du pipeline ETL.
Pour chaque connecteur : fetch() → upsert en base.
"""

import os
from datetime import date, timedelta

from connectors.runsignup import RunSignupConnector, US_STATES, cache_http_get_factory
from core.loader import MySQLLoader, SQLiteLoader

TARGET_TYPES = {"route", "trail"}


def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = [part.strip() for part in line.split("=", 1)]
            if key and key not in os.environ:
                os.environ[key] = value.strip("\"'")


def main():
    load_dotenv()

    # ── Dates (par défaut : aujourd'hui → +3 mois) ──
    today = date.today()
    start = os.environ.get("RUNSIGNUP_START", today.isoformat())
    end = os.environ.get("RUNSIGNUP_END", (today + timedelta(days=90)).isoformat())

    # ── Pays ciblé (US par défaut) ──
    country = os.environ.get("RUNSIGNUP_COUNTRY", "US").upper()
    if country == "US":
        # Balayage état par état pour une couverture complète des US.
        state = os.environ.get("RUNSIGNUP_STATE", "CA")
        region_kw = {"states": US_STATES} if state.upper() in ("ALL", "US") else {"state": state}
    else:
        # Hors US : filtrage par pays. On peut préciser des régions via
        # RUNSIGNUP_REGIONS="ON,QC,BC" (sinon tout le pays).
        regions_env = os.environ.get("RUNSIGNUP_REGIONS")
        region_kw = ({"regions": [r.strip() for r in regions_env.split(",")]}
                     if regions_env else {})

    # ── Mode hors-ligne (cache local) ──
    cache_dir = os.environ.get("RUNSIGNUP_CACHE_DIR")
    http_kw = {"http_get": cache_http_get_factory(cache_dir)} if cache_dir else {}

    # ── Liste des connecteurs à exécuter ──
    connectors = [
        RunSignupConnector(
            country_code=country,
            start_date=start, end_date=end,
            min_distance_km=5, keep_types=TARGET_TYPES,
            **region_kw, **http_kw,
        )
    ]

    # Race Roster (optionnel) — activé si les identifiants OAuth sont présents.
    if os.environ.get("RACEROSTER_CLIENT_ID"):
        from connectors.raceroster import RaceRosterConnector
        connectors.append(RaceRosterConnector(
            client_id=os.environ["RACEROSTER_CLIENT_ID"],
            client_secret=os.environ.get("RACEROSTER_CLIENT_SECRET", ""),
            username=os.environ.get("RACEROSTER_USERNAME", ""),
            password=os.environ.get("RACEROSTER_PASSWORD", ""),
            start_date=start, end_date=end,
            min_distance_km=5, keep_types=TARGET_TYPES,
        ))

    # Athlinks (optionnel) — activé si une clé API est présente.
    if os.environ.get("ATHLINKS_API_KEY"):
        from connectors.athlinks import AthlinksConnector
        connectors.append(AthlinksConnector(
            api_key=os.environ["ATHLINKS_API_KEY"],
            auth_param=os.environ.get("ATHLINKS_AUTH_PARAM", "apikey"),
            term=os.environ.get("ATHLINKS_TERM", ""),
            country=os.environ.get("ATHLINKS_COUNTRY"),
            start_date=start, end_date=end,
            min_distance_km=5, keep_types=TARGET_TYPES,
        ))

    # ── Loader (MySQL par défaut, SQLite pour tests) ──
    backend = os.environ.get("DB_BACKEND", "mysql").lower()
    if backend == "sqlite":
        loader = SQLiteLoader(os.environ.get("RACES_DB_PATH", "races.db"))
    else:
        mysql_user = os.environ.get("MYSQL_USER", "root")
        mysql_password = os.environ.get("MYSQL_PASSWORD", "")
        if mysql_user == "root" and mysql_password == "":
            raise SystemExit(
                "Connexion MySQL impossible: MYSQL_PASSWORD est vide.\n"
                "Crée un fichier .env à la racine du projet avec par exemple:\n"
                "MYSQL_HOST=localhost\n"
                "MYSQL_PORT=3306\n"
                "MYSQL_USER=root\n"
                "MYSQL_PASSWORD=ton_mot_de_passe_mysql\n"
                "MYSQL_DB=kotcha_races"
            )

        loader = MySQLLoader(
            host=os.environ.get("MYSQL_HOST", "localhost"),
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=mysql_user,
            password=mysql_password,
            database=os.environ.get("MYSQL_DB", "kotcha_races"),
        )

    # ── Pipeline : pour chaque connecteur, fetch → upsert ──
    try:
        for connector in connectors:
            print(f"[{connector.source}] fetch…")
            races = connector.fetch()
            inserted, updated = loader.upsert(races)
            print(f"[{connector.source}] {len(races)} courses → "
                  f"{inserted} insérées, {updated} màj")
        deleted = loader.delete_non_target_types(TARGET_TYPES)
        if deleted:
            print(f"{deleted} lignes hors route/trail supprimées")
        print(f"Total en base : {loader.count()} lignes ({backend})")
    finally:
        loader.close()


if __name__ == "__main__":
    main()

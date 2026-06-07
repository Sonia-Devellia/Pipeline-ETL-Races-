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

    # ── État(s) à scraper ──
    state = os.environ.get("RUNSIGNUP_STATE", "CA")
    state_kw = {"states": US_STATES} if state.upper() in ("ALL", "US") else {"state": state}

    # ── Mode hors-ligne (cache local) ──
    cache_dir = os.environ.get("RUNSIGNUP_CACHE_DIR")
    http_kw = {"http_get": cache_http_get_factory(cache_dir)} if cache_dir else {}

    # ── Connecteur ──
    connector = RunSignupConnector(
        start_date=start, end_date=end,
        min_distance_km=5, keep_types=TARGET_TYPES,
        **state_kw, **http_kw,
    )

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

    # ── Pipeline ──
    try:
        print(f"[{connector.source}] fetch…")
        races = connector.fetch()
        inserted, updated = loader.upsert(races)
        deleted = loader.delete_non_target_types(TARGET_TYPES)
        print(f"[{connector.source}] {len(races)} courses → {inserted} insérées, {updated} màj")
        if deleted:
            print(f"{deleted} lignes hors route/trail supprimées")
        print(f"Total en base : {loader.count()} lignes ({backend})")
    finally:
        loader.close()


if __name__ == "__main__":
    main()

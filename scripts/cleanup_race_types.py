"""Supprime de la table races tout ce qui n'est pas route ou trail."""

from run import TARGET_TYPES, load_dotenv
from core.loader import MySQLLoader
import os


def main():
    load_dotenv()
    loader = MySQLLoader(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DB", "kotcha_races"),
    )
    try:
        deleted = loader.delete_non_target_types(TARGET_TYPES)
        print(f"{deleted} lignes hors route/trail supprimées")
        print(f"Total en base : {loader.count()} lignes")
    finally:
        loader.close()


if __name__ == "__main__":
    main()

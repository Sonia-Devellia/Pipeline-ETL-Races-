"""Écriture des Race normalisées en base MySQL ou SQLite."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Iterable

from core.model import Race


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Loader(ABC):
    @abstractmethod
    def upsert(self, races: Iterable[Race]) -> tuple[int, int]: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def delete_non_target_types(self, keep_types: set[str]) -> int: ...

    @abstractmethod
    def close(self) -> None: ...


class MySQLLoader(Loader):

    DDL = """
    CREATE TABLE IF NOT EXISTS races (
        id           BIGINT       NOT NULL AUTO_INCREMENT,
        source       VARCHAR(64)  NOT NULL,
        external_id  VARCHAR(128) NOT NULL,
        date         DATE         NULL,
        pays         VARCHAR(8)   NULL,
        ville        VARCHAR(255) NULL,
        distance_km  DOUBLE       NULL,
        type         VARCHAR(16)  NULL,
        prix         DECIMAL(10,2) NULL,
        devise       VARCHAR(8)   NULL,
        updated_at   DATETIME     NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uq_source_external (source, external_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    UPSERT = """
    INSERT INTO races
        (source, external_id, date, pays, ville,
         distance_km, type, prix, devise, updated_at)
    VALUES
        (%(source)s, %(external_id)s, %(date)s, %(pays)s, %(ville)s,
         %(distance_km)s, %(type)s, %(prix)s, %(devise)s, %(updated_at)s)
    ON DUPLICATE KEY UPDATE
        date=VALUES(date), pays=VALUES(pays), ville=VALUES(ville),
        distance_km=VALUES(distance_km), type=VALUES(type),
        prix=VALUES(prix), devise=VALUES(devise), updated_at=VALUES(updated_at);
    """

    def __init__(self, host="localhost", port=3306, user="root",
                 password="", database="kotcha_races"):
        import pymysql
        self.conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, charset="utf8mb4", autocommit=False,
        )
        with self.conn.cursor() as cur:
            cur.execute(self.DDL)
        self.conn.commit()

    def upsert(self, races: Iterable[Race]) -> tuple[int, int]:
        races = list(races)
        if not races:
            return (0, 0)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT external_id FROM races WHERE source = %s",
                (races[0].source,),
            )
            existing = {row[0] for row in cur.fetchall()}
            now = _now_iso()
            inserted = updated = 0
            for race in races:
                params = race.as_dict()
                params["updated_at"] = now
                cur.execute(self.UPSERT, params)
                if race.external_id in existing:
                    updated += 1
                else:
                    inserted += 1
        self.conn.commit()
        return (inserted, updated)

    def count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM races")
            return cur.fetchone()[0]

    def delete_non_target_types(self, keep_types: set[str]) -> int:
        placeholders = ", ".join(["%s"] * len(keep_types))
        with self.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM races WHERE type IS NULL OR type NOT IN ({placeholders})",
                tuple(sorted(keep_types)),
            )
            deleted = cur.rowcount
        self.conn.commit()
        return deleted

    def close(self):
        self.conn.close()


class SQLiteLoader(Loader):

    DDL = """
    CREATE TABLE IF NOT EXISTS races (
        id           INTEGER      NOT NULL PRIMARY KEY AUTOINCREMENT,
        source       TEXT         NOT NULL,
        external_id  TEXT         NOT NULL,
        date         TEXT         NULL,
        pays         TEXT         NULL,
        ville        TEXT         NULL,
        distance_km  REAL         NULL,
        type         TEXT         NULL,
        prix         REAL         NULL,
        devise       TEXT         NULL,
        updated_at   TEXT         NULL,
        UNIQUE (source, external_id)
    );
    """

    UPSERT = """
    INSERT INTO races
        (source, external_id, date, pays, ville,
         distance_km, type, prix, devise, updated_at)
    VALUES
        (:source, :external_id, :date, :pays, :ville,
         :distance_km, :type, :prix, :devise, :updated_at)
    ON CONFLICT(source, external_id) DO UPDATE SET
        date=excluded.date,
        pays=excluded.pays,
        ville=excluded.ville,
        distance_km=excluded.distance_km,
        type=excluded.type,
        prix=excluded.prix,
        devise=excluded.devise,
        updated_at=excluded.updated_at;
    """

    def __init__(self, path="races.db"):
        import sqlite3
        self.conn = sqlite3.connect(path)
        self.conn.execute(self.DDL)
        self.conn.commit()

    def upsert(self, races: Iterable[Race]) -> tuple[int, int]:
        races = list(races)
        if not races:
            return (0, 0)

        cur = self.conn.cursor()
        cur.execute(
            "SELECT external_id FROM races WHERE source = ?",
            (races[0].source,),
        )
        existing = {row[0] for row in cur.fetchall()}

        now = _now_iso()
        inserted = updated = 0
        for race in races:
            params = race.as_dict()
            params["updated_at"] = now
            cur.execute(self.UPSERT, params)
            if race.external_id in existing:
                updated += 1
            else:
                inserted += 1
        self.conn.commit()
        return (inserted, updated)

    def count(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM races")
        return cur.fetchone()[0]

    def delete_non_target_types(self, keep_types: set[str]) -> int:
        placeholders = ", ".join(["?"] * len(keep_types))
        cur = self.conn.cursor()
        cur.execute(
            f"DELETE FROM races WHERE type IS NULL OR type NOT IN ({placeholders})",
            tuple(sorted(keep_types)),
        )
        self.conn.commit()
        return cur.rowcount

    def close(self):
        self.conn.close()

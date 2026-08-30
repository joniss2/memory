"""Migrationsrunner. Nummerierte SQL-Dateien, einmal angewandt, protokolliert."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

from provenance.config import get_settings
from provenance.db.pool import connection

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,
  checksum    TEXT NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    raw: str

    @property
    def checksum(self) -> str:
        """Hash über die Datei, nicht über das eingesetzte Ergebnis.

        Sonst änderte ein Wechsel von PROVENANCE_EMBEDDING_DIM die Prüfsumme
        einer längst angewandten Migration -- und der Dienst verweigerte den
        Start mit der irreführenden Meldung, jemand habe die Datei bearbeitet.
        """
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()[:16]


def _render(raw: str, embedding_dim: int) -> str:
    return raw.replace("${EMBEDDING_DIM}", str(int(embedding_dim)))


def load_migrations(embedding_dim: int | None = None) -> list[Migration]:
    dim = embedding_dim if embedding_dim is not None else get_settings().embedding_dim
    out: list[Migration] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        raw = path.read_text("utf-8")
        out.append(Migration(version=version, path=path, sql=_render(raw, dim), raw=raw))
    return out


def applied_versions(conn: psycopg.Connection) -> dict[str, str]:
    conn.execute(_BOOTSTRAP)
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {row["version"]: row["checksum"] for row in rows}


def migrate(database_url: str | None = None, embedding_dim: int | None = None) -> list[str]:
    """Wendet ausstehende Migrationen an und gibt deren Versionen zurück."""
    applied_now: list[str] = []
    with connection(database_url) as conn:
        known = applied_versions(conn)
        for migration in load_migrations(embedding_dim):
            if migration.version in known:
                if known[migration.version] != migration.checksum:
                    raise RuntimeError(
                        f"Migration {migration.version} wurde nach dem Anwenden geändert "
                        f"(erwartet {known[migration.version]}, gefunden {migration.checksum}). "
                        "Migrationen sind unveränderlich; eine neue Datei anlegen."
                    )
                continue
            with conn.transaction():
                conn.execute(migration.sql)  # type: ignore[arg-type]
                conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (migration.version, migration.checksum),
                )
            applied_now.append(migration.version)
        conn.commit()
    return applied_now


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def drop_all(database_url: str | None = None) -> None:
    """Räumt das Schema leer. Für Tests und Eval-Läufe, nicht für Betrieb."""
    with connection(database_url) as conn:
        with conn.transaction():
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
        conn.commit()


def reset(database_url: str | None = None, embedding_dim: int | None = None) -> None:
    drop_all(database_url)
    migrate(database_url, embedding_dim)

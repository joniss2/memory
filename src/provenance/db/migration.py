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
  version        TEXT PRIMARY KEY,
  checksum       TEXT NOT NULL,
  embedding_dim  INTEGER,
  applied_at     TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

# Für Installationen, die vor dieser Spalte angelegt wurden.
_BOOTSTRAP_DIM = "ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS embedding_dim INTEGER"


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    raw: str
    embedding_dim: int

    @property
    def checksum(self) -> str:
        """Hash über die Datei, nicht über das eingesetzte Ergebnis.

        Sonst änderte ein Wechsel von PROVENANCE_EMBEDDING_DIM die Prüfsumme
        einer längst angewandten Migration -- und der Dienst verweigerte den
        Start mit der irreführenden Meldung, jemand habe die Datei bearbeitet.
        """
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()[:16]

    @property
    def depends_on_dim(self) -> bool:
        """Setzt diese Datei die Einbettungsweite ins Schema ein?

        Nur solche Migrationen werden gegen die Konfiguration geprüft; für
        alle anderen ist die Weite ohne Belang.
        """
        return "${EMBEDDING_DIM}" in self.raw


def _render(raw: str, embedding_dim: int) -> str:
    return raw.replace("${EMBEDDING_DIM}", str(int(embedding_dim)))


def load_migrations(embedding_dim: int | None = None) -> list[Migration]:
    dim = embedding_dim if embedding_dim is not None else get_settings().embedding_dim
    out: list[Migration] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        raw = path.read_text("utf-8")
        out.append(
            Migration(
                version=version, path=path, sql=_render(raw, dim), raw=raw, embedding_dim=dim
            )
        )
    return out


def applied_versions(conn: psycopg.Connection) -> dict[str, dict[str, object]]:
    conn.execute(_BOOTSTRAP)
    conn.execute(_BOOTSTRAP_DIM)
    rows = conn.execute("SELECT version, checksum, embedding_dim FROM schema_migrations").fetchall()
    return {
        row["version"]: {"checksum": row["checksum"], "embedding_dim": row["embedding_dim"]}
        for row in rows
    }


class DimensionMismatch(RuntimeError):
    """Die konfigurierte Einbettungsweite passt nicht zum angelegten Schema."""


def migrate(database_url: str | None = None, embedding_dim: int | None = None) -> list[str]:
    """Wendet ausstehende Migrationen an und gibt deren Versionen zurück."""
    applied_now: list[str] = []
    with connection(database_url) as conn:
        known = applied_versions(conn)
        for migration in load_migrations(embedding_dim):
            if migration.version in known:
                row = known[migration.version]
                if row["checksum"] != migration.checksum:
                    raise RuntimeError(
                        f"Migration {migration.version} wurde nach dem Anwenden geändert "
                        f"(erwartet {row['checksum']}, gefunden {migration.checksum}). "
                        "Migrationen sind unveränderlich; eine neue Datei anlegen."
                    )
                # Die Prüfsumme geht über den Rohtext und merkt einen Wechsel
                # der Einbettungsweite deshalb nicht mehr. Ungeprüft liefe der
                # Dienst mit einer Vektorspalte einer Weite und einem Einbetter
                # einer anderen an -- und scheiterte erst beim Schreiben, mit
                # einer Meldung, die nirgendwohin zeigt.
                applied_dim = row["embedding_dim"]
                if (
                    migration.depends_on_dim
                    and applied_dim is not None
                    and applied_dim != migration.embedding_dim
                ):
                    raise DimensionMismatch(
                        f"Das Schema wurde mit {applied_dim} Dimensionen angelegt, "
                        f"konfiguriert sind {migration.embedding_dim} "
                        "(PROVENANCE_EMBEDDING_DIM). Bestehende Vektoren haben die alte "
                        f"Weite: entweder auf {applied_dim} zurücksetzen, oder die Fakten "
                        "in einer neuen Migration neu einbetten."
                    )
                continue
            with conn.transaction():
                conn.execute(migration.sql)  # type: ignore[arg-type]
                conn.execute(
                    "INSERT INTO schema_migrations (version, checksum, embedding_dim) "
                    "VALUES (%s, %s, %s)",
                    (
                        migration.version,
                        migration.checksum,
                        migration.embedding_dim if migration.depends_on_dim else None,
                    ),
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

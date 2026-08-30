"""Gemeinsame Fixtures.

Die Tests laufen gegen ein echtes Postgres mit pgvector. Ein Ersatz wäre
hier wertlos: bitemporale Fenster, rekursive CTEs, HNSW und die
schemakonforme Schwärzung sind genau das, was getestet werden soll.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.sql import SQL, Identifier

DEFAULT_URL = "postgresql://provenance:provenance@localhost:5432/provenance_test"
TEST_URL = os.environ.get("PROVENANCE_TEST_DATABASE_URL", DEFAULT_URL)

# Vor dem ersten provenance-Import setzen: die Einstellungen sind gecacht.
os.environ["PROVENANCE_DATABASE_URL"] = TEST_URL
os.environ.setdefault("PROVENANCE_LLM_PROVIDER", "heuristic")
os.environ.setdefault("PROVENANCE_EMBEDDING_PROVIDER", "hashing")

from provenance.config import get_settings, reset_settings_cache  # noqa: E402
from provenance.db.migration import reset as reset_schema  # noqa: E402
from provenance.db.pool import close_pool, connection  # noqa: E402

TABLES = (
    "erasure_receipts",
    "lineage",
    "trace_steps",
    "traces",
    "edges",
    "entities",
    "facts",
    "turns",
)


def _ensure_database() -> None:
    """Legt die Testdatenbank an, falls sie fehlt.

    Die URL wird über psycopg zerlegt statt am letzten Schrägstrich getrennt:
    sonst landete ein angehängtes ``?sslmode=...`` im Datenbanknamen, und die
    Fixture legte eine Datenbank an, die der Pool nie benutzt.
    """
    params = conninfo_to_dict(TEST_URL)
    name = params.get("dbname")
    if not name:
        raise RuntimeError(f"keine Datenbank in PROVENANCE_TEST_DATABASE_URL: {TEST_URL!r}")
    admin_url = make_conninfo(TEST_URL, dbname="postgres")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(SQL("CREATE DATABASE {}").format(Identifier(name)))


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    reset_settings_cache()
    _ensure_database()
    reset_schema()
    yield
    close_pool()


@pytest.fixture(autouse=True)
def clean_tables(database: None) -> Iterator[None]:
    """Jeder Test startet mit leeren Tabellen und zurückgesetzten Sequenzen.

    Zurückgesetzte Sequenzen, weil mehrere Tests über Fakt-IDs argumentieren
    und ein Test nicht davon abhängen soll, wie viele vor ihm liefen.
    """
    with connection() as conn:
        conn.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")
        conn.commit()
    yield


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def service():
    from provenance.service import MemoryService

    return MemoryService()


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with connection() as connection_:
        yield connection_
        connection_.commit()


def at(month: int, day: int = 1, year: int = 2026) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


@pytest.fixture
def ingest(service):
    """Kürzel: einen Beitrag aufnehmen."""

    def _ingest(text: str, when: datetime | None = None, subject: str = "s", **kwargs):
        return service.ingest_turn(
            subject_id=subject,
            session_id=kwargs.pop("session", "t"),
            role=kwargs.pop("role", "user"),
            content=text,
            occurred_at=when,
            **kwargs,
        )

    return _ingest

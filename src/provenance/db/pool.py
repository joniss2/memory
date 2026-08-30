"""Verbindungspool und die wenigen Helfer, die pgvector ohne Zusatzpaket
benutzbar machen."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from provenance.config import get_settings

__all__ = ["get_pool", "connection", "transaction", "to_pgvector", "from_pgvector", "Jsonb"]

_pool: ConnectionPool | None = None
_pool_url: str | None = None
_lock = threading.Lock()


def get_pool(database_url: str | None = None) -> ConnectionPool:
    """Ein Pool pro Prozess. Wechselt die URL, wird er neu aufgebaut."""
    global _pool, _pool_url
    settings = get_settings()
    url = database_url or settings.database_url
    with _lock:
        if _pool is not None and _pool_url == url:
            return _pool
        if _pool is not None:
            _pool.close()
        _pool = ConnectionPool(
            conninfo=url,
            min_size=settings.pool_min_size,
            max_size=settings.pool_max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        _pool_url = url
        return _pool


def close_pool() -> None:
    global _pool, _pool_url
    with _lock:
        if _pool is not None:
            _pool.close()
        _pool = None
        _pool_url = None


@contextmanager
def connection(database_url: str | None = None) -> Iterator[psycopg.Connection]:
    with get_pool(database_url).connection() as conn:
        yield conn


@contextmanager
def transaction(database_url: str | None = None) -> Iterator[psycopg.Connection]:
    """Eine Transaktion, ein konsistenter Zeitpunkt.

    Stufe 3 fusioniert drei Kandidatenquellen; sie müssen denselben Snapshot
    sehen, sonst ist die Fusion über Ränge aus verschiedenen Zeitpunkten
    gebildet (Abschnitt 5, Stufe 3).
    """
    with get_pool(database_url).connection() as conn, conn.transaction():
        yield conn


def to_pgvector(values: Sequence[float] | None) -> str | None:
    """Vektorliteral für pgvector.

    Bewusst ohne das Paket ``pgvector``: ein Literal plus ``::vector`` im
    Statement kostet nichts und spart eine Abhängigkeit.
    """
    if values is None:
        return None
    return "[" + ",".join(f"{float(v):.7g}" for v in values) + "]"


def from_pgvector(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [float(v) for v in raw]
    text = str(raw).strip()
    if not text.startswith("["):
        raise ValueError(f"kein Vektorliteral: {text[:40]!r}")
    inner = text[1:-1].strip()
    if not inner:
        return []
    return [float(part) for part in inner.split(",")]

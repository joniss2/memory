"""Dashboard.

Ein Datenmodell, zwei Ansichten (Abschnitt 6). Die Seiten sind reine
HTML-Hüllen; die Daten holen sie sich über dieselbe HTTP-API, die auch ein
Fremdsystem benutzen würde. Das erspart eine zweite Zugriffsschicht und
stellt sicher, dass die Ansichten nichts sehen, was die API nicht hergibt.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

TEMPLATES = Path(__file__).parent / "templates"

router = APIRouter(prefix="/ui", tags=["Dashboard"], include_in_schema=False)


@lru_cache(maxsize=8)
def _page(name: str) -> str:
    """Lädt eine Seite und legt das gemeinsame Stylesheet hinein.

    Inline statt als eigener Request: das Dashboard soll ohne zusätzliche
    Route und ohne Cache-Fragen auskommen, und die Datei ist klein.
    """
    html = (TEMPLATES / name).read_text("utf-8")
    return html.replace("/*SHARED_CSS*/", (TEMPLATES / "_shared.css").read_text("utf-8"))


@router.get("/", response_class=HTMLResponse)
def developer_view() -> HTMLResponse:
    """Entwickleransicht: Zeitleiste, Trace-Inspektor, Graph, Replay."""
    return HTMLResponse(_page("dev.html"))


@router.get("/auskunft", response_class=HTMLResponse)
def disclosure_view() -> HTMLResponse:
    """Auskunftsansicht: Was wissen wir, woher, und was ginge bei einer Löschung mit."""
    return HTMLResponse(_page("auskunft.html"))


# Ohne diese Route protokolliert jeder Browser einen 404 in die Konsole --
# und eine Konsole voller Rauschen ist eine, in der niemand nach echten
# Fehlern sucht.
FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#1f5f4f"/>'
    '<path d="M16 6v20M16 12l-6 5M16 12l6 5" stroke="#e8f1ee" stroke-width="2.5" '
    'stroke-linecap="round" fill="none"/></svg>'
)


@router.get("/favicon.svg", include_in_schema=False)
def favicon() -> Response:
    return Response(FAVICON, media_type="image/svg+xml")

# Ein Container. Eine Datenbank.
#
# Das offizielle Postgres-Image ist die Grundlage, nicht ein Python-Image mit
# nachinstalliertem Postgres: initdb, Rechte, Signalbehandlung und das
# Datenverzeichnis sind dort bereits richtig gelöst.
FROM postgres:16-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv postgresql-16-pgvector \
 && rm -rf /var/lib/apt/lists/*

# Eigene Umgebung: das Systempython gehört dem Paketmanager (PEP 668).
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY evals ./evals
RUN pip install --no-cache-dir ".[mcp]"

COPY docker/entrypoint.sh /usr/local/bin/provenance-entrypoint
RUN chmod +x /usr/local/bin/provenance-entrypoint

ENV POSTGRES_USER=provenance \
    POSTGRES_PASSWORD=provenance \
    POSTGRES_DB=provenance \
    PROVENANCE_DATABASE_URL=postgresql://provenance:provenance@127.0.0.1:5432/provenance \
    PROVENANCE_HOST=0.0.0.0 \
    PROVENANCE_PORT=8080

EXPOSE 8080
VOLUME ["/var/lib/postgresql/data"]

HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"

ENTRYPOINT ["provenance-entrypoint"]
CMD ["serve"]

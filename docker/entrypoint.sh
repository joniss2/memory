#!/usr/bin/env bash
# Ein Container, eine Datenbank.
#
# Postgres läuft im selben Container wie die Anwendung. Wer eine externe
# Datenbank benutzt, setzt PROVENANCE_EMBEDDED_POSTGRES=0 und
# PROVENANCE_DATABASE_URL auf deren Adresse -- dann startet hier nur die
# Anwendung.
set -euo pipefail

EMBEDDED="${PROVENANCE_EMBEDDED_POSTGRES:-1}"
POSTGRES_PID=""

shutdown() {
  if [ -n "$POSTGRES_PID" ]; then
    echo "provenance: fahre Postgres herunter" >&2
    pg_ctl -D "$PGDATA" -m fast stop >/dev/null 2>&1 || kill -TERM "$POSTGRES_PID" 2>/dev/null || true
    wait "$POSTGRES_PID" 2>/dev/null || true
  fi
}
trap shutdown TERM INT EXIT

if [ "$EMBEDDED" = "1" ]; then
  echo "provenance: starte eingebettetes Postgres" >&2
  # Das Einstiegsskript des offiziellen Postgres-Images übernimmt initdb,
  # Rechte und die Rolle. Wir hängen uns nur davor.
  docker-entrypoint.sh postgres &
  POSTGRES_PID=$!

  for _ in $(seq 1 120); do
    if pg_isready -h 127.0.0.1 -U "${POSTGRES_USER:-provenance}" -q; then break; fi
    if ! kill -0 "$POSTGRES_PID" 2>/dev/null; then
      echo "provenance: Postgres ist beim Start gescheitert" >&2
      exit 1
    fi
    sleep 1
  done
  pg_isready -h 127.0.0.1 -U "${POSTGRES_USER:-provenance}" -q || {
    echo "provenance: Postgres wurde nicht rechtzeitig bereit" >&2
    exit 1
  }
fi

case "${1:-serve}" in
  serve)  shift || true; provenance serve "$@" ;;
  mcp)    shift || true; provenance-mcp "$@" ;;
  *)      provenance "$@" ;;
esac

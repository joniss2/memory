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
APP_PID=""

shutdown() {
  # Kein erneutes Auslösen, während wir schon herunterfahren.
  trap '' TERM INT

  if [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; then
    echo "provenance: beende die Anwendung" >&2
    kill -TERM "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi

  if [ -n "$POSTGRES_PID" ] && kill -0 "$POSTGRES_PID" 2>/dev/null; then
    echo "provenance: fahre Postgres herunter" >&2
    pg_ctl -D "${PGDATA:?}" -m fast stop >/dev/null 2>&1 \
      || kill -TERM "$POSTGRES_PID" 2>/dev/null || true
    wait "$POSTGRES_PID" 2>/dev/null || true
  fi
}

# Bewusst ohne EXIT: der Handler wird am Ende von Hand gerufen. Mit EXIT liefe
# er zusätzlich beim regulären Ende und wartete dort auf bereits beendete
# Prozesse.
trap shutdown TERM INT

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
    shutdown
    exit 1
  }
fi

# Die Anwendung läuft im Hintergrund, davor steht ein `wait`. Nur so kann Bash
# ein eintreffendes SIGTERM überhaupt bearbeiten: solange ein Vordergrundbefehl
# läuft, stellt es jeden Trap bis zu dessen Ende zurück -- und `docker stop`
# liefe in den SIGKILL, mit unsauber beendetem Postgres als Preis.
case "${1:-serve}" in
  serve)  shift || true; provenance serve "$@" & ;;
  mcp)    shift || true; provenance-mcp "$@" & ;;
  *)      provenance "$@" & ;;
esac
APP_PID=$!

# `wait` bricht ab, sobald ein abgefangenes Signal eintrifft; der Status ist
# dann 128+Signalnummer. Beides ist hier erwünscht.
set +e
wait "$APP_PID"
STATUS=$?
set -e

shutdown
exit "$STATUS"

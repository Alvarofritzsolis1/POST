#!/usr/bin/env bash
# No confundir el PostgreSQL temporal de initdb con el servidor definitivo.
# La imagen oficial postgres:16 arranca un postmaster temporal durante initdb;
# pg_isready puede responder OK y el postmaster cerrarse inmediatamente después.
set -Eeuo pipefail

container_name="${1:?Falta el contenedor PostgreSQL de restauración}"
db_user="${2:?Falta usuario}"
db_name="${3:?Falta base de datos}"

# Comprobar proceso definitivo (PID 1 ya reemplazado por postgres),
# Y una conexión SQL real; no aceptar pg_isready del postmaster temporal.
for attempt in $(seq 1 60); do
  if docker exec "$container_name" sh -c 'test "$(cat /proc/1/comm)" = "postgres"' >/dev/null 2>&1; then
    if probe="$(docker exec "$container_name" psql -U "$db_user" -d "$db_name" \
        -v ON_ERROR_STOP=1 -qtAX -c 'SELECT 1' 2>/dev/null)" && [[ "$probe" == "1" ]]; then
      echo "PostgreSQL definitivo listo para restauración aislada"
      exit 0
    fi
  fi
  sleep 2
done

echo "PostgreSQL temporal no alcanzó el estado estable: se cancela la restauración" >&2
docker logs --tail 40 "$container_name" >&2 || true
exit 3

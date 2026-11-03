#!/usr/bin/env bash
# Respaldo transaccional para el stack de previsualización GALANT POST.
# No modifica datos ni reinicia servicios.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")/.."
[[ -f .env.preview ]] || { echo "Falta .env.preview en el directorio del proyecto" >&2; exit 1; }
docker compose --env-file .env.preview -f docker-compose.preview.yml config --quiet
backup_dir="${GALANT_BACKUP_DIR:-/opt/galant-post-backups}"
mkdir -p -m 700 "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_dir/$stamp"
mkdir -m 700 "$target"
compose=(docker compose --env-file .env.preview -f docker-compose.preview.yml)
echo "Iniciando respaldo protegido de PostgreSQL y preview-storage…"
"${compose[@]}" exec -T db pg_dump -U galant -d galant --format=custom --no-owner --no-acl > "$target/postgres.dump"
test -s "$target/postgres.dump"
"${compose[@]}" exec -T db pg_restore --list < "$target/postgres.dump" >/dev/null
if [[ -d preview-storage ]]; then
  tar --create --gzip --file "$target/preview-storage.tar.gz" --directory . preview-storage
else
  echo "Directorio preview-storage no existe" >&2
  exit 1
fi
test -s "$target/preview-storage.tar.gz"
tar --list --gzip --file "$target/preview-storage.tar.gz" >/dev/null
(cd "$target" && sha256sum postgres.dump preview-storage.tar.gz > SHA256SUMS && sha256sum --check SHA256SUMS)
chmod 600 "$target"/*
echo "RESPALDO GENERADO Y ARCHIVOS VALIDOS: $target"
printf "BACKUP_PATH=%s\\n" "$target"
echo "Importante: esta verificación comprueba la legibilidad de archivos; no sustituye ensayo de restauración en BD aislada."

#!/usr/bin/env bash
# Verificación real de RESTAURACIÓN AISLADA. Nunca apunta a la BD ni a volúmenes activos.
set -Eeuo pipefail
umask 077

backup_dir="${1:?Indica el directorio del respaldo generado por backup-preview.sh}"
backup_dir="$(realpath "$backup_dir")"
[[ -d "$backup_dir" && -s "$backup_dir/postgres.dump" && -s "$backup_dir/preview-storage.tar.gz" && -s "$backup_dir/SHA256SUMS" ]] || {
  echo "Respaldo incompleto" >&2; exit 2;
}
(cd "$backup_dir" && sha256sum --check --status SHA256SUMS)
gzip -t "$backup_dir/preview-storage.tar.gz"

sandbox="$(mktemp -d /var/tmp/galant-restore-XXXXXXXX)"
chmod 700 "$sandbox"
mkdir -m 700 "$sandbox/pgdata"
container_name="galant-restore-${$}-$(date +%s)"
pass="$(openssl rand -hex 24)"
cleanup() {
  local status=$?
  trap - EXIT
  docker rm --force "$container_name" >/dev/null 2>&1 || true
  # PostgreSQL crea archivos propiedad de UID postgres; el runner CI no
  # puede borrarlos sin limpieza aislada con root dentro de Docker.
  if ! docker run --rm --pull never --network none \
      --entrypoint sh --mount "type=bind,src=$sandbox,dst=/sandbox" \
      postgres:16-alpine -c 'rm -rf -- /sandbox/pgdata' >/dev/null; then
    echo "No se pudieron eliminar los datos temporales de restauración" >&2
    status=1
  fi
  if ! rm -rf -- "$sandbox"; then
    echo "Quedaron archivos temporales: revisar permisos" >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT

echo "Iniciando PostgreSQL temporal sin puertos ni acceso a red"
docker run --rm -d --name "$container_name" \
  --network none \
  --memory=1g \
  --security-opt no-new-privileges \
  --mount "type=bind,src=$sandbox/pgdata,dst=/var/lib/postgresql/data" \
  -e POSTGRES_USER=galant_restore \
  -e POSTGRES_DB=galant_restore \
  -e POSTGRES_PASSWORD="$pass" \
  postgres:16-alpine >/dev/null

ready=0
for attempt in $(seq 1 45); do
  if docker exec "$container_name" pg_isready -q -U galant_restore -d galant_restore; then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 ]] || { echo "PostgreSQL temporal no inició" >&2; exit 3; }

docker exec -i "$container_name" pg_restore \
  --exit-on-error --single-transaction --no-owner --no-acl \
  -U galant_restore -d galant_restore < "$backup_dir/postgres.dump"

# El dump debe contener datos y restaurar sus relaciones en una BD nueva.
docker exec "$container_name" psql -U galant_restore -d galant_restore \
  -v ON_ERROR_STOP=1 -qtAX -c "SELECT count(*) FROM organizations;" >/dev/null
docker exec "$container_name" psql -U galant_restore -d galant_restore \
  -v ON_ERROR_STOP=1 -qtAX -c "SELECT count(*) FROM users;" >/dev/null
docker exec "$container_name" psql -U galant_restore -d galant_restore \
  -v ON_ERROR_STOP=1 -At -F $'\t' \
  -c "SELECT storage_path, sha256 FROM documents WHERE storage_path IS NOT NULL ORDER BY id;" \
  > "$sandbox/documents.tsv"

python3 - "$backup_dir/preview-storage.tar.gz" "$sandbox/documents.tsv" <<'PY'
import hashlib
import os
import pathlib
import sys
import tarfile

archive_path, manifest_path = sys.argv[1:]
with tarfile.open(archive_path, mode="r:gz") as archive:
    entries = {m.name: m for m in archive.getmembers()}
    for path, entry in entries.items():
        # No se extrae ningún archivo; se rechazan rutas peligrosas.
        parts = pathlib.PurePosixPath(path).parts
        if path.startswith("/") or ".." in parts:
            raise SystemExit("Rutas inseguras en respaldo de documentos")
        if entry.issym() or entry.islnk():
            raise SystemExit("No se admiten enlaces simbólicos en el respaldo")
    count = 0
    with open(manifest_path, encoding="utf-8") as file:
        for raw in file:
            location, digest = raw.rstrip("\n").split("\t", 1)
            prefix = "/data/private/"
            if not location.startswith(prefix):
                raise SystemExit("Ruta documental fuera del almacenamiento privado")
            relative = location[len(prefix):]
            member_name = "preview-storage/" + relative
            entry = entries.get(member_name)
            if entry is None or not entry.isfile():
                raise SystemExit("Un PDF registrado en PostgreSQL falta en el respaldo")
            payload = archive.extractfile(entry)
            if payload is None:
                raise SystemExit("Archivo no legible en el respaldo")
            checksum = hashlib.sha256()
            for chunk in iter(lambda: payload.read(1024 * 1024), b""):
                checksum.update(chunk)
            if checksum.hexdigest() != digest:
                raise SystemExit("La huella SHA256 de un documento no coincide")
            count += 1
    print(f"Restauración aislada verificada; archivos asociados contrastados: {count}")
PY

echo "RESTAURACIÓN DE ENSAYO CORRECTA: sin modificar servidor, volúmenes ni datos activos"

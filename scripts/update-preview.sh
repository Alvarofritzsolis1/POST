#!/usr/bin/env bash
# Actualiza el entorno aislado de GALANT desde un commit exacto y revierte si falla.
set -Eeuo pipefail
umask 077

target_ref="${1:?Indica el SHA de 40 caracteres que debe desplegarse}"
if [[ ! "$target_ref" =~ ^[0-9a-f]{40}$ ]]; then
    echo "El objetivo debe ser un SHA de commit de 40 caracteres." >&2
    exit 64
fi

repo_dir="${GALANT_DEPLOY_DIR:-}"
if [[ -z "$repo_dir" ]]; then
    repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$repo_dir"
if [[ $(id -u) -ne 0 ]]; then
    echo "La actualización debe ejecutarse como root." >&2
    exit 1
fi
if [[ ! -d .git || ! -f .env.preview ]]; then
    echo "Se requiere un checkout de GALANT y su archivo .env.preview existente." >&2
    exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Hay cambios locales rastreados; se cancela para no sobrescribirlos." >&2
    exit 1
fi

port="$(awk -F= '$1 == "PORT" { print $2; exit }' .env.preview)"
port="${port:-18512}"
if [[ ! "$port" =~ ^[0-9]{1,5}$ ]]; then
    echo "El puerto configurado no es válido." >&2
    exit 1
fi

compose=(docker compose --env-file .env.preview -f docker-compose.preview.yml)
previous_ref="$(git rev-parse HEAD)"
switched=0

wait_for_health() {
    local expected_version health attempt
    expected_version="$("${compose[@]}" exec -T api python -c 'from app.version import VERSION; print(VERSION)')"
    for attempt in {1..40}; do
        health="$(curl -fsS --max-time 4 "http://127.0.0.1:${port}/api/v1/health" 2>/dev/null || true)"
        if [[ "$health" == *'"status":"ok"'* && "$health" == *"\"version\":\"${expected_version}\""* ]]; then
            return 0
        fi
        sleep 3
    done
    return 1
}

rollback() {
    local status=$?
    trap - ERR
    if (( switched )); then
        echo "La actualización falló; restaurando ${previous_ref}." >&2
        if git checkout --detach "$previous_ref" \
            && "${compose[@]}" config --quiet \
            && COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" up -d --build db api worker frontend proxy \
            && "${compose[@]}" exec -T api python -m app.cli init-db \
            && wait_for_health; then
            echo "Se restauró la versión anterior." >&2
        else
            echo "La restauración automática también falló; revisa docker compose logs." >&2
        fi
    fi
    exit "$status"
}
trap rollback ERR

git fetch --no-tags --depth=1 origin "$target_ref"
git cat-file -e "${target_ref}^{commit}"
git checkout --detach "$target_ref"
switched=1
"${compose[@]}" config --quiet
# Antes de sustituir contenedores, restaurar el respaldo en PostgreSQL aislado.
# Un fallo de respaldo/restauración aborta la actualización; rollback restaura
# únicamente el checkout previo (el volumen de datos no se altera).
backup_output="$(bash scripts/backup-preview.sh)"
printf '%s\\n' "$backup_output"
backup_path="$(printf '%s\\n' "$backup_output" | sed -n 's/^BACKUP_PATH=//p' | tail -1)"
if [[ -z "$backup_path" || ! -d "$backup_path" ]]; then
    echo "No existe directorio de respaldo verificable; despliegue cancelado" >&2
    exit 1
fi
bash scripts/verify-restore-preview.sh "$backup_path"
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" up -d --build db api worker frontend proxy
"${compose[@]}" exec -T api python -m app.cli init-db
wait_for_health
trap - ERR
echo "GALANT actualizado a ${target_ref}."

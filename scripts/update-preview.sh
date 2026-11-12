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

previous_ref="$(git rev-parse HEAD)"
switched=0
previous_has_calc=0
[[ ! -f docker-compose.javiera20.yml ]] || previous_has_calc=1

configure_compose() {
    compose=(docker compose --env-file .env.preview)
    calc_services=()
    if [[ -f docker-compose.javiera20.yml ]]; then
        python3 scripts/prepare-javiera20-env.py .env.javiera20
        compose+=(--env-file .env.javiera20 -f docker-compose.preview.yml -f docker-compose.javiera20.yml)
        calc_services=(javiera-calc)
    else
        compose+=(-f docker-compose.preview.yml)
    fi
}
configure_compose

wait_for_health() {
    local expected_version health attempt expected_revision
    expected_revision="${1:-}"
    expected_version="$("${compose[@]}" exec -T api python -c 'from app.version import VERSION; print(VERSION)')"
    for attempt in {1..40}; do
        health="$(curl -fsS --max-time 4 "http://127.0.0.1:${port}/api/v1/health" 2>/dev/null || true)"
        if [[ "$health" == *'"status":"ok"'* && "$health" == *"\"version\":\"${expected_version}\""* && ( -z "$expected_revision" || "$health" == *"\"commit\":\"${expected_revision}\""* ) ]]; then
            return 0
        fi
        sleep 3
    done
    return 1
}

rollback() {
    local status=$?
    # EXIT captura también los 'exit 1' explícitos (ERR no lo hace).
    trap - EXIT ERR
    if (( status != 0 && switched )); then
        echo "La actualización falló; restaurando ${previous_ref}." >&2
        if (( ! previous_has_calc && ${#calc_services[@]} )); then
            "${compose[@]}" stop javiera-calc || true
        fi
        export SOURCE_COMMIT="$previous_ref"
        if git checkout --detach "$previous_ref" \
            && configure_compose \
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
trap rollback EXIT

git fetch --no-tags --depth=1 origin "$target_ref"
git cat-file -e "${target_ref}^{commit}"
git checkout --detach "$target_ref"
switched=1
configure_compose
"${compose[@]}" config --quiet
# Antes de sustituir contenedores, restaurar el respaldo en PostgreSQL aislado.
# Un fallo de respaldo/restauración aborta la actualización; rollback restaura
# únicamente el checkout previo (el volumen de datos no se altera).
backup_output="$(bash scripts/backup-preview.sh)"
printf '%s\n' "$backup_output"
backup_path="$(printf '%s\n' "$backup_output" | sed -n 's/^BACKUP_PATH=//p' | tail -1)"
if [[ -z "$backup_path" || ! -d "$backup_path" ]]; then
    echo "No existe directorio de respaldo verificable; despliegue cancelado" >&2
    exit 1
fi
bash scripts/verify-restore-preview.sh "$backup_path"
backup_sha256="$(sha256sum "$backup_path/postgres.dump" | cut -d' ' -f1)"
export SOURCE_COMMIT="$target_ref"
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" build api worker frontend "${calc_services[@]}"
# Freeze writers before reprojecting legacy attendance. Old rows remain intact.
# On failure the EXIT trap restores the previous containers; no volumes are removed.
"${compose[@]}" stop api worker
"${compose[@]}" run --rm --no-deps api python -m app.cli migrate-db --verified-backup-sha256 "$backup_sha256"
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" up -d --no-build db "${calc_services[@]}" api worker frontend proxy
wait_for_health "$target_ref"
# Check the exact build and additive migration, and exercise the authenticated
# Calc transport with a disposable workbook. No production dossier is created.
"${compose[@]}" exec -T api python -m app.deploy_verify --expected-commit "$target_ref"
python3 - "$port" "$target_ref" <<'PY'
import json, re, sys
from urllib.request import urlopen
base = "http://127.0.0.1:" + sys.argv[1]
with urlopen(base + "/api/v1/health", timeout=5) as response:
    health = json.load(response)
if health.get("status") != "ok" or health.get("commit") != sys.argv[2]:
    raise SystemExit("El proxy no está sirviendo el commit solicitado")
with urlopen(base + "/", timeout=5) as response:
    html = response.read().decode()
assets = re.findall(r'(?:src|href)="(/assets/[^"<>]+\.(?:js|css))"', html)
if 'id="root"' not in html or not assets:
    raise SystemExit("La portada no contiene la aplicación compilada")
for asset in assets:
    with urlopen(base + asset, timeout=5) as response:
        if response.status != 200 or not response.read(1):
            raise SystemExit("Un recurso del frontend no está disponible")
print(json.dumps({"proxy": "ok", "frontend_assets": len(assets), **health}))
PY
switched=0
trap - EXIT
echo "GALANT actualizado a ${target_ref}."

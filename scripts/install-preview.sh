#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd "$(dirname "\${BASH_SOURCE[0]}")/.."
if [[ $(id -u) -ne 0 ]]; then echo "Ejecuta con sudo." >&2; exit 1; fi
if ! grep -qi '^ID=ubuntu' /etc/os-release || ! grep -Eq '^VERSION_ID="?24[.]04"?' /etc/os-release; then
    echo "Requiere Ubuntu 24.04." >&2; exit 1
fi
for command_name in docker openssl curl ss; do
    command -v "$command_name" >/dev/null || { echo "Falta $command_name" >&2; exit 1; }
done
docker compose version >/dev/null || { echo "Se necesita Docker Compose v2." >&2; exit 1; }
if [[ ! -f .env.preview ]]; then
    secret=$(openssl rand -hex 48)
    password=$(openssl rand -hex 24)
    printf 'APP_SECRET=%s\nPOSTGRES_PASSWORD=%s\nOCR_LANGUAGE=spa+eng\nOCR_SECONDARY=disabled\nSECURE_COOKIES=false\nPORT=18512\n' "$secret" "$password" > .env.preview
    chmod 600 .env.preview
fi
if ! grep -Eq '^APP_SECRET=[[:xdigit:]]{64,}$' .env.preview || ! grep -Eq '^POSTGRES_PASSWORD=[[:xdigit:]]{32,}$' .env.preview; then
    echo "Credenciales de prueba invalidas"; exit 1
fi
free_memory=$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
free_disk=$(df -Pm . | awk 'NR==2 {print $4}')
echo "RAM libre: \${free_memory} MB; disco libre: \${free_disk} MB."
if (( free_memory < 2500 || free_disk < 5500 )); then
    echo "Insuficiente RAM/disco para mantener un segundo stack. No se hizo despliegue." >&2
    exit 1
fi
if ss -lntH 'sport = :18512' | grep -q . && ! docker ps --format '{{.Names}}' | grep -q 'galant-post-preview-proxy-'; then
    echo "Puerto 18512 ya ocupado; no tocar otros servicios." >&2
    exit 1
fi
install -d -m 0700 preview-storage
chown 10001:10001 preview-storage
compose=(docker compose --env-file .env.preview -f docker-compose.preview.yml)
"\${compose[@]}" config --quiet
COMPOSE_PARALLEL_LIMIT=1 "\${compose[@]}" build
"\${compose[@]}" up -d db api worker frontend proxy
"\${compose[@]}" exec -T api python -m app.cli init-db
ok=0
for i in {1..35}; do
    if curl -fsS --max-time 4 http://127.0.0.1:18512/api/v1/health | grep -q '"status":"ok"'; then ok=1; break; fi
    sleep 3
done
if (( ok == 0 )); then
    "\${compose[@]}" ps
    "\${compose[@]}" logs --tail=50 api db proxy
    echo "No se verificó salud del servicio" >&2
    exit 1
fi
echo "GALANT POST en http://127.0.0.1:18512 (solo VPS local)."
echo "Crear admin: docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-admin --email TU@EMPRESA.CL"
echo "Desde PowerShell Windows: ssh -N -L 18512:127.0.0.1:18512 root@89.117.144.140"
echo "Visitar http://127.0.0.1:18512 (solo documentos sintéticos)."

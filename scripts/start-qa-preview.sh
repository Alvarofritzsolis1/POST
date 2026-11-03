#!/usr/bin/env bash
# Crea un entorno QA completamente separado para validar la rama de GALANT POST
# durante 24 horas. No modifica checkout, BD ni archivos de la instancia activa.
set -Eeuo pipefail
umask 077

[[ $(id -u) == 0 ]] || { echo "Ejecutar como root para Docker" >&2; exit 1; }
live_dir="${GALANT_BASE_DIR:-/opt/galant-post}"
qa_dir="${GALANT_QA_DIR:-/opt/galant-post-qa}"
branch="feat/galant-operational-control-20261103"
[[ -d "$live_dir/.git" || -f "$live_dir/.git" ]] || {
  echo "No existe el checkout original en $live_dir" >&2; exit 2;
}
[[ ! -e "$qa_dir" ]] || {
  echo "Ya existe $qa_dir. No se sobrescribirá una instalación QA existente." >&2; exit 2;
}

free_kib="$(awk '/MemAvailable:/ {print $2; exit}' /proc/meminfo)"
disk_kib="$(df -Pk /opt | awk 'NR==2 {print $4}')"
if [[ "${free_kib:-0}" -lt 950000 || "${disk_kib:-0}" -lt 1500000 ]]; then
  echo "Memoria o disco insuficientes para crear una instancia de ensayo sin comprometer la principal." >&2
  exit 3
fi

cd "$live_dir"
remote="$(git remote get-url origin)"
case "$remote" in
  "https://github.com/Alvarofritzsolis1/POST.git"|"git@github.com:Alvarofritzsolis1/POST.git") ;;
  *) echo "Repo remoto distinto de POST, detenido." >&2; exit 3;;
esac

git fetch --no-tags origin "$branch"
target_sha="$(git rev-parse FETCH_HEAD)"
git worktree add --detach "$qa_dir" "$target_sha"
cd "$qa_dir"
mkdir -m 700 qa-storage

cat > .env.qa <<ENVIRONMENT
APP_SECRET=$(openssl rand -hex 48)
POSTGRES_PASSWORD=$(openssl rand -hex 32)
PORT=18612
SECURE_COOKIES=false
ENVIRONMENT
chmod 600 .env.qa

compose=(docker compose -p galant-post-qa --env-file .env.qa -f docker-compose.preview.yml -f docker-compose.qa.yml)
"${compose[@]}" config --quiet
# Recalcular la config por stdin simple; verifica todos los montajes críticos.
config_file="$(mktemp)"
trap 'rm -f "$config_file"' EXIT
"${compose[@]}" config --format json > "$config_file"
python3 - "$qa_dir" "$config_file" <<'PY'
import json, pathlib, sys
base = pathlib.Path(sys.argv[1]).resolve()
with open(sys.argv[2], encoding="utf-8") as handle:
    config = json.load(handle)
assert config["name"] == "galant-post-qa"
for service in ("api", "worker"):
    volumes = config["services"][service]["volumes"]
    matches = [volume for volume in volumes if volume.get("target") == "/data/private"]
    assert len(matches) == 1 and pathlib.Path(matches[0]["source"]).resolve() == base/"qa-storage", (
        service + " points to non-isolated storage"
    )
ports = config["services"]["proxy"]["ports"]
assert len(ports) == 1 and ports[0].get("host_ip") == "127.0.0.1"
assert str(ports[0].get("published")) == "18612"
print("QA isolation verified")
PY

# En QA se arranca un worker administrativo liviano y no el motor OCR.
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" up -d --build db api worker frontend proxy
"${compose[@]}" exec -T api python -m app.cli init-db

expected_version="$("${compose[@]}" exec -T api python -c 'from app.version import VERSION; print(VERSION)')"
health=""
for attempt in $(seq 1 40); do
  health="$(curl -fsS --max-time 5 http://127.0.0.1:18612/api/v1/health 2>/dev/null || true)"
  if [[ "$health" == *'"status":"ok"'* && "$health" == *"\"version\":\"${expected_version}\""* ]]; then break; fi
  sleep 3
done
if [[ "$health" != *'"status":"ok"'* || "$health" != *"\"version\":\"${expected_version}\""* ]]; then
  echo "QA no superó healthcheck: revisar docker compose logs" >&2; exit 4
fi
echo "ENTORNO QA AISLADO PREPARADO: http://127.0.0.1:18612 (solo loopback)"
echo "Rama validada: $target_sha"
echo "Crear cuentas sintéticas con: cd $qa_dir && docker compose -p galant-post-qa --env-file .env.qa -f docker-compose.preview.yml -f docker-compose.qa.yml exec api python -m app.cli create-admin --email administrador.qa@example.test"
echo "Crear el segundo usuario con create-user --admin-email administrador.qa@example.test"
echo "No cargar información laboral real ni usar passwords de producción."

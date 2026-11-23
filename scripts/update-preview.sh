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
    facebook_services=()
    training_services=()
    max_power_services=()
    if grep -q "^  max-power-controller:" docker-compose.preview.yml; then
        max_power_services=(max-power-controller galancito-training-ollama cpu-lora-manager)
        compose+=(--profile max-power-auto)
    fi
    if grep -q "^  facebook-publisher:" docker-compose.preview.yml; then
        facebook_services=(facebook-publisher)
    fi
    if grep -q "^  galancito-trainer:" docker-compose.preview.yml; then
        training_services=(galancito-trainer)
        compose+=(--profile training)
    fi
    if [[ -f docker-compose.javiera20.yml ]]; then
        python3 scripts/prepare-javiera20-env.py .env.javiera20
        compose+=(--env-file .env.javiera20 -f docker-compose.preview.yml -f docker-compose.javiera20.yml)
        calc_services=(javiera-calc)
    else
        compose+=(-f docker-compose.preview.yml)
    fi
}
configure_compose
previous_training=()
previous_max_power=()
for service in "${max_power_services[@]}"; do
    if [[ -n "$("${compose[@]}" ps --status running --quiet "$service")" ]]; then
        previous_max_power+=("$service")
    fi
done
for service in "${training_services[@]}"; do
    if [[ -n "$("${compose[@]}" ps --status running --quiet "$service")" ]]; then
        previous_training+=("$service")
    fi
done

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
        # Detener el publicador nuevo antes de restaurar un Compose anterior.
        if (( ${#facebook_services[@]} )); then
            "${compose[@]}" stop "${facebook_services[@]}" || true
        fi
        if (( ${#training_services[@]} )); then
            "${compose[@]}" stop "${training_services[@]}" || true
        fi
        if (( ${#max_power_services[@]} )); then
            "${compose[@]}" stop "${max_power_services[@]}" || true
        fi
        if (( ! previous_has_calc && ${#calc_services[@]} )); then
            "${compose[@]}" stop javiera-calc || true
        fi
        export SOURCE_COMMIT="$previous_ref"
        if git checkout --detach "$previous_ref" \
            && configure_compose \
            && "${compose[@]}" config --quiet \
            && COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" up -d --build db api worker "${facebook_services[@]}" frontend proxy "${previous_training[@]}" "${previous_max_power[@]}" \
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
# The secret is generated once on the VPS, before recreating the API container.
# The existing value is never overwritten and no key is printed in Actions logs.
python3 scripts/ensure-ai-key.py .env.preview
# Allow the new CPU LoRA / GPU QLoRA dashboard to receive authenticated
# measurements without requiring manual secret provisioning. Never starts
# training or logs the generated secret.
python3 scripts/ensure-finetune-metrics-key.py .env.preview
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
if (( ${#training_services[@]} )); then
    "${compose[@]}" pull galancito-training-ollama
fi
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" build api worker "${facebook_services[@]}" frontend "${calc_services[@]}" galancito-trainer "${max_power_services[@]}"
# Freeze writers before reprojecting legacy attendance. Old rows remain intact.
# On failure the EXIT trap restores the previous containers; no volumes are removed.
"${compose[@]}" stop api worker "${facebook_services[@]}" "${training_services[@]}" "${max_power_services[@]}"
"${compose[@]}" run --rm --no-deps api python -m app.cli migrate-db --verified-backup-sha256 "$backup_sha256"
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" up -d --no-build db "${calc_services[@]}" api worker "${facebook_services[@]}" frontend proxy "${training_services[@]}" "${max_power_services[@]}"
# Fail the release if the actual running API cannot encrypt stored credentials.
"${compose[@]}" exec -T api python -c "from app.ai_gateway import encryption_ready; assert encryption_ready(), 'Cifrado IA sin inicializar'"
wait_for_health "$target_ref"
# An API health check alone does not prove the MAX POWER conductor runs.
if (( ${#max_power_services[@]} )); then
    for i in {1..12}; do
        [[ -n "$("${compose[@]}" ps --status running --quiet max-power-controller)" ]] && break
        sleep 2
    done
    [[ -n "$("${compose[@]}" ps --status running --quiet max-power-controller)" ]] || {
        echo "MAX POWER no quedó operativo; se revierte el despliegue." >&2
        exit 1
    }
    controller_id="$("${compose[@]}" ps --quiet max-power-controller)"
    for i in {1..15}; do
        health="$(docker inspect --format '{{.State.Health.Status}}' "$controller_id" 2>/dev/null || true)"
        [[ "$health" == "healthy" ]] && break
        sleep 4
    done
    [[ "$health" == "healthy" ]] || {
        echo "MAX POWER no supera su comprobación de controlador y base de datos." >&2
        exit 1
    }
    "${compose[@]}" exec -T api python -c "from app.max_power_api import router; from app.max_power_models import MaxPowerState, MaxPowerEvent, MaxPowerMessengerTrial; assert any(r.path.endswith('/export') for r in router.routes)"
    # The one-button training supervisor is a required authenticated service.
    manager_id="$("${compose[@]}" ps --quiet cpu-lora-manager)"
    [[ -n "$manager_id" ]] || { echo "Supervisor neuronal CPU ausente; se revierte." >&2; exit 1; }
    manager_health=""
    for i in {1..15}; do
        manager_health="$(docker inspect --format '{{.State.Health.Status}}' "$manager_id" 2>/dev/null || true)"
        [[ "$manager_health" == "healthy" ]] && break
        sleep 4
    done
    [[ "$manager_health" == "healthy" ]] || { echo "Supervisor neuronal sin heartbeat; se revierte." >&2; exit 1; }
    echo "MAX POWER: supervisor neuronal operativo; no se entrenan pesos sin dataset firmado."
fi
"${compose[@]}" exec -T api python -m app.deploy_verify --expected-commit "$target_ref" --training-worker-only
# Check the exact build and additive migration, and exercise the authenticated
# Calc transport with a disposable workbook. No production dossier is created.
"${compose[@]}" exec -T api python -m app.deploy_verify --expected-commit "$target_ref"
# Non-blocking, real VPS check. Never installs a model, logs chat texts,
# touches production records or makes an external API call.
"${compose[@]}" exec -T api python - <<'PY' || true
from app.config import settings
from app.galancito_general import QWEN_4B
from app.galancito_local import installed_model_status, generate_local_text, last_timings

cfg = settings()
if not cfg.galancito_local_ai_enabled or cfg.galancito_local_model != QWEN_4B:
    print("GALANCITO_MODEL_CHECK=not_configured")
elif installed_model_status(QWEN_4B) is not True:
    print("GALANCITO_MODEL_CHECK=not_confirmed_installed")
else:
    try:
        answer = generate_local_text(
            "Verificación sin datos de usuarios. Responde solo OK.", "OK", max_chars=40)
        actual = last_timings.get().get("response_model")
        valid = actual == QWEN_4B and answer.strip().casefold().strip(".! ") == "ok"
        print("GALANCITO_MODEL_CHECK=" + ("verified_4b" if valid else "unverified"))
        print("GALANCITO_MODEL_TAG=" + str(actual or "unreported"))
    except (OSError, RuntimeError, TimeoutError, ValueError):
        print("GALANCITO_MODEL_CHECK=unavailable_or_busy")
PY
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
